"""body_schema (gateway/lab/bodyschema.py): nested body rules in manifest v2 — strict validation of the schema itself,
placeholders from settings, and the checks against bypass attempts. The *arr ManualImport use is in test_arr_routes.py."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gateway"))

from lab import bodyschema as B  # noqa: E402
from lab.registry import ManifestError, Registry, validate  # noqa: E402

SCHEMA = {"type": "object", "keys": {"id": "int"}, "by": "op", "cases": {
    "move": {"keys": {"items": {"type": "list", "max": 3, "items": {"type": "object", "required": ["path"], "keys": {
        "path": {"type": "string", "prefix": ["{roots}", "/fixed/"]}, "size": {"type": "number", "min": 0},
        "tags": {"type": "list", "null": True, "items": {"type": "string", "enum": ["a", "b"]}}}}}}, "required": ["items"]},
    "ping": {}}}


def manifest(schema=None, **route):
    r = {"method": "POST", "path": "/x", "min": "admin", "label": "x", "body_schema": SCHEMA if schema is None else schema}
    r.update(route)
    return {"manifest": 2, "id": "demo", "name": "Demo", "version": "1.0.0", "kind": "community", "category": "tools",
            "config": {"fields": [{"key": "url", "type": "url", "label": "URL", "required": True}]},
            "backend": {"url": "{url}"}, "routes": [r],
            "settings": [{"key": "roots", "type": "list", "label": "roots"}]}


class Validation(unittest.TestCase):
    def bad(self, schema=None, **route):
        with self.assertRaises(ManifestError):
            validate(manifest(copy.deepcopy(schema) if schema is not None else None, **route), "demo")

    def test_good(self):
        m = validate(manifest(), "demo")
        s = m["routes"][0]["body_schema"]
        self.assertEqual(s["cases"]["move"]["keys"]["items"]["items"]["keys"]["path"]["type"], "string")
        self.assertEqual(B.top_keys(s), {"id", "op", "items"})
        self.assertTrue(B.has_placeholders(s))
        self.assertEqual(B.compile_schema(copy.deepcopy(s)), s)  # a compiled schema compiles again unchanged (reloads)

    def test_bad_schemas(self):
        for schema in (
            {"type": "object", "keys": {"a": "integer"}},                  # unknown type name
            {"type": "object", "keys": {"a": {"type": "int", "pattern": "x"}}},  # unknown node key
            {"type": "object", "keys": {"a": {"type": "bool", "max": 3}}},  # bounds don't apply to bool
            {"type": "list"},                                               # a list needs items
            {"type": "list", "items": "int", "max": 5000},                  # > 1000 items
            {"type": "object", "keys": {"a": {"type": "string", "enum": [1]}}},
            {"type": "object", "keys": {"a": {"type": "string", "enum": []}}},
            {"type": "object", "keys": {"a": {"type": "int", "prefix": ["/x/"]}}},
            {"type": "object", "keys": {"a": {"type": "string", "prefix": ["/x/../y"]}}},
            {"type": "object", "keys": {"a": {"type": "string", "prefix": ["relative/"]}}},
            {"type": "object", "keys": {"a": {"type": "string", "prefix": ["/x/{roots}"]}}},  # placeholder = whole entry
            {"type": "object", "keys": {"a": {"type": "string", "prefix": ["{nope}"]}}},      # not a setting
            {"type": "object", "keys": {"a": "int"}, "required": ["b"]},
            {"type": "object", "keys": {"a": "int", "A": "int"}},           # case-variant names
            {"type": "object", "by": "op"},                                 # by without cases
            {"type": "object", "keys": {"op": "int"}, "by": "op", "cases": {"x": {}}},
            {"type": "object", "by": "op", "cases": {"x": {"keys": {"a": "int"}, "extra": 1}}},
            {"type": "object", "keys": {"a": "int"}, "by": "op", "cases": {"x": {"keys": {"a": "int"}}}},
            {"type": "object", "keys": {"a": {"type": "int", "min": 5, "max": 1}}},
            "object", 5, [],
        ):
            self.bad(schema)
        deep = "int"
        for _ in range(B.MAX_DEPTH + 1):
            deep = {"type": "list", "items": deep}
        self.bad({"type": "object", "keys": {"a": deep}})
        self.bad(method="GET")                                              # no body on a GET
        self.bad(body_keys=["id"])                                          # one way to describe a body
        self.bad(body_allow={"op": ["ping"]})
        self.bad(query_keys=["op"])                                         # a field from the query AND the body


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reg = Registry(os.path.join(ROOT, "modules"))
        m = validate(manifest(), "demo")
        reg.modules = {"demo": m}
        reg.apply(overrides={"demo": {"roots": ["/data/a/", "/data/b", "not/absolute", "/x/../y"]}},
                  config={"demo": {"url": "http://demo:1"}})
        cls.route = reg.get("demo")["routes"][0]
        reg2 = Registry(os.path.join(ROOT, "modules"))
        reg2.modules = {"demo": validate(manifest(), "demo")}
        reg2.apply(overrides={}, config={"demo": {"url": "http://demo:1"}})
        cls.unset = reg2.get("demo")["routes"][0]

    def ok(self, body, route=None):
        raw = body if isinstance(body, (str, bytes)) else json.dumps(body)
        return Registry.body_ok(route or self.route, raw.encode() if isinstance(raw, str) else raw)

    def test_rendered_prefixes(self):
        pre = self.route["body_schema"]["cases"]["move"]["keys"]["items"]["items"]["keys"]["path"]["prefix"]
        self.assertEqual(pre, ["/data/a/", "/data/b", "/fixed/"])            # unclean folders from the setting dropped
        self.assertTrue(Registry.body_restricted(self.route))

    def test_accepts(self):
        self.assertTrue(self.ok({"op": "ping"}))
        self.assertTrue(self.ok({"op": "ping", "id": 3}))
        self.assertTrue(self.ok({"OP": "ping", "ID": 3}))                     # .NET binds names case-insensitively
        self.assertTrue(self.ok({"op": "move", "items": [{"path": "/data/a/x"}, {"path": "/data/b/y/z", "size": 1.5},
                                                          {"path": "/fixed/q", "tags": None}]}))
        self.assertTrue(self.ok({"op": "move", "items": [{"path": "/data/a/x", "tags": ["a", "b"]}]}))

    def test_refuses(self):
        for body in (
            {}, {"op": "Ping"}, {"op": "other"}, {"op": 1}, {"op": None}, {"id": 3},          # discriminator
            {"op": "ping", "items": []},                                                      # another case's field
            {"op": "ping", "extra": 1}, {"op": "ping", "id": "3"}, {"op": "ping", "id": True},
            {"op": "ping", "id": 3.0}, {"op": "ping", "id": 2 ** 60},
            {"op": "move"}, {"op": "move", "items": {}}, {"op": "move", "items": "x"},       # not a list
            {"op": "move", "items": [{"path": "/data/a/x"}] * 4},                             # too many
            {"op": "move", "items": [{}]}, {"op": "move", "items": [None]}, {"op": "move", "items": [["/data/a/x"]]},
            {"op": "move", "items": [{"path": "/data/c/x"}]}, {"op": "move", "items": [{"path": "/data/ab/x"}]},
            {"op": "move", "items": [{"path": "/data/a/../c"}]}, {"op": "move", "items": [{"path": "/data/a/x/"}]},
            {"op": "move", "items": [{"path": "/x/../y/z"}]}, {"op": "move", "items": [{"path": "not/absolute/x"}]},
            {"op": "move", "items": [{"path": "/data/a/x", "size": -1}]},
            {"op": "move", "items": [{"path": "/data/a/x", "tags": ["c"]}]},
            {"op": "move", "items": [{"path": "/data/a/x", "tags": "a"}]},
            {"op": "move", "items": [{"path": "/data/a/x", "tags": [["a"]]}]},                # deeper than the schema
            {"op": "move", "items": [{"path": "/data/a/x", "evil": {"deep": [1]}}]},
            [{"op": "ping"}], "ping", 1, None,
        ):
            self.assertFalse(self.ok(body), body)
        for raw in ('{"op": "ping", "Op": "move"}', '{"op": "ping", "id": NaN}', '{"op": "ping", "id": Infinity}',
                    '{"op": "ping"} {"op": "ping"}', '{"op": "ping"', b'\xff\xfe{}', "[" * 100000 + "]" * 100000, ""):
            self.assertFalse(self.ok(raw), raw[:40])
        self.assertIn("outside the allowed folders",
                      Registry.body_problem(self.route, b'{"op": "move", "items": [{"path": "/etc/passwd"}]}'))

    def test_unset_placeholder_matches_nothing(self):
        self.assertFalse(self.ok({"op": "move", "items": [{"path": "/data/a/x"}]}, self.unset))
        self.assertTrue(self.ok({"op": "move", "items": [{"path": "/fixed/x"}]}, self.unset))  # the fixed folder stays

    def test_schema_only_reveals_field_names(self):
        why = Registry.body_problem(self.route, json.dumps({"op": "ping", "secret-ish": "value-xyz"}).encode())
        self.assertIn("secret-ish", why)
        self.assertNotIn("value-xyz", why)


if __name__ == "__main__":
    unittest.main()
