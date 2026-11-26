"""What a guest's menu is built from, checked on the real manifests (no live guest session needed): the registry hands a
guest only modules whose access lets guests in, every one of them carries a category the rail can group it under, and
the shell's role filter (ui/src/lib/routes.js allowedViews, tested in tests/nav.test.mjs) does the rest."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gateway"))
from lab.manifest2 import CATEGORIES  # noqa: E402
from lab.registry import Registry  # noqa: E402


class GuestMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = Registry(os.path.join(ROOT, "modules"))
        # guest groups are per installation (the _groups setting, not manifests): a sample like the live one
        cls.reg.apply(overrides={"seerr": {"_groups": ["media-brukere"]}, "proxmox": {"_groups": ["sneaky"]}},
                      config={"proxmox": {"url": "https://pve.example:8006", "api_token": "<set>"},
                              "seerr": {"url": "http://seerr.example:5055", "api_key": "<set>"}})
        cls.extra = staticmethod(lambda m: cls.reg.overrides.get(m, {}).get("_groups") or [])
        cls.all_groups = sorted({g for mid in cls.reg.modules for g in cls.extra(mid)}
                                | {g for m in cls.reg.modules.values() for g in m["access"].get("groups", [])})

    def test_bare_guest_sees_only_guest_modules(self):
        mods = self.reg.visible({"username": "g", "role": "guest", "groups": []})
        for m in mods:
            self.assertIn("guest", self.reg.get(m["id"])["access"]["roles"], m["id"])

    def test_guest_by_group_never_gets_owner_admin_only_modules_without_the_group(self):
        for g in self.all_groups:
            for m in self.reg.visible({"username": "g", "role": "guest", "groups": [g]}):
                acc = self.reg.get(m["id"])["access"]
                self.assertTrue("guest" in acc["roles"] or g in acc.get("groups", []) or g in self.extra(m["id"]), (g, m["id"]))

    def test_installation_groups_let_guests_in_but_never_into_shared_credential_modules(self):
        seen = {m["id"] for m in self.reg.visible({"username": "g", "role": "guest", "groups": ["media-brukere", "sneaky"]})}
        self.assertIn("seerr", seen)  # a guest-safe module an installation group unlocks
        self.assertNotIn("proxmox", seen)  # shared admin credential: an owner-added guest group is ignored (guest_safe)

    def test_every_module_has_a_rail_category(self):
        for u in ({"username": "o", "role": "owner", "groups": []}, {"username": "g", "role": "guest", "groups": self.all_groups}):
            for m in self.reg.visible(u):
                self.assertIn(m["category"], CATEGORIES, m["id"])

    def test_admin_sees_every_usable_module(self):
        owner = {m["id"] for m in self.reg.visible({"username": "o", "role": "owner", "groups": []})}
        admin = {m["id"] for m in self.reg.visible({"username": "a", "role": "admin", "groups": []})}
        self.assertEqual(owner, admin)


if __name__ == "__main__":
    unittest.main()
