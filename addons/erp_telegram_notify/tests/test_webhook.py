import json
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import HttpCase

from odoo.addons.erp_telegram_notify.tools import telegram_api


@tagged("post_install", "-at_install")
class TestTelegramWebhook(HttpCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({
            "name": "Bot", "token": "1:AA", "bot_username": "test_bot",
        })
        self.env.flush_all()
        self.url = "/telegram/webhook/%s" % self.bot.id
        self.secret = self.bot.sudo().webhook_secret

    def _post(self, payload, secret=None, raw=None):
        headers = {"Content-Type": "application/json"}
        if secret is not None:
            headers["X-Telegram-Bot-Api-Secret-Token"] = secret
        return self.url_open(
            self.url, data=raw if raw is not None else json.dumps(payload), headers=headers
        )

    def test_rejects_wrong_secret(self):
        with patch.object(type(self.env["telegram.bot"]), "_process_update") as proc:
            response = self._post({"update_id": 1}, "wrong")
        self.assertEqual(response.status_code, 403)
        proc.assert_not_called()

    def test_rejects_missing_secret(self):
        self.assertEqual(self._post({"update_id": 1}).status_code, 403)

    def test_rejects_unknown_bot(self):
        response = self.url_open(
            "/telegram/webhook/999999", data="{}",
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "x"},
        )
        self.assertEqual(response.status_code, 403)

    def test_accepts_a_valid_update(self):
        with patch.object(type(self.env["telegram.bot"]), "_process_update") as proc:
            response = self._post({"update_id": 1, "message": {"text": "hi"}}, self.secret)
        self.assertEqual(response.status_code, 200)
        proc.assert_called_once()

    def test_returns_200_when_processing_raises(self):
        """Telegram retries non-2xx; a bug must not become a retry storm."""
        with patch.object(type(self.env["telegram.bot"]), "_process_update",
                          side_effect=ValueError("bug")):
            response = self._post({"update_id": 1}, self.secret)
        self.assertEqual(response.status_code, 200)

    def test_returns_400_on_malformed_json(self):
        self.assertEqual(self._post(None, self.secret, raw="not json{").status_code, 400)


@tagged("post_install", "-at_install")
class TestWebhookRegistration(HttpCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({
            "name": "Bot", "token": "1:AA", "bot_username": "test_bot",
        })

    def test_set_webhook_sends_url_and_secret(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot.action_set_webhook()
        self.assertEqual(call.call_args.args[1], "setWebhook")
        payload = call.call_args.args[2]
        self.assertTrue(payload["url"].endswith("/telegram/webhook/%s" % self.bot.id))
        self.assertEqual(payload["secret_token"], self.bot.sudo().webhook_secret)

    def test_delete_webhook_calls_api(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot.action_delete_webhook()
        self.assertEqual(call.call_args.args[1], "deleteWebhook")


@tagged("post_install", "-at_install")
class TestInboundCommands(HttpCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({
            "name": "Bot", "token": "1:AA", "bot_username": "test_bot",
        })
        self.Channel = self.env["telegram.channel"]

    def _message(self, text, chat_id=-1001234567890, thread_id=None,
                 title="Phòng Kế toán", from_id=42):
        message = {
            "message_id": 1, "text": text, "from": {"id": from_id},
            "chat": {"id": chat_id, "title": title, "type": "supergroup"},
        }
        if thread_id:
            message["message_thread_id"] = thread_id
        return {"update_id": 1, "message": message}

    def _private(self, text, chat_id, from_id=None):
        update = self._message(text, chat_id=chat_id, from_id=from_id or chat_id)
        update["message"]["chat"] = {"id": chat_id, "type": "private"}
        return update

    # --- /register ----------------------------------------------------

    def test_register_creates_a_pending_channel(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._message("/register"))
        channel = self.Channel.search([("chat_id", "=", "-1001234567890")])
        self.assertEqual(len(channel), 1)
        self.assertEqual(channel.state, "pending")
        self.assertEqual(channel.name, "Phòng Kế toán")

    def test_register_stores_the_topic(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}) as call:
            self.bot._process_update(self._message("/register", thread_id=77))
        self.assertEqual(
            self.Channel.search([("chat_id", "=", "-1001234567890")]).thread_id, 77
        )
        self.assertEqual(call.call_args.args[2]["message_thread_id"], 77)

    def test_register_is_idempotent(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._message("/register"))
            self.bot._process_update(self._message("/register"))
        self.assertEqual(self.Channel.search_count([("chat_id", "=", "-1001234567890")]), 1)

    def test_register_does_not_reactivate_a_confirmed_channel(self):
        existing = self.Channel.create({
            "name": "Kế toán", "bot_id": self.bot.id,
            "chat_id": "-1001234567890", "state": "confirmed",
        })
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._message("/register"))
        self.assertEqual(existing.state, "confirmed")

    def test_command_with_bot_mention_is_accepted(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._message("/register@test_bot"))
        self.assertEqual(self.Channel.search_count([("chat_id", "=", "-1001234567890")]), 1)

    def test_plain_text_is_ignored(self):
        with patch.object(telegram_api, "call") as call:
            self.bot._process_update(self._message("chào cả nhà"))
        call.assert_not_called()
        self.assertFalse(self.Channel.search([("chat_id", "=", "-1001234567890")]))

    # --- /start (account linking) -------------------------------------

    def test_start_links_the_user(self):
        user = self.env["res.users"].search([("login", "=", "admin")], limit=1)
        user.sudo().telegram_bind_token = "tok123"
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(
                self._private("/start tok123", chat_id=555, from_id=555)
            )
        self.assertEqual(user.sudo().telegram_chat_id, "555")
        self.assertEqual(user.sudo().telegram_user_id, "555")
        self.assertFalse(user.sudo().telegram_bind_token, "token must be single-use")

    def test_start_with_an_unknown_token_links_nobody(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._private("/start nope", chat_id=556))
        self.assertFalse(
            self.env["res.users"].sudo().search([("telegram_chat_id", "=", "556")])
        )

    def test_bare_start_without_token_does_nothing(self):
        with patch.object(telegram_api, "call") as call:
            self.bot._process_update(self._private("/start", chat_id=557))
        call.assert_not_called()

    def test_start_in_a_group_refuses_to_bind(self):
        user = self.env["res.users"].search([("login", "=", "admin")], limit=1)
        user.sudo().telegram_bind_token = "tok999"
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._message("/start tok999"))
        self.assertFalse(user.sudo().telegram_chat_id)
        self.assertEqual(user.sudo().telegram_bind_token, "tok999", "token stays usable")
