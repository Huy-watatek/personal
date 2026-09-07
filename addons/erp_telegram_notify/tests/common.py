from odoo.tests.common import TransactionCase


class TelegramCase(TransactionCase):
    """Shared fixtures: one bot, one confirmed channel, one partner."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env["telegram.bot"].create({
            "name": "Test Bot", "token": "1:AA", "bot_username": "test_bot",
        })
        cls.channel = cls.env["telegram.channel"].create({
            "name": "Ops", "bot_id": cls.bot.id,
            "chat_id": "-100777", "thread_id": 5, "state": "confirmed",
        })
        cls.model_partner = cls.env["ir.model"]._get("res.partner")
        cls.partner = cls.env["res.partner"].create({"name": "Công ty A & B"})
        cls.Outbox = cls.env["telegram.outbox"]
