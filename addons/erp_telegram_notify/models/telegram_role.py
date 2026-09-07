import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class TelegramRole(models.Model):
    """A named way of finding "who cares" about a record.

    Defining the lookup once and reusing it across rules means a change in the
    org chart is edited in one place instead of in every automation rule.
    """

    _name = "telegram.role"
    _description = "Telegram Recipient Role"
    _order = "model_name, name"

    name = fields.Char(required=True, help="e.g. Approver, Owner, Department Manager")
    model_id = fields.Many2one("ir.model", string="Model", required=True, ondelete="cascade")
    model_name = fields.Char(related="model_id.model", store=True)
    kind = fields.Selection(
        [
            ("field_path", "Field on the record"),
            ("followers", "Followers of the record"),
            ("group", "Members of an Odoo group"),
            ("users", "Specific users"),
        ],
        string="Resolved from", default="field_path", required=True,
    )
    field_path = fields.Char(
        string="Field Path",
        help="Dotted path from the record to the people, e.g. user_id, "
             "employee_id.parent_id.user_id, or partner_id.user_id. "
             "May end on users, partners, or any model carrying user_id.",
    )
    group_id = fields.Many2one("res.groups", string="Group")
    user_ids = fields.Many2many("res.users", string="Users")
    active = fields.Boolean(default=True)

    @api.constrains("kind", "field_path", "group_id", "user_ids")
    def _check_source_is_set(self):
        for role in self:
            if role.kind == "field_path" and not role.field_path:
                raise ValidationError(_("Role %s needs a field path.", role.name))
            if role.kind == "group" and not role.group_id:
                raise ValidationError(_("Role %s needs a group.", role.name))
            if role.kind == "users" and not role.user_ids:
                raise ValidationError(_("Role %s needs at least one user.", role.name))

    def _partners_to_users(self, partners):
        if not partners:
            return self.env["res.users"]
        return self.env["res.users"].sudo().search([("partner_id", "in", partners.ids)])

    def _to_users(self, targets):
        """Coerce whatever a path resolved to into a ``res.users`` recordset."""
        Users = self.env["res.users"]
        if not targets or not hasattr(targets, "_name"):
            return Users
        if targets._name == "res.users":
            return targets
        if targets._name == "res.partner":
            return self._partners_to_users(targets)
        # hr.employee and most assignment models carry a user_id.
        if "user_id" in targets._fields:
            return targets.mapped("user_id")
        return Users

    def _resolve(self, record):
        """Return the ``res.users`` this role designates for ``record``."""
        self.ensure_one()
        Users = self.env["res.users"]
        if self.kind == "users":
            return self.user_ids
        if self.kind == "group":
            return Users.sudo().search([("all_group_ids", "in", self.group_id.ids)])
        if self.kind == "followers":
            if "message_follower_ids" not in record._fields:
                return Users
            return self._partners_to_users(record.message_follower_ids.partner_id)
        if self.kind == "field_path" and self.field_path:
            try:
                targets = record.sudo().mapped(self.field_path)
            except (KeyError, AttributeError, ValueError):
                _logger.warning(
                    "Telegram role %s: field path %r is invalid on %s",
                    self.display_name, self.field_path, record._name,
                )
                return Users
            return self._to_users(targets)
        return Users
