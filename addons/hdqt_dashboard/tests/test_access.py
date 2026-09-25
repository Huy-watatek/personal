from odoo.tests import tagged
from odoo.tests.common import HttpCase, new_test_user


@tagged("post_install", "-at_install")
class TestDashboardAccess(HttpCase):
    """The viewer group is the only gate, so it has to hold."""

    def setUp(self):
        super().setUp()
        self.viewer = new_test_user(
            self.env, login="hdqt_viewer", password="hdqt_viewer",
            groups="base.group_user,hdqt_dashboard.group_hdqt_viewer",
        )
        self.outsider = new_test_user(
            self.env, login="hdqt_outsider", password="hdqt_outsider",
            groups="base.group_user",
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.url_open("/hdqt/dashboard", allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn("/web/login", response.headers.get("Location", ""))

    def test_employee_without_the_group_is_forbidden(self):
        self.authenticate("hdqt_outsider", "hdqt_outsider")
        self.assertEqual(self.url_open("/hdqt/dashboard").status_code, 403)

    def test_data_endpoint_is_gated_too(self):
        """The page and its JSON feed must not diverge."""
        self.authenticate("hdqt_outsider", "hdqt_outsider")
        self.assertEqual(self.url_open("/hdqt/dashboard/data").status_code, 403)

    def test_viewer_gets_the_page(self):
        self.authenticate("hdqt_viewer", "hdqt_viewer")
        response = self.url_open("/hdqt/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("hdqt-root", response.text)

    def test_viewer_gets_json(self):
        import json
        self.authenticate("hdqt_viewer", "hdqt_viewer")
        response = self.url_open("/hdqt/dashboard/data")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.headers.get("Content-Type", ""))
        self.assertIn("kpis", json.loads(response.text))

    def test_company_ids_query_string_ignores_junk(self):
        from odoo.addons.hdqt_dashboard.controllers.dashboard import _int_list
        self.assertEqual(_int_list("1,2,abc,,3"), [1, 2, 3])
        self.assertEqual(_int_list(None), [])
        self.assertEqual(_int_list("'; DROP TABLE res_users;--"), [])
