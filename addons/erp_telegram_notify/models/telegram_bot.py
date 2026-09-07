import logging
import secrets

from odoo import _, api, fields, models

from ..tools import telegram_api

_logger = logging.getLogger(__name__)


class TelegramBot(models.Model):
    _name = "telegram.bot"
    _description = "Telegram Bot"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    token = fields.Char(
        string="Bot Token", required=True, groups="base.group_system",
        help="Token issued by @BotFather. Never exposed to non-system users.",
    )
    webhook_secret = fields.Char(
        string="Webhook Secret", groups="base.group_system",
        default=lambda self: secrets.token_hex(16),
        help="Telegram echoes this in the X-Telegram-Bot-Api-Secret-Token header.",
    )
    bot_username = fields.Char(
        string="Bot Username",
        help="Without the @. Required to build account-linking deep links.",
    )
    webhook_url = fields.Char(compute="_compute_webhook_url")
    active = fields.Boolean(default=True)
    enabled = fields.Boolean(
        string="Sending Enabled", default=True,
        help="Global kill switch. Turn it off to stop all outbound traffic "
             "without uninstalling, e.g. if Telegram becomes unreachable.",
    )

    def _compute_webhook_url(self):
        for bot in self:
            bot.webhook_url = "%s/telegram/webhook/%s" % (bot.get_base_url(), bot.id) if bot.id else ""

    @api.model
    def _get_default_bot(self):
        return self.search([("enabled", "=", True)], limit=1)

    # ------------------------------------------------------------------
    # Webhook registration
    # ------------------------------------------------------------------

    def action_set_webhook(self):
        """Register this Odoo instance as the bot's webhook endpoint."""
        for bot in self:
            telegram_api.call(bot.sudo().token, "setWebhook", {
                "url": bot.webhook_url,
                "secret_token": bot.sudo().webhook_secret,
                "allowed_updates": ["message", "callback_query"],
            })

    def action_delete_webhook(self):
        """Stop Telegram from delivering updates here."""
        for bot in self:
            telegram_api.call(bot.sudo().token, "deleteWebhook", {})

    # ------------------------------------------------------------------
    # Outgoing helpers
    # ------------------------------------------------------------------

    def _reply(self, chat_id, thread_id, text):
        """Send a direct reply into the originating chat and topic."""
        self.ensure_one()
        payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"}
        if thread_id:
            payload["message_thread_id"] = thread_id
        telegram_api.call(self.sudo().token, "sendMessage", payload)

    def _answer_callback(self, callback_id, text, alert=False):
        telegram_api.call(self.sudo().token, "answerCallbackQuery", {
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": alert,
        })

    # ------------------------------------------------------------------
    # Inbound dispatch
    # ------------------------------------------------------------------

    def _process_update(self, payload):
        """Dispatch one Telegram update to the right handler."""
        self.ensure_one()
        if payload.get("message"):
            return self._handle_message(payload["message"])
        if payload.get("callback_query"):
            return self._handle_callback_query(payload["callback_query"])
        return False

    @staticmethod
    def _command_parts(text):
        """Return (command, argument) for a slash command, else (False, False).

        Telegram appends ``@bot_username`` when several bots share a group.
        """
        if not text or not text.startswith("/"):
            return False, False
        chunks = text.split(maxsplit=1)
        command = chunks[0][1:].split("@", 1)[0].lower()
        return command, (chunks[1].strip() if len(chunks) > 1 else "")

    def _handle_message(self, message):
        self.ensure_one()
        command, argument = self._command_parts(message.get("text"))
        if command == "register":
            return self._handle_register(message)
        if command == "start" and argument:
            return self._handle_start(message, argument)
        return False

    def _handle_register(self, message):
        """Create a pending channel for the chat the command came from."""
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id"))
        thread_id = message.get("message_thread_id") or 0
        Channel = self.env["telegram.channel"].sudo()
        existing = Channel.with_context(active_test=False).search([
            ("bot_id", "=", self.id),
            ("chat_id", "=", chat_id),
            ("thread_id", "=", thread_id),
        ], limit=1)
        if existing:
            self._reply(chat_id, thread_id, _(
                "This chat is already registered as “%(name)s” (%(state)s).",
                name=existing.name, state=existing.state,
            ))
            return False
        channel = Channel.create({
            "name": chat.get("title") or chat_id,
            "bot_id": self.id,
            "chat_id": chat_id,
            "thread_id": thread_id,
            "state": "pending",
        })
        self._reply(chat_id, thread_id, _(
            "✅ Registered as “%(name)s”. An Odoo administrator must confirm this "
            "channel before notifications start arriving.", name=channel.name,
        ))
        return True

    def _handle_start(self, message, token):
        """Link the sender's Telegram account to the Odoo user holding ``token``."""
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if chat.get("type") != "private":
            # Binding a group chat as someone's inbox would leak their direct
            # notifications to everyone in that group.
            self._reply(chat.get("id"), message.get("message_thread_id") or 0, _(
                "Open this link in a direct chat with me, not in a group."
            ))
            return False
        user = self.env["res.users"].sudo().search(
            [("telegram_bind_token", "=", token)], limit=1
        )
        if not user:
            self._reply(chat.get("id"), 0, _(
                "This link is invalid or has already been used. "
                "Generate a new one from your Odoo profile."
            ))
            return False
        user.write({
            "telegram_chat_id": str(chat.get("id")),
            "telegram_user_id": str(sender.get("id") or ""),
            "telegram_bind_token": False,
        })
        self._reply(chat.get("id"), 0, _(
            "✅ Linked to your Odoo account (%(login)s). "
            "You will now receive your notifications here.", login=user.login,
        ))
        return True

    def _handle_callback_query(self, callback):
        """Run the method behind an inline button, as the mapped Odoo user."""
        self.ensure_one()
        callback_id = callback.get("id")
        parts = (callback.get("data") or "").split(":")
        if len(parts) != 3 or parts[0] != "tgb":
            return False

        button = self.env["telegram.button"].sudo().browse(
            int(parts[1]) if parts[1].isdigit() else 0
        ).exists()
        if not button:
            self._answer_callback(callback_id, _("This button no longer exists."), alert=True)
            return False

        sender_id = str((callback.get("from") or {}).get("id") or "")
        user = self.env["res.users"].sudo().search(
            [("telegram_user_id", "=", sender_id)], limit=1
        )
        if not user:
            self._answer_callback(callback_id, _(
                "Your Telegram account is not linked to an Odoo user. "
                "Open your Odoo profile and scan the linking QR code first."
            ), alert=True)
            return False

        record = self.env[button.model_name].sudo().browse(
            int(parts[2]) if parts[2].isdigit() else 0
        ).exists()
        if not record:
            self._answer_callback(callback_id, _("This record no longer exists."), alert=True)
            return False

        try:
            # with_user() keeps Odoo's access rights and record rules in force.
            getattr(record.with_user(user), button.method)()
        except Exception as exc:  # noqa: BLE001 - reported to the caller, not swallowed
            self.env.cr.rollback()
            _logger.info("Telegram button %s refused for %s: %s", button.method, user.login, exc)
            self._answer_callback(callback_id, _("Refused: %s", exc), alert=True)
            return False

        self._answer_callback(callback_id, _("✅ %s done.", button.name))
        return True
