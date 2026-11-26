"""`body_schema`: a route's JSON body, field by field and level by level (manifest v2; docs/modules.md).

body_keys / body_allow only see the top level. Some APIs take nested bodies whose inner fields matter: the *arr
ManualImport command carries `files: [{path, seriesId, episodeIds, quality: {...}}]`, where `path` decides which file
on the server gets imported (and moved). A schema says exactly what may be sent:

    "body_schema": {"type": "object", "by": "name", "cases": {
        "SeriesSearch": {"keys": {"seriesId": "int"}, "required": ["seriesId"]},
        "ManualImport": {"keys": {
            "files": {"type": "list", "max": 200, "items": {"type": "object", "required": ["path"], "keys": {
                "path": {"type": "string", "prefix": ["{import_paths}"]}, "seriesId": "int"}}},
            "importMode": {"type": "string", "enum": ["auto"]}}, "required": ["files"]}}}

A node is a type name ("string", "int", "number", "bool") or an object:

    type      string | int | number | bool | object | list   (required)
    null      true: null is accepted too
    enum      the allowed values (string/int/number)
    min, max  number bounds; for strings and lists the length (strings default to 4096, lists to 100 items)
    prefix    strings: one of these folders ("{setting}" = this installation's value(s); unset = nothing matches). The
              value must not contain "..", ".", empty segments, backslashes or control characters.
    keys      objects: {name: node} — the ONLY fields allowed (names compared case-insensitively, as .NET binds them)
    required  objects: names from keys (or a case's keys) that must be present
    by, cases objects: a discriminator field ("name") whose string value picks one case {keys, required}; the case's
              keys are allowed on top of the common `keys`, and the discriminator must be one of the cases
    items     lists: the node every item must match

Everything not described is refused: unknown fields, other types (true is not 1, 1.5 is not an int), deeper nesting,
duplicate or case-variant keys, NaN/Infinity, more than 1000 items, a schema deeper than 8 levels.
"""
import copy
import json
import math
import re

TYPES = ("string", "int", "number", "bool", "object", "list")
NODE = {"type", "null", "enum", "min", "max", "prefix", "keys", "required", "by", "cases", "items"}
CASE = {"keys", "required"}
PLACEHOLDER = re.compile(r"^\{([a-z][a-z0-9_]{0,40})\}$")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
MAX_DEPTH = 8
STRING_MAX = 4096
LIST_MAX = 100
INT_LIMIT = 2 ** 53
NEVER = "\0unset\0"   # a placeholder without a value: matches no path


class SchemaError(ValueError):
    pass


