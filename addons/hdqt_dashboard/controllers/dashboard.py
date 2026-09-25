import json
import logging

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

VIEWER_GROUP = "hdqt_dashboard.group_hdqt_viewer"


def _int_list(raw):
    """Parse a comma-separated id list, ignoring anything that is not an id."""
    if not raw:
        return []
    return [int(chunk) for chunk in str(raw).split(",") if chunk.strip().isdigit()]


class HdqtDashboardController(http.Controller):

    def _check_access(self):
        """The viewer group is the only gate — see the model's module docstring."""
        if not request.env.user.has_group(VIEWER_GROUP):
            raise Forbidden()

    @http.route("/hdqt/dashboard", type="http", auth="user", methods=["GET"])
    def dashboard(self, **kwargs):
        self._check_access()
        return request.render("hdqt_dashboard.dashboard_page", {
            "user": request.env.user,
        })

    @http.route("/hdqt/dashboard/data", type="http", auth="user", methods=["GET"])
    def dashboard_data(self, date_from=None, date_to=None, company_ids=None, **kwargs):
        """Return the aggregations as JSON.

        Plain JSON rather than JSON-RPC so the page can fetch() it directly.
        """
        self._check_access()
        try:
            payload = request.env["hdqt.dashboard"].get_dashboard_data(
                date_from=date_from,
                date_to=date_to,
                company_ids=_int_list(company_ids),
            )
        except Exception:  # noqa: BLE001 - surfaced to the page as a readable error
            _logger.exception("Board dashboard aggregation failed")
            return request.make_response(
                json.dumps({"error": "aggregation_failed"}),
                headers=[("Content-Type", "application/json")],
                status=500,
            )
        return request.make_response(
            json.dumps(payload, default=str),
            headers=[
                ("Content-Type", "application/json"),
                ("Cache-Control", "no-store"),
            ],
        )
