"""Minimal LDAP v3 client (RFC 4511) — just what the AD connector needs, stdlib only.

Why not a vendored library: ldap3 + pyasn1 are ~25k lines to audit and carry; the connector needs six operations
(simple bind, search with the paged-results control, modify, add, delete, unbind) on one TLS socket. The BER subset
for those is small and fully covered by test_ldap.py. TLS is the stdlib ssl module, verified against a pinned CA file
(no system trust store) with hostname checking.

    sock = connect_tls("winsrv.ad.example.com", 636, cafile="ad-root-ca.pem")
    c = Connection(sock); c.bind("svc-lab@ad.example.com", pw)
    for dn, attrs in c.search("DC=ad,DC=owner,DC=no", SUBTREE, "(objectClass=user)", ["sAMAccountName"]): ...
Attribute names in results are lower-cased; values are bytes (use first()/text()).
"""
import socket
import ssl

BASE, ONELEVEL, SUBTREE = 0, 1, 2
PAGED_OID = "1.2.840.113556.1.4.319"

RESULT = {0: "success", 1: "operationsError", 2: "protocolError", 3: "timeLimitExceeded", 4: "sizeLimitExceeded",
          7: "authMethodNotSupported", 8: "strongerAuthRequired", 10: "referral", 11: "adminLimitExceeded",
          12: "unavailableCriticalExtension", 13: "confidentialityRequired", 16: "noSuchAttribute",
          17: "undefinedAttributeType", 19: "constraintViolation", 20: "attributeOrValueExists",
          21: "invalidAttributeSyntax", 32: "noSuchObject", 34: "invalidDNSyntax", 48: "inappropriateAuthentication",
          49: "invalidCredentials", 50: "insufficientAccessRights", 51: "busy", 52: "unavailable", 53: "unwillingToPerform",
          64: "namingViolation", 65: "objectClassViolation", 66: "notAllowedOnNonLeaf", 67: "notAllowedOnRDN",
          68: "entryAlreadyExists", 80: "other"}


class LdapError(Exception):
    def __init__(self, code, message=""):
        self.code, self.message = code, message
        super().__init__(f"{RESULT.get(code, code)}: {message}".strip(" :"))


class ConnectionLost(OSError):
    pass