def compile_schema(node, where="body_schema", depth=0, placeholders=None):
    """The schema with shorthands expanded, or SchemaError. placeholders: a set the "{key}" names found are added to."""
    if depth > MAX_DEPTH:
        raise SchemaError(f"{where}: deeper than {MAX_DEPTH} levels")
    if isinstance(node, str):
        if node not in ("string", "int", "number", "bool"):
            raise SchemaError(f"{where}: {node!r} is not a type (string, int, number, bool, or an object node)")
        node = {"type": node}
    if not isinstance(node, dict):
        raise SchemaError(f"{where}: a node is a type name or an object")
    extra = set(node) - NODE
    if extra:
        raise SchemaError(f"{where}: unknown key(s) {sorted(extra)} (allowed: {sorted(NODE)})")
    t = node.get("type")
    if t not in TYPES:
        raise SchemaError(f"{where}: type must be one of {TYPES}")
    out = {"type": t}
    if "null" in node:
        if not isinstance(node["null"], bool):
            raise SchemaError(f"{where}: null must be true/false")
        out["null"] = node["null"]
    allowed = {"type", "null"} | {"string": {"enum", "min", "max", "prefix"}, "int": {"enum", "min", "max"},
                                  "number": {"enum", "min", "max"}, "bool": set(), "list": {"min", "max", "items"},
                                  "object": {"keys", "required", "by", "cases"}}[t]
    wrong = set(node) - allowed
    if wrong:
        raise SchemaError(f"{where}: {sorted(wrong)} do not apply to type {t}")
    for b in ("min", "max"):
        if b in node:
            v = node[b]
            ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            if t in ("string", "list"):
                ok = ok and isinstance(v, int) and 0 <= v <= (65536 if t == "string" else 1000)
            if not ok:
                raise SchemaError(f"{where}: {b} must be a number (a length 0..{65536 if t == 'string' else 1000} for {t})")
            out[b] = v
    if "min" in out and "max" in out and out["min"] > out["max"]:
        raise SchemaError(f"{where}: min > max")
    if "enum" in node:
        vals = node["enum"]
        pyt = {"string": (str,), "int": (int,), "number": (int, float)}[t]
        if not (isinstance(vals, list) and vals and len(vals) <= 200
                and all(isinstance(v, pyt) and not isinstance(v, bool) for v in vals)):
            raise SchemaError(f"{where}: enum must be a non-empty list of {t} values")
        out["enum"] = list(vals)
    if "prefix" in node:
        pre = node["prefix"]
        if not (isinstance(pre, list) and pre and all(isinstance(p, str) and p for p in pre)):
            raise SchemaError(f"{where}: prefix must be a non-empty list of folders or \"{{setting}}\" placeholders")
        for p in pre:
            m = PLACEHOLDER.match(p)
            if m:
                if placeholders is not None:
                    placeholders.add(m.group(1))
            elif "{" in p or "}" in p or not _clean_folder(p):
                raise SchemaError(f"{where}: prefix {p!r} must be an absolute folder (no '..') or a whole \"{{setting}}\"")
        out["prefix"] = list(pre)
    if t == "list":
        if "items" not in node:
            raise SchemaError(f"{where}: a list needs items")
        out["items"] = compile_schema(node["items"], f"{where}[]", depth + 1, placeholders)
    if t == "object":
        keys = node.get("keys", {})
        if not isinstance(keys, dict):
            raise SchemaError(f"{where}: keys must be an object")
        out["keys"] = _keys(keys, where, depth, placeholders)
        out["required"] = _required(node.get("required", []), out["keys"], where)
        if ("by" in node) != ("cases" in node):
            raise SchemaError(f"{where}: by and cases go together")
        if "by" in node:
            by, cases = node["by"], node["cases"]
            if not (isinstance(by, str) and NAME.match(by)) or by.lower() in out["keys"]:
                raise SchemaError(f"{where}: by must name the discriminator field (not one of keys)")
            if not (isinstance(cases, dict) and cases and len(cases) <= 100 and all(isinstance(k, str) and k for k in cases)):
                raise SchemaError(f"{where}: cases must map discriminator values to {{keys, required}}")
            out["by"], out["cases"] = by.lower(), {}
            for val, case in cases.items():
                cw = f"{where}<{by}={val}>"
                if not isinstance(case, dict) or set(case) - CASE:
                    raise SchemaError(f"{cw}: a case is {{keys, required}}")
                ck = _keys(case.get("keys", {}), cw, depth, placeholders)
                clash = set(ck) & (set(out["keys"]) | {out["by"]})
                if clash:
                    raise SchemaError(f"{cw}: {sorted(clash)} already defined for every case")
                out["cases"][val] = {"keys": ck, "required": _required(case.get("required", []), {**out["keys"], **ck}, cw)}
    return out


def _keys(keys, where, depth, placeholders):
    if not isinstance(keys, dict) or len(keys) > 200:
        raise SchemaError(f"{where}: keys must be an object (≤ 200 fields)")
    out = {}
    for k, sub in keys.items():
        if not (isinstance(k, str) and NAME.match(k)) or k.lower() in out:
            raise SchemaError(f"{where}: bad or repeated field name {k!r}")
        out[k.lower()] = compile_schema(sub, f"{where}.{k}", depth + 1, placeholders)
    return out


def _required(req, keys, where):
    if not (isinstance(req, list) and all(isinstance(k, str) for k in req)):
        raise SchemaError(f"{where}: required must be a list of field names")
    low = [k.lower() for k in req]
    missing = [k for k in low if k not in keys]
    if missing or len(set(low)) != len(low):
        raise SchemaError(f"{where}: required {missing or req} not (once) in keys")
    return low


def top_keys(schema):
    """Every field name the top level may carry (for the query/body overlap check)."""
    out = set(schema.get("keys") or {})
    if schema.get("by"):
        out.add(schema["by"])
        for c in schema["cases"].values():
            out |= set(c["keys"])
    return out


def has_placeholders(schema):
    return any(PLACEHOLDER.match(p) for p in _prefixes(schema))


def _prefixes(n):
    yield from n.get("prefix") or []
    if n.get("items"):
        yield from _prefixes(n["items"])
    for sub in (n.get("keys") or {}).values():
        yield from _prefixes(sub)
    for c in (n.get("cases") or {}).values():
        for sub in c["keys"].values():
            yield from _prefixes(sub)


