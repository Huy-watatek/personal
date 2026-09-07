import json
import logging
import secrets

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class TelegramWebhook(http.Controller):

    @http.route(
        "/telegram/webhook/<int:bot_id>",
        type="http", auth="public", methods=["POST"],
        csrf=False, save_session=False,
    )
    def telegram_webhook(self, bot_id, **kwargs):
        """Receive one Telegram update.

        Telegram posts plain JSON (not JSON-RPC), hence ``type='http'``.
        Once authenticated this always answers 2xx: Telegram retries non-2xx
        responses, so an internal bug must not become a retry storm.
        """
        presented = request.httprequest.headers.get(SECRET_HEADER) or ""
        bot = request.env["telegram.bot"].sudo().browse(bot_id).exists()
        expected = bot.webhook_secret or "" if bot else ""
        if not expected or not secrets.compare_digest(presented, expected):
            _logger.warning("Rejected Telegram webhook for bot %s: bad secret", bot_id)
            return request.make_response("", status=403)

        try:
            payload = json.loads(request.httprequest.get_data(as_text=True))
        except ValueError:
            return request.make_response("", status=400)

        try:
            bot._process_update(payload)
        except Exception:  # noqa: BLE001 - see docstring
            request.env.cr.rollback()
            _logger.exception("Failed to process Telegram update for bot %s", bot_id)

        return request.make_response("", status=200)
