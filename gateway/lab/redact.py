"""Credential redaction for data that leaves lab's own trust zone (today: what the AI assistant reads).

Two layers, both conservative (a false positive costs a little context, a miss leaks a credential to a third party):
  * JSON: a value under a credential-looking KEY (password, secret, token, api key, private key, cookie, ...) is
    replaced, unless it is a bool/number/null ("has_password": true stays useful);
  * text (every string, also inside JSON): PEM private keys, bearer/basic headers, JWTs, well-known token prefixes,
    and `name=value` / `"name": "value"` pairs whose name looks like a credential.
The same idea as connectors/npm's redact() for nginx config, made general. Used by the gateway's delegation endpoint
(delegate.py) and by connectors/ai for what the browser posts."""
import re

MARK = "[redacted]"
_WORDS = {"password", "passwd", "passphrase", "pwd", "secret", "secrets", "token", "tokens", "credential",
          "credentials", "cookie", "cookies", "authorization", "psk", "otp", "totp", "apikey", "privkey", "privatekey",
          "secretkey", "accesskey", "sessionid", "csrf", "xsrf", "wpakey", "recovery", "mnemonic", "seed",
          # review L8 (2026-11-15): tracker passkeys, short password names, password hashes
          "passkey", "pass", "pw", "pwhash", "passhash", "passwordhash"}
# a word that STARTS like this is a credential too: secretValue's "secretvalue", "tokenid", "apikeys", "passwords"
_PREFIXES = ("secret", "token", "passw", "passkey", "apikey", "privatekey", "accesskey", "authkey")
_PAIRS = {("api", "key"), ("private", "key"), ("access", "key"), ("signing", "key"), ("enrollment", "key"),
          ("encryption", "key"), ("auth", "key"), ("secret", "key"), ("client", "secret"), ("pre", "shared"),
          ("session", "id"), ("auth", "code"), ("pairing", "code"), ("x", "api"), ("wpa", "key"), ("enroll", "key"),
          ("wg", "private"), ("wireguard", "private"), ("pw", "hash"), ("pass", "key")}
_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _words(key):
    return [w.lower() for w in _SPLIT.findall(str(key))]


def secret_key(key):
    """Does this field name look like it holds a credential?"""
    w = _words(key)
    if set(w) & _WORDS or any(x.startswith(_PREFIXES) for x in w):
        return True
    flat = re.sub(r"[^a-z0-9]", "", str(key).lower())   # "API_KEY", "Api-Key", "apikey2", "x_secretvalue"
    if flat.startswith(_PREFIXES) or any(p in flat for p in ("apikey", "secret", "token", "passw", "passkey")):
        return True
    return any((a, b) in _PAIRS for a, b in zip(w, w[1:]))


_NAME = (r"(?:password|passwd|passphrase|passkey|pwd|pw[_-]?hash|pass|secret\w*|token\w*|api[_-]?key|apikey"
         r"|access[_-]?key|private[_-]?key|enroll[_-]?key|wg[_-]?private\w*"
         r"|client[_-]?secret|authorization|session[_-]?id|cookie|psk)(?:[_-]?(?:hash|value|key|id))?")
_TEXT = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)", re.S), MARK),
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 " + MARK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"), MARK),
    (re.compile(r"\b(?:sk-ant-|sk-|ghp_|gho_|ghs_|github_pat_|glpat-|xox[abpr]-|AKIA|ASIA)[A-Za-z0-9_-]{12,}"), MARK),
    (re.compile(r"(?i)(" + _NAME + r"[\"']?\s*[:=]\s*[\"']?)([^\s\"'&,;}{]{3,})"), r"\1" + MARK),
    (re.compile(r"(?i)(://[^/\s:@]+:)([^@\s/]{2,})(@)"), r"\1" + MARK + r"\3"),  # user:password@host in URLs
]


def text(s):
    if not isinstance(s, str) or not s:
        return s
    for rx, rep in _TEXT:
        s = rx.sub(rep, s)
    return s


def data(obj, depth=0):
    """Redacted deep copy of decoded JSON."""
    if depth > 60:
        return MARK
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if secret_key(k) and not (v is None or isinstance(v, (bool, int, float))):
                out[k] = MARK
            else:
                out[k] = data(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [data(v, depth + 1) for v in obj]
    if isinstance(obj, str):
        return text(obj)
    return obj
