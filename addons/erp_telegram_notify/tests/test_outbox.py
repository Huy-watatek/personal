from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged

from odoo.addons.erp_telegram_notify.models.telegram_outbox import (
    MAX_RETRY, RATE_LIMIT_PER_MINUTE,
)
from odoo.addons.erp_telegram_notify.tools import telegram_api

from .common import TelegramCase


@tagged("post_install", "-at_install")
class TestOutbox(TelegramCase):

    def _queue(self, body="hi", **kwargs):
        return self.Outbox._enqueue(self.bot, "-100777", body, thread_id=5, **kwargs)

    def test_enqueue_creates_pending_row(self):
        msg = self._queue()
        self.assertEqual(msg.state, "pending")
        self.assertEqual(msg.retry_count, 0)

    def test_enqueue_without_chat_id_is_a_noop(self):
        self.assertFalse(self.Outbox._enqueue(self.bot, False, "hi"))

    def test_flush_marks_sent_and_stamps_time(self):
        msg = self._queue()
        with patch.object(telegram_api, "call", return_value={"message_id": 99}) as call:
            self.Outbox._flush()
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.telegram_message_id, 99)
        self.assertTrue(msg.sent_at)
        payload = call.call_args.args[2]
        self.assertEqual(payload["chat_id"], "-100777")
        self.assertEqual(payload["message_thread_id"], 5)
        self.assertEqual(payload["parse_mode"], "HTML")

    def test_flush_schedules_retry_on_error(self):
        msg = self._queue()
        err = telegram_api.TelegramError("boom", error_code=500)
        with patch.object(telegram_api, "call", side_effect=err):
            self.Outbox._flush()
        self.assertEqual(msg.state, "pending")
        self.assertEqual(msg.retry_count, 1)
        self.assertIn("boom", msg.last_error)
        self.assertGreater(msg.next_retry_at, fields.Datetime.now())

    def test_flush_honours_retry_after(self):
        msg = self._queue()
        err = telegram_api.TelegramError("slow", error_code=429, retry_after=120)
        with patch.object(telegram_api, "call", side_effect=err):
            self.Outbox._flush()
        delay = msg.next_retry_at - fields.Datetime.now()
        self.assertGreater(delay, timedelta(seconds=110))
        self.assertLess(delay, timedelta(seconds=130))

    def test_flush_gives_up_after_max_retry(self):
        msg = self._queue()
        msg.retry_count = MAX_RETRY - 1
        err = telegram_api.TelegramError("boom", error_code=400)
        with patch.object(telegram_api, "call", side_effect=err):
            self.Outbox._flush()
        self.assertEqual(msg.state, "failed")

    def test_flush_skips_rows_not_yet_due(self):
        msg = self._queue()
        msg.next_retry_at = fields.Datetime.now() + timedelta(hours=1)
        with patch.object(telegram_api, "call") as call:
            self.Outbox._flush()
        call.assert_not_called()

    def test_kill_switch_blocks_sending(self):
        msg = self._queue()
        self.bot.enabled = False
        with patch.object(telegram_api, "call") as call:
            self.Outbox._flush()
        call.assert_not_called()
        self.assertEqual(msg.state, "pending")

    def test_action_retry_requeues_failed_rows(self):
        msg = self._queue()
        msg.write({"state": "failed", "retry_count": 5})
        msg.action_retry()
        self.assertEqual(msg.state, "pending")
        self.assertEqual(msg.retry_count, 0)


@tagged("post_install", "-at_install")
class TestOutboxCoalesce(TelegramCase):

    def test_second_enqueue_updates_the_pending_row(self):
        first = self.Outbox._enqueue(self.bot, "-1", "v1", res_model="res.partner", res_id=1)
        second = self.Outbox._enqueue(self.bot, "-1", "v2", res_model="res.partner", res_id=1)
        self.assertEqual(first, second)
        self.assertEqual(first.body, "v2")

    def test_different_records_are_not_merged(self):
        a = self.Outbox._enqueue(self.bot, "-1", "a", res_model="res.partner", res_id=1)
        b = self.Outbox._enqueue(self.bot, "-1", "b", res_model="res.partner", res_id=2)
        self.assertNotEqual(a, b)

    def test_different_chats_are_not_merged(self):
        a = self.Outbox._enqueue(self.bot, "-1", "a", res_model="res.partner", res_id=1)
        b = self.Outbox._enqueue(self.bot, "-2", "a", res_model="res.partner", res_id=1)
        self.assertNotEqual(a, b)

    def test_sent_rows_are_not_merged(self):
        a = self.Outbox._enqueue(self.bot, "-1", "a", res_model="res.partner", res_id=1)
        a.state = "sent"
        b = self.Outbox._enqueue(self.bot, "-1", "b", res_model="res.partner", res_id=1)
        self.assertNotEqual(a, b)

    def test_rows_without_a_record_are_never_merged(self):
        a = self.Outbox._enqueue(self.bot, "-1", "a")
        b = self.Outbox._enqueue(self.bot, "-1", "b")
        self.assertNotEqual(a, b)

    def test_coalesce_can_be_disabled(self):
        a = self.Outbox._enqueue(self.bot, "-1", "a", res_model="res.partner", res_id=1)
        b = self.Outbox._enqueue(self.bot, "-1", "b", res_model="res.partner",
                                 res_id=1, coalesce=False)
        self.assertNotEqual(a, b)


@tagged("post_install", "-at_install")
class TestOutboxRateLimit(TelegramCase):

    def _fill(self, chat_id, count):
        for index in range(count):
            self.Outbox._enqueue(self.bot, chat_id, "m%s" % index, coalesce=False)

    def test_stops_at_the_per_minute_cap(self):
        self._fill("-100777", RATE_LIMIT_PER_MINUTE + 5)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush(limit=100)
        self.assertEqual(call.call_count, RATE_LIMIT_PER_MINUTE)
        self.assertEqual(
            self.Outbox.search_count([("chat_id", "=", "-100777"), ("state", "=", "pending")]), 5
        )

    def test_cap_is_per_chat_not_global(self):
        self._fill("-100777", RATE_LIMIT_PER_MINUTE)
        self._fill("-100888", 3)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush(limit=100)
        self.assertEqual(call.call_count, RATE_LIMIT_PER_MINUTE + 3)

    def test_earlier_sends_count_towards_the_cap(self):
        self._fill("-100777", 2)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}):
            self.Outbox._flush(limit=100)
        self._fill("-100777", RATE_LIMIT_PER_MINUTE)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush(limit=100)
        self.assertEqual(call.call_count, RATE_LIMIT_PER_MINUTE - 2)

    def test_sends_outside_the_window_do_not_count(self):
        self._fill("-100777", 2)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}):
            self.Outbox._flush(limit=100)
        self.Outbox.search([("state", "=", "sent")]).sent_at = (
            fields.Datetime.now() - timedelta(seconds=120)
        )
        self._fill("-100777", RATE_LIMIT_PER_MINUTE)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush(limit=100)
        self.assertEqual(call.call_count, RATE_LIMIT_PER_MINUTE)