def render(schema, value_of):
    """A copy with "{key}" prefixes replaced by this installation's value(s): value_of(key) → text, list or None.
    Folders that are not clean absolute paths are dropped; nothing left = nothing matches."""
    s = copy.deepcopy(schema)

    def walk(n):
        if n.get("prefix"):
            res = []
            for p in n["prefix"]:
                m = PLACEHOLDER.match(p)
                vals = value_of(m.group(1)) if m else p
                for v in vals if isinstance(vals, list) else [vals]:
                    if isinstance(v, str) and _clean_folder(v):
                        res.append(v)
            n["prefix"] = res or [NEVER]
        if n.get("items"):
            walk(n["items"])
        for sub in (n.get("keys") or {}).values():
            walk(sub)
        for c in (n.get("cases") or {}).values():
            for sub in c["keys"].values():
                walk(sub)
    walk(s)
    return s


def _clean_folder(p):
    return isinstance(p, str) and p.startswith("/") and _clean_path(p.rstrip("/") + "/x")


def _clean_path(v):
    if not v.startswith("/") or "\\" in v or any(ord(c) < 32 or ord(c) == 127 for c in v):
        return False
    return all(seg not in ("", ".", "..") for seg in v[1:].split("/"))


def parse(body):
    """The body as the backend will read it, or ValueError: UTF-8 JSON, no duplicate or case-variant keys, no NaN."""
    def pairs(items):
        seen = set()
        for k, _ in items:
            if k.lower() in seen:
                raise ValueError("duplicate key")
            seen.add(k.lower())
        return dict(items)

    def no_constant(x):
        raise ValueError(f"{x} is not JSON")
    raw = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body
    return json.loads(raw or "{}", object_pairs_hook=pairs, parse_constant=no_constant)


def check(schema, data, where="body"):
    """None when data matches the schema, else a short reason (field names only, never values)."""
    t = schema["type"]
    if data is None:
        return None if schema.get("null") else f"{where}: null"
    if t == "object":
        if not isinstance(data, dict):
            return f"{where}: not an object"
        low = {k.lower(): v for k, v in data.items()}
        keys, req = dict(schema["keys"]), list(schema["required"])
        if schema.get("by"):
            d = low.get(schema["by"])
            case = schema["cases"].get(d) if isinstance(d, str) else None
            if case is None:
                return f"{where}.{schema['by']}: not one of the allowed values"
            keys.update(case["keys"])
            req += case["required"]
            low.pop(schema["by"])
        extra = set(low) - set(keys)
        if extra:
            return f"{where}: field(s) not allowed: {sorted(extra)[:5]}"
        missing = [k for k in req if k not in low]
        if missing:
            return f"{where}: missing {missing[:5]}"
        for k, v in low.items():
            why = check(keys[k], v, f"{where}.{k}")
            if why:
                return why
        return None
    if t == "list":
        if not isinstance(data, list):
            return f"{where}: not a list"
        if len(data) > schema.get("max", LIST_MAX) or len(data) < schema.get("min", 0):
            return f"{where}: {len(data)} items (allowed {schema.get('min', 0)}..{schema.get('max', LIST_MAX)})"
        for i, item in enumerate(data):
            why = check(schema["items"], item, f"{where}[{i}]")
            if why:
                return why
        return None
    if t == "bool":
        return None if isinstance(data, bool) else f"{where}: not true/false"
    if t == "string":
        if not isinstance(data, str):
            return f"{where}: not text"
        if not (schema.get("min", 0) <= len(data) <= schema.get("max", STRING_MAX)):
            return f"{where}: length out of range"
        if "enum" in schema and data not in schema["enum"]:
            return f"{where}: not one of the allowed values"
        if "prefix" in schema:
            if not _clean_path(data):
                return f"{where}: not a clean absolute path"
            if not any(p != NEVER and data.startswith(p.rstrip("/") + "/") for p in schema["prefix"]):
                return f"{where}: outside the allowed folders"
        return None
    # int / number
    if isinstance(data, bool) or not isinstance(data, (int, float)) or (t == "int" and not isinstance(data, int)):
        return f"{where}: not {'an integer' if t == 'int' else 'a number'}"
    if isinstance(data, float) and not math.isfinite(data):
        return f"{where}: not finite"
    if abs(data) > INT_LIMIT and "max" not in schema and "min" not in schema:
        return f"{where}: out of range"
    if data < schema.get("min", -math.inf) or data > schema.get("max", math.inf):
        return f"{where}: out of range"
    if "enum" in schema and data not in schema["enum"]:
        return f"{where}: not one of the allowed values"
    return None