# --- BER (definite lengths, single-byte tags: all LDAP needs) ------------------------------------------------------
def _length(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def tlv(tag, content=b""):
    return bytes([tag]) + _length(len(content)) + content


def seq(*items, tag=0x30):
    return tlv(tag, b"".join(items))


def octets(v, tag=0x04):
    return tlv(tag, v.encode("utf-8") if isinstance(v, str) else bytes(v))


def integer(n, tag=0x02):
    size = 1
    while True:
        try:
            return tlv(tag, int(n).to_bytes(size, "big", signed=True))
        except OverflowError:
            size += 1


def enum(n):
    return integer(n, 0x0A)


def boolean(v, tag=0x01):
    return tlv(tag, b"\xff" if v else b"\x00")


def read_tlv(buf, pos=0):
    """→ (tag, content, next_pos). Raises ValueError on truncated/indefinite input."""
    if pos + 2 > len(buf):
        raise ValueError("truncated BER")
    tag, n = buf[pos], buf[pos + 1]
    pos += 2
    if n & 0x80:
        k = n & 0x7F
        if k == 0 or k > 4 or pos + k > len(buf):
            raise ValueError("bad BER length")
        n = int.from_bytes(buf[pos:pos + k], "big")
        pos += k
    if pos + n > len(buf):
        raise ValueError("truncated BER")
    return tag, buf[pos:pos + n], pos + n


def children(content):
    out, pos = [], 0
    while pos < len(content):
        tag, c, pos = read_tlv(content, pos)
        out.append((tag, c))
    return out


def to_int(content):
    return int.from_bytes(content, "big", signed=True) if content else 0


# --- filters (RFC 4515 string → BER) --------------------------------------------------------------------------------
def escape_filter(value):
    """Escape a value for use inside a filter string (always do this for user input)."""
    out = []
    for ch in str(value):
        out.append({"\\": r"\5c", "*": r"\2a", "(": r"\28", ")": r"\29", "\0": r"\00"}.get(ch, ch))
    return "".join(out)


def escape_dn(value):
    """Escape one RDN value (RFC 4514)."""
    v = str(value)
    out = []
    for i, ch in enumerate(v):
        if ch in ',+"\\<>;=' or (ch == "#" and i == 0) or (ch == " " and (i == 0 or i == len(v) - 1)):
            out.append("\\" + ch)
        elif ch == "\0":
            out.append("\\00")
        else:
            out.append(ch)
    return "".join(out)


def _unescape(v):
    raw, i = bytearray(), 0
    while i < len(v):
        if v[i] == "\\":
            raw += bytes.fromhex(v[i + 1:i + 3])
            i += 3
        else:
            raw += v[i].encode("utf-8")
            i += 1
    return bytes(raw)


def _close(s, i):
    """Index of the ')' closing the simple item that starts at s[i] (values have ')' escaped)."""
    j = s.find(")", i)
    if j < 0:
        raise ValueError("unbalanced filter")
    return j


def _parse(s, i):
    if s[i] != "(":
        raise ValueError(f"filter: expected ( at {i}")
    op = s[i + 1]
    if op in "&|":
        i += 2
        parts = []
        while s[i] == "(":
            enc, i = _parse(s, i)
            parts.append(enc)
        if s[i] != ")" or not parts:
            raise ValueError("filter: bad and/or")
        return tlv(0xA0 if op == "&" else 0xA1, b"".join(parts)), i + 1
    if op == "!":
        enc, i = _parse(s, i + 2)
        if s[i] != ")":
            raise ValueError("filter: bad not")
        return tlv(0xA2, enc), i + 1
    j = _close(s, i + 1)
    item = s[i + 1:j]
    k = item.find("=")
    if k <= 0:
        raise ValueError(f"filter: no operator in {item!r}")
    tag = {"~": 0xA8, ">": 0xA5, "<": 0xA6}.get(item[k - 1])
    attr, value = (item[:k - 1] if tag else item[:k]), item[k + 1:]
    if not attr:
        raise ValueError(f"filter: no attribute in {item!r}")
    if tag is not None:
        return seq(octets(attr), octets(_unescape(value)), tag=tag), j + 1
    if attr.endswith(":"):  # extensible: attr:rule:=value (e.g. the AD bitwise-and rule)
        bits = attr[:-1].split(":")
        name, rule = bits[0], (bits[1] if len(bits) > 1 else "")
        body = (octets(rule, 0x81) if rule else b"") + (octets(name, 0x82) if name else b"") + octets(_unescape(value), 0x83)
        return tlv(0xA9, body), j + 1
    if value == "*":
        return octets(attr, 0x87), j + 1
    if "*" in value:
        pieces = value.split("*")
        subs = []
        if pieces[0]:
            subs.append(octets(_unescape(pieces[0]), 0x80))
        for mid in pieces[1:-1]:
            if mid:
                subs.append(octets(_unescape(mid), 0x81))
        if pieces[-1]:
            subs.append(octets(_unescape(pieces[-1]), 0x82))
        return seq(octets(attr), seq(*subs), tag=0xA4), j + 1
    return seq(octets(attr), octets(_unescape(value)), tag=0xA3), j + 1


def parse_filter(s):
    s = s.strip()
    enc, i = _parse(s, 0)
    if i != len(s):
        raise ValueError("filter: trailing input")
    return enc


# --- helpers for results ---------------------------------------------------------------------------------------------
def first(attrs, name, default=None):
    v = attrs.get(name.lower())
    return v[0] if v else default


def text(attrs, name, default=""):
    v = first(attrs, name)
    return v.decode("utf-8", "replace") if v is not None else default


def texts(attrs, name):
    return [v.decode("utf-8", "replace") for v in attrs.get(name.lower(), [])]


def number(attrs, name, default=None):
    v = first(attrs, name)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


# --- transport ------------------------------------------------------------------------------------------------------
def tls_context(cafile=None, cadata=None):
    """Trust ONLY the given CA (cafile or PEM text cadata: create_default_context then loads no system CAs), or the
    system's trusted CAs when neither is given. The DC's certificate and name are always verified."""
    ctx = ssl.create_default_context(cafile=cafile, cadata=cadata or None)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def connect_tls(host, port=636, cafile=None, timeout=10, addr=None, cadata=None):
    """TLS socket to host:port (or to addr while verifying the certificate for host)."""
    raw = socket.create_connection((addr or host, port), timeout=timeout)
    try:
        return tls_context(cafile, cadata).wrap_socket(raw, server_hostname=host)
    except Exception:
        raw.close()
        raise


class Connection:
    """One LDAP session on a connected socket. Not thread-safe: the caller serializes (the connector holds a lock)."""

    def __init__(self, sock, timeout=15):
        self.sock = sock
        self.sock.settimeout(timeout)
        self.mid = 0
        self.buf = b""

    # wire
    def _send(self, op, controls=b""):
        self.mid += 1
        msg = seq(integer(self.mid), op, tlv(0xA0, controls) if controls else b"")
        try:
            self.sock.sendall(msg)
        except OSError as e:
            raise ConnectionLost(str(e)) from None
        return self.mid

    def _need(self, n):
        while len(self.buf) < n:
            try:
                chunk = self.sock.recv(65536)
            except OSError as e:
                raise ConnectionLost(str(e)) from None
            if not chunk:
                raise ConnectionLost("server closed the connection")
            self.buf += chunk

    def _recv(self):
        """→ (messageID, op tag, op content, controls content|None)."""
        self._need(2)
        n = self.buf[1]
        head = 2 + ((n & 0x7F) if n & 0x80 else 0)
        self._need(head)
        size = int.from_bytes(self.buf[2:head], "big") if n & 0x80 else n
        self._need(head + size)
        tag, content, end = read_tlv(self.buf)
        self.buf = self.buf[end:]
        if tag != 0x30:
            raise ConnectionLost("not an LDAPMessage")
        parts = children(content)
        mid = to_int(parts[0][1])
        op_tag, op = parts[1]
        controls = next((c for t, c in parts[2:] if t == 0xA0), None)
        if mid == 0:  # unsolicited notification (e.g. notice of disconnection)
            raise ConnectionLost("server sent notice of disconnection")
        return mid, op_tag, op, controls

    def _expect(self, mid, tag):
        while True:
            got, op_tag, op, controls = self._recv()
            if got != mid:
                continue  # a late answer to an abandoned request
            if op_tag != tag:
                raise LdapError(2, f"unexpected response 0x{op_tag:02x}")
            return op, controls

    @staticmethod
    def _check(op):
        parts = children(op)
        code = to_int(parts[0][1])
        diag = parts[2][1].decode("utf-8", "replace").strip("\0 \r\n") if len(parts) > 2 else ""
        if code != 0:
            raise LdapError(code, diag)
        return parts

    # operations
    def bind(self, dn, password):
        if not password:
            raise LdapError(49, "empty password (would be an anonymous bind)")
        mid = self._send(seq(integer(3), octets(dn), octets(password, 0x80), tag=0x60))
        op, _ = self._expect(mid, 0x61)
        self._check(op)

    def search(self, base, scope, filt="(objectClass=*)", attrs=(), page=500, size_limit=0):
        """→ [(dn, {attr_lower: [bytes, ...]})]. Pages through results with the paged-results control."""
        enc_filter = parse_filter(filt)
        out, cookie = [], b""
        while True:
            req = seq(octets(base), enum(scope), enum(0), integer(size_limit), integer(0), boolean(False), enc_filter,
                      seq(*[octets(a) for a in attrs]), tag=0x63)
            ctrl = seq(octets(PAGED_OID), boolean(False), octets(seq(integer(page), octets(cookie)))) if page else b""
            mid = self._send(req, ctrl)
            cookie = b""
            while True:
                got, tag, op, controls = self._recv()
                if got != mid:
                    continue
                if tag == 0x64:  # SearchResultEntry
                    p = children(op)
                    dn = p[0][1].decode("utf-8", "replace")
                    attrs_out = {}
                    for _, pa in children(p[1][1]):
                        kids = children(pa)
                        attrs_out[kids[0][1].decode().lower()] = [v for _, v in children(kids[1][1])]
                    out.append((dn, attrs_out))
                elif tag == 0x73:  # SearchResultReference (AD referrals to other partitions): ignored
                    continue
                elif tag == 0x65:  # SearchResultDone
                    self._check(op)
                    for _, c in children(controls or b""):
                        cp = children(c)
                        if cp and cp[0][1] == PAGED_OID.encode():
                            val = next((v for t, v in cp[1:] if t == 0x04), b"")
                            if val:
                                _, inner, _ = read_tlv(val)
                                cookie = children(inner)[1][1]
                    break
                else:
                    raise LdapError(2, f"unexpected search response 0x{tag:02x}")
            if not cookie:
                return out

    def modify(self, dn, changes):
        """changes: [(op, attr, [values])] with op in add|delete|replace; values str/bytes/int."""
        ops = {"add": 0, "delete": 1, "replace": 2}
        items = [seq(enum(ops[o]), seq(octets(a), seq(*[octets(_val(v)) for v in vs], tag=0x31))) for o, a, vs in changes]
        mid = self._send(seq(octets(dn), seq(*items), tag=0x66))
        op, _ = self._expect(mid, 0x67)
        self._check(op)

    def add(self, dn, attrs):
        """attrs: {name: value | [values]}."""
        items = []
        for a, vs in attrs.items():
            vs = vs if isinstance(vs, (list, tuple)) else [vs]
            items.append(seq(octets(a), seq(*[octets(_val(v)) for v in vs], tag=0x31)))
        mid = self._send(seq(octets(dn), seq(*items), tag=0x68))
        op, _ = self._expect(mid, 0x69)
        self._check(op)

    def delete(self, dn):
        mid = self._send(octets(dn, 0x4A))
        op, _ = self._expect(mid, 0x6B)
        self._check(op)

    def unbind(self):
        try:
            self._send(tlv(0x42))
        except OSError:
            pass
        self.close()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _val(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    return v


def ad_password(pw):
    """unicodePwd value: the password in double quotes, UTF-16-LE (only accepted over TLS)."""
    return f'"{pw}"'.encode("utf-16-le")
