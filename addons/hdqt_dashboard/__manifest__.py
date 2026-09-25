{
    "name": "HĐQT Executive Dashboard",
    "version": "19.0.1.0.0",
    "category": "Productivity",
    "summary": "Board-level dashboard over Sales, Inventory, Manufacturing and Invoicing at /hdqt/dashboard",
    "description": """
A single read-only page for the board, served at /hdqt/dashboard.

Every figure is derived from stored columns of the standard Odoo modules, so
there is no parallel bookkeeping to keep in sync: sale.order, account.move,
stock.picking, stock.quant and mrp.production.

Each section detects whether its module is installed and disappears cleanly when
it is not, so the dashboard runs on any subset of Sales / Inventory /
Manufacturing / Invoicing.
""",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/hdqt_security.xml",
        "views/dashboard_templates.xml",
        "views/menus.xml",
    ],
    "assets": {
        "hdqt_dashboard.assets_dashboard": [
            "hdqt_dashboard/static/src/css/dashboard.css",
            "hdqt_dashboard/static/src/js/charts.js",
            "hdqt_dashboard/static/src/js/dashboard.js",
        ],
    },
    "installable": True,
    "application": False,
}
