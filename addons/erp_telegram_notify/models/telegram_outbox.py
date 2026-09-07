import logging
from datetime import timedelta

from odoo import api, fields, models

from ..tools import telegram_api

_logger = logging.getLogger(__name__)

# Backoff schedule in seconds: 1min, 5min, 30min, 2h, 6h.
RETRY_DELAYS = [60, 300, 1800, 7200, 21600]
MAX_RETRY = len(RETRY_DELAYS)

# Messages for the same record queued within this many seconds are merged, so a
# burst of edits produces one message instead of a flood.
COALESCE_WINDOW = 60

# Telegram caps a bot at 20 messages per minute into one chat. Staying under it
# turns a burst into a short delay instead of a 429 and a temporary ban.
RATE_LIMIT_PER_MINUTE = 18
RATE_LIMIT_WINDOW = 60


class TelegramOutbox(models.Model):
    _name = "telegram.outbox"
    _description = "Telegram Outgoing Message Queue"
    _order = "id"

    bot_id = fields.Many2one("telegram.bot", required=True, ondelete="cascade")
    channel_id = fields.Many2one(
        "telegram.channel", ondelete="set null",
        help="Set when the destination is a registered group, empty for a direct message.",
    )
    recipient_id = fields.Many2one(
        "res.users", ondelete="set null",
        help="Set when the destination is a user's direct chat.",
    )
    chat_id = fields.Char(required=True, index=True)
    thread_id = fields.Integer()
    body = fields.Text(required=True)
    reply_markup = fields.Text(help="Serialised Telegram InlineKeyboardMarkup, if any.")
    res_model = fields.Char(index=True)
    res_id = fields.Integer(index=True)
    state = fields.Selection(
        [("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
        default="pending", required=True, index=True,
    )
    retry_count = fields.Integer(default=0)
    next_retry_at = fields.Datetime(index=True)
    sent_at = fields.Datetime(readonly=True, index=True)
    last_error = fields.Text()
    telegram_message_id = fields.Integer(readonly=True)

    # ------------------------------------------------------------------
    # Queueing
    # ------------------------------------------------------------------

    @api.model
    def _enqueue(self, bot, chat_id, body, thread_id=0, reply_markup=None,
                 res_model=None, res_id=None, channel=None, recipient=None,
                 coalesce=True):
        """Queue one message. Safe to call inside a business transaction.

        No HTTP happens here: if the surrounding transaction rolls back, the
        message is rolled back with it instead of having already been sent.
        """
        if not chat_id:
            return self.browse()
        values = {
            "bot_id": bot.id,
            "chat_id": str(chat_id),
            "thread_id": thread_id or 0,
            "body": body,
            "reply_markup": reply_markup,
            "res_model": res_model,
            "res_id": res_id,
            "channel_id": channel.id if channel else False,
            "recipient_id": recipient.id if recipient else False,
        }
        if coalesce and res_model and res_id:
            cutoff = fields.Datetime.now() - timedelta(seconds=COALESCE_WINDOW)
            existing = self.search([
                ("chat_id", "=", str(chat_id)),
                ("thread_id", "=", thread_id or 0),
                ("res_model", "=", res_model),
                ("res_id", "=", res_id),
                ("state", "=", "pending"),
                ("create_date", ">=", cutoff),
            ], limit=1)
            if existing:
                existing.write({"body": body, "reply_markup": reply_markup})
                return existing
        return self.create(values)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _payload(self):
        self.ensure_one()
        payload = {
            "chat_id": self.chat_id,
            "text": self.body,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if self.thread_id:
            payload["message_thread_id"] = self.thread_id
        if self.reply_markup:
            payload["reply_markup"] = self.reply_markup
        return payload

    def _schedule_retry(self, error):
        """Move the row to its next attempt, or give up past MAX_RETRY."""
        self.ensure_one()
        retry_count = self.retry_count + 1
        if retry_count >= MAX_RETRY:
            self.write({
                "state": "failed",
                "retry_count": retry_count,
                "last_error": error.description,
            })
            return
        # A 429 tells us exactly how long to wait; ignoring it earns a longer ban.
        delay = error.retry_after or RETRY_DELAYS[retry_count - 1]
        self.write({
            "retry_count": retry_count,
            "last_error": error.description,
            "next_retry_at": fields.Datetime.now() + timedelta(seconds=delay),
        })

    @api.model
    def _flush(self, limit=50):
        """Send every due pending message, respecting the per-chat rate cap.

        Never raises: a notification failure must not break business flow.
        """
        now = fields.Datetime.now()
        window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
        messages = self.search(
            [
                ("state", "=", "pending"),
                "|", ("next_retry_at", "=", False), ("next_retry_at", "<=", now),
                ("bot_id.enabled", "=", True),
            ],
            limit=limit,
        )
        budget = {}
        for message in messages:
            chat_id = message.chat_id
            if chat_id not in budget:
                already_sent = self.search_count([
                    ("chat_id", "=", chat_id),
                    ("sent_at", ">=", window_start),
                ])
                budget[chat_id] = RATE_LIMIT_PER_MINUTE - already_sent
            if budget[chat_id] <= 0:
                continue
            token = message.bot_id.sudo().token
            if not token:
                continue
            try:
                result = telegram_api.call(token, "sendMessage", message._payload())
            except telegram_api.TelegramError as exc:
                message._schedule_retry(exc)
                continue
            budget[chat_id] -= 1
            message.write({
                "state": "sent",
                "last_error": False,
                "sent_at": fields.Datetime.now(),
                "telegram_message_id": (result or {}).get("message_id", 0),
            })

    @api.model
    def _cron_flush(self):
        self._flush(limit=200)

    @api.model
    def _flush_after_commit(self):
        """Flush right after the current transaction commits (~1s latency).

        The cron stays the safety net: if this hook fails, rows remain pending
        and the next cron pass picks them up.
        """
        def _run():
            with self.pool.cursor() as cr:
                env = self.env(cr=cr)
                try:
                    env["telegram.outbox"]._flush()
                except Exception:  # noqa: BLE001
                    _logger.exception("Telegram outbox post-commit flush failed")

        self.env.cr.postcommit.add(_run)

    def action_retry(self):
        """Put failed rows back in the queue."""
        self.write({"state": "pending", "retry_count": 0, "next_retry_at": False})
