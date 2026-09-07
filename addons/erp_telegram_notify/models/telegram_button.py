from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TelegramButton(models.Model):
    """Allowlist of methods reachable from a Telegram inline button.

    The callback payload carries only a row id from this table, never a method
    name, so a crafted callback cannot reach anything an admin did not declare.
    """

    _name = "telegram.button"
    _description = "Telegram Inline Button"
    _order = "sequence, id"

    name = fields.Char(required=True, help="Label shown on the button.")
    sequence = fields.Integer(default=10)
    model_id = fields.Many2one("ir.model", required=True, ondelete="cascade")
    model_name = fields.Char(related="model_id.model", store=True)
    method = fields.Char(
        required=True,
        help="Public method invoked on the record, e.g. action_approve. It runs "
             "as the Odoo user linked to the Telegram sender, so access rights "
             "and record rules still apply.",
    )
    active = fields.Boolean(default=True)

    @api.constrains("model_id", "method")
    def _check_method_is_callable(self):
        for button in self:
            method = (button.method or "").strip()
            if not method or method.startswith("_"):
                raise ValidationError(_(
                    "Method %(method)s is not allowed: only public methods may be "
                    "bound to a Telegram button.", method=button.method,
                ))
            model = self.env.get(button.model_id.model)
            if model is None or not callable(getattr(model, method, None)):
                raise ValidationError(_(
                    "Model %(model)s has no callable method %(method)s.",
                    model=button.model_id.model, method=method,
                ))
