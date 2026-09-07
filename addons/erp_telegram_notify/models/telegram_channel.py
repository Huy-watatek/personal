from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools import telegram_api


class TelegramChannel(models.Model):
    _name = "telegram.channel"
    _description = "Telegram Destination Channel"
    _order = "name"

    name = fields.Char(required=True)
    bot_id = fields.Many2one(
        "telegram.bot", required=True, ondelete="cascade",
        default=lambda self: self.env["telegram.bot"]._get_default_bot(),
    )
    chat_id = fields.Char(
        required=True,
        help="Telegram chat id. Group and supergroup ids are negative, "
             "e.g. -1001234567890. Use /register in the group to fill this in.",
    )
    thread_id = fields.Integer(
        string="Topic ID",
        help="Forum topic (message_thread_id). Leave at 0 for the main thread.",
    )
    state = fields.Selection(
        [("pending", "Pending"), ("confirmed", "Confirmed")],
        default="confirmed", required=True,
        help="Channels created by /register start as Pending: an unknown group "
             "cannot subscribe itself to your data without an admin saying so.",
    )
    active = fields.Boolean(default=True)

    _chat_thread_uniq = models.Constraint(
        "UNIQUE(bot_id, chat_id, thread_id)",
        "This bot already has a channel for that chat and topic.",
    )

    def _base_payload(self):
        """Return the chat routing fields shared by every outgoing message."""
        self.ensure_one()
        payload = {"chat_id": self.chat_id}
        if self.thread_id:
            payload["message_thread_id"] = self.thread_id
        return payload

    def action_confirm(self):
        self.write({"state": "confirmed"})

    def action_send_test(self):
        """Send a probe message so an administrator can verify the wiring."""
        self.ensure_one()
        token = self.bot_id.sudo().token
        if not token:
            raise UserError(_("Bot %s has no token configured.", self.bot_id.display_name))
        payload = self._base_payload()
        payload.update({
            "text": _("✅ Test message from Odoo (database %s).", self.env.cr.dbname),
            "parse_mode": "HTML",
        })
        try:
            telegram_api.call(token, "sendMessage", payload)
        except telegram_api.TelegramError as exc:
            raise UserError(_("Telegram refused the test message: %s", exc.description)) from exc
