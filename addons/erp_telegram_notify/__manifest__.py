{
    "name": "ERP Telegram Notify",
    "version": "19.0.1.0.0",
    "category": "Productivity/Discuss",
    "summary": "Push ERP notifications to Telegram, with dynamic recipients and inline actions",
    "description": """
Send Telegram notifications when Odoo data changes.

Configuration lives entirely in Automation Rules: pick any model, any trigger,
any filter, then choose who receives the message. Recipients are resolved from
the record itself through reusable Roles (assignee, manager, followers, group),
so a rule keeps targeting the right person as the data changes.

Also supports inline action buttons (approve / reject) executed as the Odoo
user linked to the Telegram sender, so access rights still apply.
""",
    "license": "LGPL-3",
    "depends": ["base", "base_automation", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/telegram_bot_views.xml",
        "views/telegram_channel_views.xml",
        "views/telegram_role_views.xml",
        "views/telegram_button_views.xml",
        "views/telegram_outbox_views.xml",
        "views/res_users_views.xml",
        "views/ir_actions_server_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
