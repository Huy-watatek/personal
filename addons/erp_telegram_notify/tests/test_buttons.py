import json
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.erp_telegram_notify.tools import telegram_api

from .common import TelegramCase


@tagged("post_install", "-at_install")
class TestTelegramButton(TelegramCase):

    def setUp(self):
        super().setUp()
        self.button = self.env["telegram.button"].create({
            "name": "Toggle", "model_id": self.model_partner.id, "method": "toggle_active",
        })
        self.approver = new_test_user(
            self.env, login="tg_approver",
            groups="base.group_user,base.group_partner_manager",
        )
        self.approver.sudo().telegram_user_id = "555001"

    def _callback(self, data, from_id="555001"):
        return {"callback_query": {
            "id": "cbq-1", "from": {"id": int(from_id)}, "data": data,
            "message": {"message_id": 9, "chat": {"id": -100777}},
        }}

    # --- allowlist integrity -----------------------------------------

    def test_private_method_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["telegram.button"].create({
                "name": "Bad", "model_id": self.model_partner.id, "method": "_write",
            })

    def test_unknown_method_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["telegram.button"].create({
                "name": "Bad", "model_id": self.model_partner.id, "method": "nope",
            })

    # --- dispatch -----------------------------------------------------

    def test_runs_the_method_as_the_linked_user(self):
        self.assertTrue(self.partner.active)
        with patch.object(telegram_api, "call", return_value=True):
            self.bot._process_update(
                self._callback("tgb:%s:%s" % (self.button.id, self.partner.id))
            )
        self.assertFalse(self.partner.active)

    def test_unlinked_sender_is_refused(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(
                self._callback("tgb:%s:%s" % (self.button.id, self.partner.id), "999999")
            )
        self.assertTrue(self.partner.active)
        self.assertEqual(call.call_args.args[1], "answerCallbackQuery")
        self.assertTrue(call.call_args.args[2]["show_alert"])

    def test_odoo_access_rights_still_apply(self):
        reader = new_test_user(self.env, login="tg_reader", groups="base.group_user")
        reader.sudo().telegram_user_id = "555002"
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(
                self._callback("tgb:%s:%s" % (self.button.id, self.partner.id), "555002")
            )
        self.assertEqual(call.call_args.args[1], "answerCallbackQuery")

    def test_unknown_button_id_is_refused(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(self._callback("tgb:999999:%s" % self.partner.id))
        self.assertTrue(self.partner.active)
        self.assertEqual(call.call_args.args[1], "answerCallbackQuery")

    def test_malformed_callback_data_is_ignored(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(self._callback("garbage"))
        call.assert_not_called()
        self.assertTrue(self.partner.active)

    def test_deleted_record_is_refused(self):
        res_id = self.partner.id
        self.partner.unlink()
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(self._callback("tgb:%s:%s" % (self.button.id, res_id)))
        self.assertEqual(call.call_args.args[1], "answerCallbackQuery")

    def test_callback_data_fits_telegram_limit(self):
        action = self.env["ir.actions.server"].create({
            "name": "Notify", "model_id": self.model_partner.id, "state": "telegram",
            "telegram_button_ids": [(4, self.button.id)],
        })
        markup = action._telegram_reply_markup(self.partner)
        for row in json.loads(markup)["inline_keyboard"]:
            for btn in row:
                if "callback_data" in btn:
                    self.assertLessEqual(len(btn["callback_data"].encode()), 64)
