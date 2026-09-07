from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import TelegramCase


@tagged("post_install", "-at_install")
class TestTelegramRole(TelegramCase):

    def setUp(self):
        super().setUp()
        self.Role = self.env["telegram.role"]
        self.model_users = self.env["ir.model"]._get("res.users")
        self.alice = new_test_user(self.env, login="tg_alice", name="Alice")
        self.bob = new_test_user(self.env, login="tg_bob", name="Bob")

    def test_field_path_to_users(self):
        self.partner.user_id = self.alice
        role = self.Role.create({
            "name": "Salesperson", "model_id": self.model_partner.id,
            "kind": "field_path", "field_path": "user_id",
        })
        self.assertEqual(role._resolve(self.partner), self.alice)

    def test_field_path_landing_on_partner_maps_back_to_user(self):
        role = self.Role.create({
            "name": "Self", "model_id": self.model_users.id,
            "kind": "field_path", "field_path": "partner_id",
        })
        self.assertIn(self.alice, role._resolve(self.alice))

    def test_multi_level_field_path(self):
        self.partner.user_id = self.alice
        child = self.env["res.partner"].create({
            "name": "Chi nhánh", "parent_id": self.partner.id,
        })
        role = self.Role.create({
            "name": "Parent salesperson", "model_id": self.model_partner.id,
            "kind": "field_path", "field_path": "parent_id.user_id",
        })
        self.assertEqual(role._resolve(child), self.alice)

    def test_invalid_field_path_returns_empty_instead_of_raising(self):
        role = self.Role.create({
            "name": "Broken", "model_id": self.model_partner.id,
            "kind": "field_path", "field_path": "no_such_field.nope",
        })
        self.assertFalse(role._resolve(self.partner))

    def test_followers_role(self):
        self.partner.message_subscribe(partner_ids=self.alice.partner_id.ids)
        role = self.Role.create({
            "name": "Followers", "model_id": self.model_partner.id, "kind": "followers",
        })
        self.assertIn(self.alice, role._resolve(self.partner))

    def test_group_role_includes_implied_members(self):
        group = self.env.ref("base.group_user")
        role = self.Role.create({
            "name": "Employees", "model_id": self.model_partner.id,
            "kind": "group", "group_id": group.id,
        })
        resolved = role._resolve(self.partner)
        self.assertIn(self.alice, resolved)
        self.assertIn(self.bob, resolved)

    def test_specific_users_role(self):
        role = self.Role.create({
            "name": "Board", "model_id": self.model_partner.id,
            "kind": "users", "user_ids": [(6, 0, (self.alice | self.bob).ids)],
        })
        self.assertEqual(role._resolve(self.partner), self.alice | self.bob)

    def test_field_path_is_required_for_that_kind(self):
        with self.assertRaises(ValidationError):
            self.Role.create({
                "name": "Bad", "model_id": self.model_partner.id, "kind": "field_path",
            })

    def test_group_is_required_for_that_kind(self):
        with self.assertRaises(ValidationError):
            self.Role.create({
                "name": "Bad", "model_id": self.model_partner.id, "kind": "group",
            })
