from datetime import date, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestDashboardPeriod(TransactionCase):

    def setUp(self):
        super().setUp()
        self.dashboard = self.env["hdqt.dashboard"]

    def test_previous_window_has_the_same_length(self):
        period = self.dashboard._period("2026-09-01", "2026-09-30")
        span = (period["stop"] - period["start"]).days
        previous_span = (period["previous_stop"] - period["previous_start"]).days
        self.assertEqual(span, previous_span)

    def test_previous_window_ends_the_day_before(self):
        period = self.dashboard._period("2026-09-01", "2026-09-30")
        self.assertEqual(period["previous_stop"], date(2026, 8, 31))

    def test_reversed_dates_are_swapped_not_rejected(self):
        period = self.dashboard._period("2026-09-30", "2026-09-01")
        self.assertEqual(period["start"], date(2026, 9, 1))
        self.assertEqual(period["stop"], date(2026, 9, 30))

    def test_garbage_dates_fall_back_to_the_default_window(self):
        period = self.dashboard._period("not-a-date", "nonsense")
        today = fields.Date.context_today(self.dashboard)
        self.assertEqual(period["stop"], today)
        self.assertEqual(period["start"], today.replace(day=1))

    def test_month_axis_is_chronological_and_complete(self):
        axis = self.dashboard._month_axis(date(2026, 9, 25), months=12)
        self.assertEqual(len(axis), 12)
        self.assertEqual(axis[-1], date(2026, 9, 1))
        self.assertEqual(axis[0], date(2025, 10, 1))
        self.assertEqual(axis, sorted(axis))


@tagged("post_install", "-at_install")
class TestDashboardMath(TransactionCase):

    def setUp(self):
        super().setUp()
        self.dashboard = self.env["hdqt.dashboard"]

    def test_delta_percentage(self):
        self.assertEqual(self.dashboard._delta(150, 100), 50.0)
        self.assertEqual(self.dashboard._delta(50, 100), -50.0)

    def test_delta_is_none_without_a_baseline(self):
        """Dividing by a zero baseline would report an infinite jump."""
        self.assertIsNone(self.dashboard._delta(100, 0))

    def test_delta_against_a_negative_baseline_uses_magnitude(self):
        self.assertEqual(self.dashboard._delta(-50, -100), 50.0)

    def test_bucket_by_month_normalises_to_month_start(self):
        rows = [(date(2026, 3, 17), 500.0), (date(2026, 4, 2), 250.0)]
        buckets = self.dashboard._bucket_by_month(rows)
        self.assertEqual(buckets[date(2026, 3, 1)], 500.0)
        self.assertEqual(buckets[date(2026, 4, 1)], 250.0)

    def test_bucket_by_month_skips_empty_keys(self):
        self.assertEqual(self.dashboard._bucket_by_month([(False, 100.0)]), {})


@tagged("post_install", "-at_install")
class TestDashboardScope(TransactionCase):

    def setUp(self):
        super().setUp()
        self.dashboard = self.env["hdqt.dashboard"]

    def test_companies_default_to_everything_the_user_may_see(self):
        self.assertEqual(self.dashboard._companies(), self.env.user.company_ids)

    def test_companies_cannot_be_widened_by_the_query_string(self):
        """A crafted company_ids must never reach a company the user cannot see."""
        stranger = self.env["res.company"].create({"name": "Not mine"})
        resolved = self.dashboard._companies([stranger.id])
        self.assertNotIn(stranger, resolved)
        self.assertEqual(resolved, self.env.user.company_ids)

    def test_companies_can_be_narrowed(self):
        allowed = self.env.user.company_ids
        resolved = self.dashboard._companies([allowed[0].id])
        self.assertEqual(resolved, allowed[0])

    def test_missing_model_yields_zero_not_an_error(self):
        with patch.object(type(self.dashboard), "_has", return_value=False):
            self.assertEqual(self.dashboard._sum("sale.order", [], "amount_total"), 0.0)
            self.assertEqual(self.dashboard._count("sale.order", []), 0)


@tagged("post_install", "-at_install")
class TestDashboardPayload(TransactionCase):

    def test_payload_has_every_section(self):
        data = self.env["hdqt.dashboard"].get_dashboard_data()
        for key in ("period", "currency", "companies", "kpis",
                    "revenue_trend", "top_customers", "ar_aging",
                    "operations", "generated_at"):
            self.assertIn(key, data)

    def test_trend_axis_matches_the_series_length(self):
        data = self.env["hdqt.dashboard"].get_dashboard_data()
        trend = data["revenue_trend"]
        self.assertEqual(len(trend["labels"]), len(trend["full_labels"]))
        for series in trend["series"]:
            self.assertEqual(len(series["points"]), len(trend["labels"]),
                             "every month on the axis needs a point, gaps included")

    def test_payload_is_json_serialisable(self):
        import json
        data = self.env["hdqt.dashboard"].get_dashboard_data()
        json.loads(json.dumps(data, default=str))

    def test_kpis_declare_a_format_the_page_can_render(self):
        data = self.env["hdqt.dashboard"].get_dashboard_data()
        for kpi in data["kpis"]:
            self.assertIn(kpi["format"], ("currency", "integer"))
            self.assertIn(kpi["delta_good"], ("up", "down"))


@tagged("post_install", "-at_install")
class TestArAging(TransactionCase):
    """The ageing split is the one figure computed in Python rather than SQL."""

    def setUp(self):
        super().setUp()
        self.dashboard = self.env["hdqt.dashboard"]
        self.today = fields.Date.context_today(self.dashboard)

    def _fake_moves(self, offsets):
        return [
            {"invoice_date_due": self.today - timedelta(days=days), "amount_residual_signed": 100.0}
            for days in offsets
        ]

    def _aging(self, offsets):
        with patch.object(
            type(self.env["account.move"]), "search_read", return_value=self._fake_moves(offsets)
        ):
            return {row["key"]: row["value"] for row in self.dashboard._ar_aging(self.env.companies)}

    def test_not_yet_due_and_due_today_are_current(self):
        result = self._aging([-5, 0])
        self.assertEqual(result["current"], 200.0)

    def test_boundaries_land_in_the_expected_bucket(self):
        result = self._aging([1, 30, 31, 60, 61])
        self.assertEqual(result["d1_30"], 200.0, "1 and 30 days")
        self.assertEqual(result["d31_60"], 200.0, "31 and 60 days")
        self.assertEqual(result["d60p"], 100.0, "61 days")

    def test_every_bucket_is_present_even_when_empty(self):
        keys = [row["key"] for row in self.dashboard._ar_aging(self.env.companies)]
        self.assertEqual(keys, ["current", "d1_30", "d31_60", "d60p"])
