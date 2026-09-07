import json
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.erp_telegram_notify.tools import telegram_api

from .common import TelegramCase


@tagged("post_install", "-at_install")
class TestTelegramServerAction(TelegramCase):

    def setUp(self):
        super().setUp()
        self.alice = new_test_user(self.env, login="tg_alice", name="Alice")
        self.alice.sudo().write({"telegram_chat_id": "111", "telegram_user_id": "111"})
        self.bob = new_test_user(self.env, login="tg_bob", name="Bob")
        self.bob.sudo().write({"telegram_chat_id": "222", "telegram_user_id": "222"})
        self.owner_role = self.env["telegram.role"].create({
            "name": "Salesperson", "model_id": self.model_partner.id,
            "kind": "field_path", "field_path": "user_id",
        })

    def _action(self, **overrides):
        values = {
            "name": "Notify Telegram",
            "model_id": self.model_partner.id,
            "state": "telegram",
        }
        values.update(overrides)
        return self.env["ir.actions.server"].create(values)

    def _run(self, action, records=None):
        records = records or self.partner
        return action.with_context(
            active_model=records._name, active_ids=records.ids
        ).run()

    # --- basics -------------------------------------------------------

    def test_state_is_selectable(self):
        self.assertEqual(self._action().state, "telegram")

    def test_automation_rule_accepts_the_action(self):
        action = self._action(telegram_channel_ids=[(4, self.channel.id)])
        rule = self.env["base.automation"].create({
            "name": "Partner changed",
            "model_id": self.model_partner.id,
            "trigger": "on_create_or_write",
            "action_server_ids": [(4, action.id)],
        })
        self.assertEqual(rule.action_server_ids, action)

    # --- body ---------------------------------------------------------

    def test_link_only_body_is_the_escaped_display_name(self):
        action = self._action(telegram_content_level="link_only")
        self.assertEqual(action._telegram_render_body(self.partner), "<b>Công ty A &amp; B</b>")

    def test_full_body_appends_the_template(self):
        template = self.env["mail.template"].create({
            "name": "TG", "model_id": self.model_partner.id,
            "body_html": "<p>Đã cập nhật <b>{{ object.name }}</b></p>",
        })
        action = self._action(telegram_content_level="full",
                              telegram_template_id=template.id)
        body = action._telegram_render_body(self.partner)
        self.assertIn("<b>Công ty A &amp; B</b>", body)
        self.assertNotIn("<p>", body)

    def test_full_without_template_falls_back_to_header(self):
        action = self._action(telegram_content_level="full")
        self.assertEqual(action._telegram_render_body(self.partner), "<b>Công ty A &amp; B</b>")

    # --- markup -------------------------------------------------------

    def test_markup_carries_the_record_link(self):
        action = self._action(telegram_add_link=True)
        markup = json.loads(action._telegram_reply_markup(self.partner))
        url = markup["inline_keyboard"][0][0]["url"]
        self.assertIn("/mail/view?model=res.partner&res_id=%s" % self.partner.id, url)

    def test_markup_is_none_when_nothing_to_show(self):
        action = self._action(telegram_add_link=False)
        self.assertIsNone(action._telegram_reply_markup(self.partner))

    # --- recipients ---------------------------------------------------

    def test_responsible_gets_a_direct_message(self):
        self.partner.user_id = self.alice
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)])
        self._run(action)
        row = self.Outbox.search([("recipient_id", "=", self.alice.id)])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.chat_id, "111")

    def test_watcher_gets_no_action_buttons(self):
        self.partner.user_id = self.alice
        button = self.env["telegram.button"].create({
            "name": "Toggle", "model_id": self.model_partner.id, "method": "toggle_active",
        })
        watcher_role = self.env["telegram.role"].create({
            "name": "Board", "model_id": self.model_partner.id,
            "kind": "users", "user_ids": [(6, 0, self.bob.ids)],
        })
        action = self._action(
            telegram_role_ids=[(4, self.owner_role.id)],
            telegram_watcher_role_ids=[(4, watcher_role.id)],
            telegram_button_ids=[(4, button.id)],
        )
        self._run(action)
        owner_row = self.Outbox.search([("recipient_id", "=", self.alice.id)])
        watcher_row = self.Outbox.search([("recipient_id", "=", self.bob.id)])
        self.assertIn("callback_data", owner_row.reply_markup)
        self.assertNotIn("callback_data", watcher_row.reply_markup)

    def test_responsible_is_never_demoted_to_watcher(self):
        self.partner.user_id = self.alice
        also = self.env["telegram.role"].create({
            "name": "Also", "model_id": self.model_partner.id,
            "kind": "users", "user_ids": [(6, 0, self.alice.ids)],
        })
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)],
                              telegram_watcher_role_ids=[(4, also.id)])
        owners, watchers = action._telegram_resolve(self.partner)
        self.assertIn(self.alice, owners)
        self.assertNotIn(self.alice, watchers)

    def test_author_is_skipped_by_default(self):
        self.partner.user_id = self.env.user
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)])
        owners, _watchers = action._telegram_resolve(self.partner)
        self.assertNotIn(self.env.user, owners)

    def test_author_can_be_kept(self):
        self.env.user.sudo().telegram_chat_id = "999"
        self.partner.user_id = self.env.user
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)],
                              telegram_exclude_actor=False)
        owners, _watchers = action._telegram_resolve(self.partner)
        self.assertIn(self.env.user, owners)

    def test_group_message_names_unlinked_recipients(self):
        carol = new_test_user(self.env, login="tg_carol", name="Carol")
        self.partner.user_id = carol
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)],
                              telegram_channel_ids=[(4, self.channel.id)])
        self._run(action)
        row = self.Outbox.search([("channel_id", "=", self.channel.id)])
        self.assertIn("Carol", row.body)

    def test_falls_back_when_nobody_is_resolved(self):
        fallback = self.env["telegram.channel"].create({
            "name": "Fallback", "bot_id": self.bot.id,
            "chat_id": "-100999", "state": "confirmed",
        })
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)],
                              telegram_fallback_channel_id=fallback.id)
        self._run(action)
        row = self.Outbox.search([("channel_id", "=", fallback.id)])
        self.assertEqual(len(row), 1)

    def test_no_recipient_and_no_fallback_queues_nothing(self):
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)])
        self._run(action)
        self.assertFalse(self.Outbox.search([("res_model", "=", "res.partner")]))

    def test_one_message_per_record(self):
        other = self.env["res.partner"].create({"name": "Công ty C", "user_id": self.alice.id})
        self.partner.user_id = self.alice
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)])
        self._run(action, self.partner | other)
        rows = self.Outbox.search([("res_model", "=", "res.partner")])
        self.assertEqual(len(rows), 2)

    def test_run_queues_but_sends_nothing_synchronously(self):
        """HTTP must never happen inside the writing transaction."""
        self.partner.user_id = self.alice
        action = self._action(telegram_role_ids=[(4, self.owner_role.id)])
        with patch.object(telegram_api, "call") as call:
            self._run(action)
        call.assert_not_called()
        self.assertTrue(self.Outbox.search([("state", "=", "pending")]))
