from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.erp_telegram_notify.tools import telegram_api


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@tagged("post_install", "-at_install")
class TestTelegramApi(BaseCase):

    def test_returns_result_payload(self):
        fake = _FakeResponse({"ok": True, "result": {"message_id": 7}})
        with patch.object(telegram_api.requests, "post", return_value=fake) as post:
            result = telegram_api.call("TOKEN", "sendMessage", {"chat_id": "-100"})
        self.assertEqual(result, {"message_id": 7})
        self.assertEqual(post.call_args.kwargs["timeout"], 10)
        self.assertIn("/botTOKEN/sendMessage", post.call_args.args[0])

    def test_raises_with_description_and_code(self):
        fake = _FakeResponse(
            {"ok": False, "error_code": 400, "description": "can't parse entities"}, 400
        )
        with patch.object(telegram_api.requests, "post", return_value=fake):
            with self.assertRaises(telegram_api.TelegramError) as ctx:
                telegram_api.call("TOKEN", "sendMessage", {})
        self.assertEqual(ctx.exception.error_code, 400)
        self.assertIsNone(ctx.exception.retry_after)

    def test_extracts_retry_after_on_429(self):
        fake = _FakeResponse({
            "ok": False, "error_code": 429, "description": "Too Many Requests",
            "parameters": {"retry_after": 37},
        }, 429)
        with patch.object(telegram_api.requests, "post", return_value=fake):
            with self.assertRaises(telegram_api.TelegramError) as ctx:
                telegram_api.call("TOKEN", "sendMessage", {})
        self.assertEqual(ctx.exception.retry_after, 37)

    def test_wraps_transport_error(self):
        boom = telegram_api.requests.exceptions.Timeout("timed out")
        with patch.object(telegram_api.requests, "post", side_effect=boom):
            with self.assertRaises(telegram_api.TelegramError) as ctx:
                telegram_api.call("TOKEN", "sendMessage", {})
        self.assertIsNone(ctx.exception.error_code)

    def test_token_never_leaks_through_exception(self):
        boom = telegram_api.requests.exceptions.ConnectionError("failed for SECRETTOKEN")
        with patch.object(telegram_api.requests, "post", side_effect=boom):
            with self.assertRaises(telegram_api.TelegramError) as ctx:
                telegram_api.call("SECRETTOKEN", "sendMessage", {})
        self.assertNotIn("SECRETTOKEN", str(ctx.exception))
