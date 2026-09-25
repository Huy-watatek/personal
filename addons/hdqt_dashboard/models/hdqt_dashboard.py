"""Aggregations behind /hdqt/dashboard.

Every figure comes from a stored column of a standard Odoo model, so the
dashboard never needs its own bookkeeping:

    sale.order       amount_total, date_order, state, partner_id
    account.move     amount_total_signed, amount_residual_signed, invoice_date,
                     invoice_date_due, move_type, state, payment_state
    stock.picking    state, scheduled_date
    stock.quant      value (from stock_account), location_id.usage
    mrp.production   state, date_start

Reads are done with elevated rights on purpose: a board member is not an
accountant and should not need read access to account.move to see a revenue
total. Membership of ``hdqt_dashboard.group_hdqt_viewer`` is therefore the only
gate, and every domain pins company_id explicitly because sudo() also drops the
multi-company record rules.
"""

import logging
from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

MONTHS_ON_TREND = 12
TOP_CUSTOMERS = 10

SALE_CONFIRMED = ("sale",)
PICKING_OPEN = ("waiting", "confirmed", "assigned")
MRP_OPEN = ("confirmed", "progress", "to_close")
CUSTOMER_INVOICES = ("out_invoice", "out_refund")


class HdqtDashboard(models.AbstractModel):
    _name = "hdqt.dashboard"
    _description = "Board Executive Dashboard"

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def _has(self, model_name):
        """True when ``model_name`` is installed in this database."""
        return model_name in self.env

    def _companies(self, company_ids=None):
        """Restrict the request to companies the current user may actually see."""
        allowed = self.env.user.company_ids
        if not company_ids:
            return allowed
        wanted = allowed.filtered(lambda company: company.id in set(company_ids))
        return wanted or allowed

    @api.model
    def _parse_date(self, value, fallback):
        if not value:
            return fallback
        try:
            return fields.Date.to_date(value)
        except (ValueError, TypeError):
            return fallback

    def _period(self, date_from, date_to):
        """Return the requested window plus the equal-length window before it."""
        today = fields.Date.context_today(self)
        stop = self._parse_date(date_to, today)
        start = self._parse_date(date_from, stop.replace(day=1))
        if start > stop:
            start, stop = stop, start
        span = (stop - start).days + 1
        return {
            "start": start,
            "stop": stop,
            "previous_start": start - relativedelta(days=span),
            "previous_stop": start - relativedelta(days=1),
        }

    @staticmethod
    def _as_datetime_bounds(start, stop):
        """Datetime fields need the full day, not the bare date."""
        return datetime.combine(start, time.min), datetime.combine(stop, time.max)

    def _sum(self, model_name, domain, field):
        """Sum one stored column, or 0.0 when the model is not installed."""
        if not self._has(model_name):
            return 0.0
        groups = self.env[model_name].sudo()._read_group(domain, [], ["%s:sum" % field])
        return (groups[0][0] or 0.0) if groups else 0.0

    def _count(self, model_name, domain):
        if not self._has(model_name):
            return 0
        return self.env[model_name].sudo().search_count(domain)

    @staticmethod
    def _delta(current, previous):
        """Percentage change, or None when there is no baseline to compare to."""
        if not previous:
            return None
        return round((current - previous) / abs(previous) * 100.0, 1)

    # ------------------------------------------------------------------
    # Domains — one place per module, so a column rename is a single edit
    # ------------------------------------------------------------------

    def _sale_domain(self, companies, start, stop):
        date_from, date_to = self._as_datetime_bounds(start, stop)
        return [
            ("state", "in", SALE_CONFIRMED),
            ("company_id", "in", companies.ids),
            ("date_order", ">=", date_from),
            ("date_order", "<=", date_to),
        ]

    def _invoice_domain(self, companies, start, stop):
        return [
            ("move_type", "in", CUSTOMER_INVOICES),
            ("state", "=", "posted"),
            ("company_id", "in", companies.ids),
            ("invoice_date", ">=", start),
            ("invoice_date", "<=", stop),
        ]

    def _receivable_domain(self, companies):
        """Open customer balance — a snapshot, deliberately not time-bounded."""
        return [
            ("move_type", "in", CUSTOMER_INVOICES),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
            ("company_id", "in", companies.ids),
        ]

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def _kpis(self, companies, period):
        """The headline row. Each entry is one stat tile."""
        start, stop = period["start"], period["stop"]
        prev_start, prev_stop = period["previous_start"], period["previous_stop"]
        tiles = []

        if self._has("sale.order"):
            current = self._sum("sale.order", self._sale_domain(companies, start, stop), "amount_total")
            previous = self._sum("sale.order", self._sale_domain(companies, prev_start, prev_stop), "amount_total")
            tiles.append({
                "key": "sale_amount",
                "label": _("Confirmed sales"),
                "value": current,
                "format": "currency",
                "delta": self._delta(current, previous),
                "delta_good": "up",
                "hint": _("sale.order · state = Sales Order · by order date"),
            })
            tiles.append({
                "key": "sale_count",
                "label": _("Sales orders"),
                "value": self._count("sale.order", self._sale_domain(companies, start, stop)),
                "format": "integer",
                "delta": self._delta(
                    self._count("sale.order", self._sale_domain(companies, start, stop)),
                    self._count("sale.order", self._sale_domain(companies, prev_start, prev_stop)),
                ),
                "delta_good": "up",
                "hint": _("sale.order · number of confirmed orders"),
            })

        if self._has("account.move"):
            current = self._sum(
                "account.move", self._invoice_domain(companies, start, stop), "amount_total_signed"
            )
            previous = self._sum(
                "account.move", self._invoice_domain(companies, prev_start, prev_stop), "amount_total_signed"
            )
            tiles.append({
                "key": "invoiced",
                "label": _("Invoiced"),
                "value": current,
                "format": "currency",
                "delta": self._delta(current, previous),
                "delta_good": "up",
                "hint": _("account.move · posted customer invoices, refunds netted"),
            })

            overdue_domain = self._receivable_domain(companies) + [
                ("invoice_date_due", "<", fields.Date.context_today(self)),
            ]
            tiles.append({
                "key": "overdue",
                "label": _("Overdue receivables"),
                "value": self._sum("account.move", overdue_domain, "amount_residual_signed"),
                "format": "currency",
                "delta": None,
                "delta_good": "down",
                "hint": _("account.move · unpaid past due date · snapshot, not period-bound"),
            })

        inventory_value = self._inventory_value(companies)
        if inventory_value is not None:
            tiles.append({
                "key": "stock_value",
                "label": _("Inventory value"),
                "value": inventory_value,
                "format": "currency",
                "delta": None,
                "delta_good": "down",
                "hint": _("stock.quant · internal locations · current valuation"),
            })

        if self._has("mrp.production"):
            tiles.append({
                "key": "mrp_open",
                "label": _("Open manufacturing orders"),
                "value": self._count("mrp.production", [
                    ("state", "in", MRP_OPEN),
                    ("company_id", "in", companies.ids),
                ]),
                "format": "integer",
                "delta": None,
                "delta_good": "down",
                "hint": _("mrp.production · confirmed, in progress or to close"),
            })

        if self._has("stock.picking"):
            tiles.append({
                "key": "picking_late",
                "label": _("Late transfers"),
                "value": self._count("stock.picking", [
                    ("state", "in", PICKING_OPEN),
                    ("company_id", "in", companies.ids),
                    ("scheduled_date", "<", fields.Datetime.now()),
                ]),
                "format": "integer",
                "delta": None,
                "delta_good": "down",
                "hint": _("stock.picking · still open past its scheduled date"),
            })

        return tiles

    def _inventory_value(self, companies):
        """Current stock valuation, or None when stock_account is not installed.

        ``stock.quant.value`` is a non-stored compute, so it cannot be summed by
        the database; Odoo batches the compute over the whole recordset, which
        keeps this to a single pass.
        """
        if not self._has("stock.quant"):
            return None
        Quant = self.env["stock.quant"].sudo()
        if "value" not in Quant._fields:
            return None
        quants = Quant.search([
            ("location_id.usage", "=", "internal"),
            ("company_id", "in", companies.ids),
        ])
        return sum(quants.mapped("value"))

    def _month_axis(self, stop, months=MONTHS_ON_TREND):
        """The last ``months`` month-starts, oldest first."""
        first = stop.replace(day=1)
        return [first - relativedelta(months=offset) for offset in range(months - 1, -1, -1)]

    @staticmethod
    def _bucket_by_month(rows):
        """Turn ``_read_group`` output into {month-start date: value}."""
        out = {}
        for key, value in rows:
            if not key:
                continue
            moment = fields.Date.to_date(key) if isinstance(key, str) else key
            if hasattr(moment, "date"):
                moment = moment.date()
            out[moment.replace(day=1)] = value or 0.0
        return out

    def _revenue_trend(self, companies, period):
        """Booked vs invoiced over the trailing months — two measures, one scale."""
        axis = self._month_axis(period["stop"])
        window_start, window_stop = axis[0], period["stop"]
        series = []

        if self._has("sale.order"):
            rows = self.env["sale.order"].sudo()._read_group(
                self._sale_domain(companies, window_start, window_stop),
                ["date_order:month"],
                ["amount_total:sum"],
            )
            by_month = self._bucket_by_month(rows)
            series.append({
                "key": "ordered",
                "label": _("Confirmed sales"),
                "points": [by_month.get(month, 0.0) for month in axis],
            })

        if self._has("account.move"):
            rows = self.env["account.move"].sudo()._read_group(
                self._invoice_domain(companies, window_start, window_stop),
                ["invoice_date:month"],
                ["amount_total_signed:sum"],
            )
            by_month = self._bucket_by_month(rows)
            series.append({
                "key": "invoiced",
                "label": _("Invoiced"),
                "points": [by_month.get(month, 0.0) for month in axis],
            })

        return {
            "labels": ["%02d/%s" % (month.month, str(month.year)[2:]) for month in axis],
            "full_labels": [month.strftime("%m/%Y") for month in axis],
            "series": series,
        }

    def _top_customers(self, companies, period):
        if not self._has("sale.order"):
            return []
        rows = self.env["sale.order"].sudo()._read_group(
            self._sale_domain(companies, period["start"], period["stop"]),
            ["partner_id"],
            ["amount_total:sum"],
            order="amount_total:sum desc",
            limit=TOP_CUSTOMERS,
        )
        return [
            {"label": partner.display_name if partner else _("Unknown"), "value": total or 0.0}
            for partner, total in rows
        ]

    def _ar_aging(self, companies):
        """Open receivables split into ordered ageing buckets."""
        if not self._has("account.move"):
            return []
        today = fields.Date.context_today(self)
        moves = self.env["account.move"].sudo().search_read(
            self._receivable_domain(companies),
            ["invoice_date_due", "amount_residual_signed"],
        )
        buckets = [
            {"key": "current", "label": _("Not yet due"), "value": 0.0},
            {"key": "d1_30", "label": _("1–30 days"), "value": 0.0},
            {"key": "d31_60", "label": _("31–60 days"), "value": 0.0},
            {"key": "d60p", "label": _("Over 60 days"), "value": 0.0},
        ]
        for move in moves:
            due = move.get("invoice_date_due")
            amount = move.get("amount_residual_signed") or 0.0
            overdue_days = (today - fields.Date.to_date(due)).days if due else 0
            if overdue_days <= 0:
                index = 0
            elif overdue_days <= 30:
                index = 1
            elif overdue_days <= 60:
                index = 2
            else:
                index = 3
            buckets[index]["value"] += amount
        return buckets

    def _state_breakdown(self, model_name, domain, states):
        """Count records per state, keeping the model's own state order."""
        if not self._has(model_name):
            return []
        model = self.env[model_name].sudo()
        labels = dict(model._fields["state"]._description_selection(self.env))
        rows = dict(model._read_group(domain, ["state"], ["__count"]))
        return [
            {"key": state, "label": labels.get(state, state), "value": rows.get(state, 0)}
            for state in states
        ]

    def _operations(self, companies):
        return {
            "mrp": self._state_breakdown(
                "mrp.production",
                [("state", "in", MRP_OPEN), ("company_id", "in", companies.ids)],
                MRP_OPEN,
            ),
            "picking": self._state_breakdown(
                "stock.picking",
                [("state", "in", PICKING_OPEN), ("company_id", "in", companies.ids)],
                PICKING_OPEN,
            ),
        }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, company_ids=None):
        companies = self._companies(company_ids)
        period = self._period(date_from, date_to)
        currency = companies[:1].currency_id or self.env.company.currency_id

        return {
            "period": {
                "from": fields.Date.to_string(period["start"]),
                "to": fields.Date.to_string(period["stop"]),
                "previous_from": fields.Date.to_string(period["previous_start"]),
                "previous_to": fields.Date.to_string(period["previous_stop"]),
            },
            "currency": {
                "symbol": currency.symbol or "",
                "position": currency.position or "after",
                "decimals": currency.decimal_places,
            },
            "companies": [
                {"id": company.id, "name": company.name, "selected": company in companies}
                for company in self.env.user.company_ids
            ],
            "kpis": self._kpis(companies, period),
            "revenue_trend": self._revenue_trend(companies, period),
            "top_customers": self._top_customers(companies, period),
            "ar_aging": self._ar_aging(companies),
            "operations": self._operations(companies),
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
        }
