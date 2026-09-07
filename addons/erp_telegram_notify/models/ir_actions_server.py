import json
import logging
from html import escape

from odoo import _, fields, models

from ..tools.html2tg import html_to_telegram

_logger = logging.getLogger(__name__)


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"

    state = fields.Selection(
        selection_add=[("telegram", "Send Telegram")],
        ondelete={"telegram": "cascade"},
    )

    # --- Where it goes ------------------------------------------------
    telegram_channel_ids = fields.Many2many(
        "telegram.channel", "telegram_action_channel_rel", "action_id", "channel_id",
        string="Telegram Groups",
        domain="[('state', '=', 'confirmed')]",
        help="Registered groups or topics that always receive this notification.",
    )
    telegram_role_ids = fields.Many2many(
        "telegram.role", "telegram_action_role_rel", "action_id", "role_id",
        string="Responsible",
        domain="[('model_id', '=', model_id)]",
        help="People accountable for the record. They get a direct message "
             "carrying the action buttons.",
    )
    telegram_watcher_role_ids = fields.Many2many(
        "telegram.role", "telegram_action_watcher_rel", "action_id", "role_id",
        string="Also Notify",
        domain="[('model_id', '=', model_id)]",
        help="People kept in the loop. They get the same information without "
             "the action buttons, so nobody approves by accident.",
    )
    telegram_fallback_channel_id = fields.Many2one(
        "telegram.channel", string="Fallback Group",
        domain="[('state', '=', 'confirmed')]",
        help="Used when no recipient could be resolved — for instance a task "
             "nobody is assigned to. Without it such notifications vanish silently.",
    )
    telegram_exclude_actor = fields.Boolean(
        string="Skip the Author", default=True,
        help="Do not notify the user who caused the change.",
    )

    # --- What it says -------------------------------------------------
    telegram_content_level = fields.Selection(
        [("link_only", "Record name and link only"), ("full", "Full content")],
        string="Content", default="link_only", required=True,
        help="A Telegram group sits outside Odoo's access rules: everyone in it "
             "reads whatever is relayed. 'Link only' keeps the data behind login.",
    )
    telegram_template_id = fields.Many2one(
        "mail.template", string="Body Template",
        domain="[('model_id', '=', model_id)]",
        help="Rendered as the message body when Content is Full.",
    )
    telegram_add_link = fields.Boolean(
        string="Add 'Open in Odoo' Button", default=True,
    )
    telegram_button_ids = fields.Many2many(
        "telegram.button", "telegram_action_button_rel", "action_id", "button_id",
        string="Action Buttons",
        domain="[('model_id', '=', model_id)]",
        help="Buttons appended to the message for the responsible people.",
    )

    # ------------------------------------------------------------------
    # Recipients
    # ------------------------------------------------------------------

    def _telegram_resolve(self, record):
        """Return (responsible, watchers) as deduplicated ``res.users``."""
        self.ensure_one()
        Users = self.env["res.users"]
        owners = Users
        for role in self.telegram_role_ids:
            owners |= role._resolve(record)
        watchers = Users
        for role in self.telegram_watcher_role_ids:
            watchers |= role._resolve(record)
        # Somebody accountable is never merely a watcher.
        watchers -= owners
        if self.telegram_exclude_actor:
            owners -= self.env.user
            watchers -= self.env.user
        def reachable(user):
            return user.active and not user.share

        return owners.filtered(reachable), watchers.filtered(reachable)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _telegram_render_body(self, record):
        """Return the Telegram-safe message body for ``record``."""
        self.ensure_one()
        header = "<b>%s</b>" % escape(record.display_name or "")
        if self.telegram_content_level != "full" or not self.telegram_template_id:
            return html_to_telegram(header)
        rendered = self.telegram_template_id._render_field("body_html", [record.id])[record.id]
        return html_to_telegram("%s<br/>%s" % (header, rendered or ""))

    def _telegram_reply_markup(self, record, with_actions=True):
        """Return a serialised inline keyboard, or None when there is nothing to show."""
        self.ensure_one()
        rows = []
        if self.telegram_add_link:
            url = "%s/mail/view?model=%s&res_id=%s" % (
                record.get_base_url(), record._name, record.id,
            )
            rows.append([{"text": _("Open in Odoo"), "url": url}])
        if with_actions:
            # callback_data is capped at 64 bytes by Telegram; ids keep it short
            # and keep the method name off the wire.
            action_row = [
                {"text": button.name, "callback_data": "tgb:%s:%s" % (button.id, record.id)}
                for button in self.telegram_button_ids
            ]
            if action_row:
                rows.append(action_row)
        return json.dumps({"inline_keyboard": rows}) if rows else None

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _telegram_bot(self):
        self.ensure_one()
        channel = self.telegram_channel_ids[:1] or self.telegram_fallback_channel_id
        return channel.bot_id or self.env["telegram.bot"]._get_default_bot()

    def _telegram_dispatch(self, record, outbox):
        """Queue every message this rule owes for ``record``. Returns True if any."""
        self.ensure_one()
        bot = self._telegram_bot()
        if not bot:
            _logger.warning("Server action %s has no Telegram bot to send through", self.id)
            return False

        owners, watchers = self._telegram_resolve(record)
        body = self._telegram_render_body(record)
        common = {"res_model": record._name, "res_id": record.id}
        queued = False

        owner_markup = self._telegram_reply_markup(record, with_actions=True)
        watcher_markup = self._telegram_reply_markup(record, with_actions=False)

        for user in owners:
            if not user.telegram_chat_id:
                continue
            outbox._enqueue(bot, user.telegram_chat_id, body,
                            reply_markup=owner_markup, recipient=user, **common)
            queued = True

        for user in watchers:
            if not user.telegram_chat_id:
                continue
            outbox._enqueue(bot, user.telegram_chat_id, "👀 %s" % body,
                            reply_markup=watcher_markup, recipient=user, **common)
            queued = True

        group_body = body
        unlinked = (owners | watchers).filtered(lambda user: not user.telegram_chat_id)
        if unlinked:
            group_body = "%s\n<i>%s</i>" % (body, escape(_(
                "Not linked to Telegram: %s", ", ".join(unlinked.mapped("name")),
            )))
        for channel in self.telegram_channel_ids:
            outbox._enqueue(channel.bot_id, channel.chat_id, group_body,
                            thread_id=channel.thread_id, reply_markup=owner_markup,
                            channel=channel, **common)
            queued = True

        if not queued and self.telegram_fallback_channel_id:
            fallback = self.telegram_fallback_channel_id
            text = "%s\n<i>%s</i>" % (body, escape(_("No linked recipient was found.")))
            outbox._enqueue(fallback.bot_id, fallback.chat_id, text,
                            thread_id=fallback.thread_id, channel=fallback, **common)
            queued = True

        if not queued:
            _logger.warning(
                "Telegram rule %s resolved no recipient for %s(%s) and has no fallback",
                self.display_name, record._name, record.id,
            )
        return queued

    def _run_action_telegram_multi(self, eval_context=None):
        """Queue Telegram messages for every active record."""
        res_ids = list(self.env.context.get("active_ids") or [])
        if not res_ids and self.env.context.get("active_id"):
            res_ids = [self.env.context["active_id"]]
        if not res_ids:
            return False
        records = self.env[self.model_name].browse(res_ids).exists()
        outbox = self.env["telegram.outbox"].sudo()
        queued = False
        for record in records:
            if self._telegram_dispatch(record, outbox):
                queued = True
        if queued:
            outbox._flush_after_commit()
        return False

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def action_telegram_preview(self):
        """Show who would be notified, and with what, for a real record."""
        self.ensure_one()
        record = self.env[self.model_name].search([], order="id desc", limit=1)
        if not record:
            message = _("There is no %s record to preview with yet.", self.model_name)
            return self._telegram_notification(message)

        owners, watchers = self._telegram_resolve(record)

        def describe(users):
            if not users:
                return _("(nobody)")
            return ", ".join(
                "%s%s" % (user.name, "" if user.telegram_chat_id else _(" [not linked]"))
                for user in users
            )

        lines = [
            _("Preview on: %s", record.display_name),
            "",
            _("Responsible: %s", describe(owners)),
            _("Also notify: %s", describe(watchers)),
            _("Groups: %s", ", ".join(self.telegram_channel_ids.mapped("name")) or _("(none)")),
            "",
            _("Message:"),
            self._telegram_render_body(record),
        ]
        return self._telegram_notification("\n".join(lines))

    def _telegram_notification(self, message):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Telegram preview"),
                "message": message,
                "type": "info",
                "sticky": True,
            },
        }
