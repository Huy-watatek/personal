import secrets
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = "res.users"

    telegram_chat_id = fields.Char(
        string="Telegram Chat ID", copy=False, index=True, readonly=True,
        help="Private chat with the bot. Filled in automatically when the user "
             "opens their linking link.",
    )
    telegram_user_id = fields.Char(
        string="Telegram User ID", copy=False, index=True, readonly=True,
        help="Numeric Telegram id, required before this user can act on inline buttons.",
    )
    telegram_bind_token = fields.Char(copy=False, readonly=True)
    telegram_bind_url = fields.Char(compute="_compute_telegram_bind")
    telegram_qr_url = fields.Char(compute="_compute_telegram_bind")
    telegram_linked = fields.Boolean(compute="_compute_telegram_linked", store=True)

    _telegram_user_uniq = models.Constraint(
        "UNIQUE(telegram_user_id)",
        "That Telegram account is already linked to another Odoo user.",
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            "telegram_chat_id", "telegram_user_id", "telegram_linked",
            "telegram_bind_url", "telegram_qr_url",
        ]

    @api.depends("telegram_chat_id")
    def _compute_telegram_linked(self):
        for user in self:
            user.telegram_linked = bool(user.telegram_chat_id)

    def _compute_telegram_bind(self):
        bot = self.env["telegram.bot"].sudo()._get_default_bot()
        for user in self:
            if not bot or not bot.bot_username or not user.telegram_bind_token:
                user.telegram_bind_url = False
                user.telegram_qr_url = False
                continue
            url = "https://t.me/%s?start=%s" % (bot.bot_username, user.telegram_bind_token)
            user.telegram_bind_url = url
            user.telegram_qr_url = (
                "/report/barcode?barcode_type=QR&value=%s&width=256&height=256"
                % quote(url, safe="")
            )

    def action_telegram_generate_link(self):
        """Issue a fresh one-time linking token for this user."""
        bot = self.env["telegram.bot"].sudo()._get_default_bot()
        if not bot or not bot.bot_username:
            raise UserError(_(
                "Set the Bot Username on an enabled Telegram bot first — "
                "the linking link cannot be built without it."
            ))
        for user in self:
            user.sudo().telegram_bind_token = secrets.token_urlsafe(16)

    def action_telegram_unlink(self):
        """Forget the Telegram binding for this user."""
        self.sudo().write({
            "telegram_chat_id": False,
            "telegram_user_id": False,
            "telegram_bind_token": False,
        })
