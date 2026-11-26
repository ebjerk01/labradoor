"""Roles, password hashing, TOTP and recovery codes — stdlib only.

Roles: an SSO login maps the login service's groups (owner group → owner, admin group → admin, anyone else → guest;
a guest sees only modules whose access lists one of their groups). The group names come from the Login settings
(login.py; LAB_OWNER_GROUP / LAB_ADMIN_GROUP win when set). A local account's role and groups are set by the owner.

Passwords: scrypt (hashlib.scrypt) with a per-user salt; the parameters are stored with the hash, so they can be raised
later and older hashes (scrypt with lower parameters, or the PBKDF2 hashes of the first break-glass accounts) are
upgraded at the next successful login (needs_rehash).

TOTP: RFC 6238 (HMAC-SHA1, 6 digits, 30 s), one step of clock drift either way; a code is accepted once only (the
caller stores the last accepted time step). Recovery codes are random and stored as SHA-256 hashes, each usable once."""
import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time

from . import config

# --- roles ------------------------------------------------------------------------------------------------------------
GROUPS = {"owner": config.OWNER_GROUP, "admin": config.ADMIN_GROUP}  # login.apply() keeps this current
ROLES = ("guest", "admin", "owner")


def role_for(groups):
    groups = set(groups or [])
    if GROUPS.get("owner") and GROUPS["owner"] in groups:
        return "owner"
    if GROUPS.get("admin") and GROUPS["admin"] in groups:
        return "admin"
    return "guest"


# --- passwords --------------------------------------------------------------------------------------------------------
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1   # ~32 MiB and ~50-100 ms per check
SCRYPT_MAXMEM = 128 * 1024 * 1024
# security review 2026-11-15 (M3): each check takes ~32 MiB; /auth/local is reachable from the internet and the CT has
# 768 MB. At most SCRYPT_SLOTS run at once; the rest wait a little, then get "busy" (never an unbounded pile-up).
SCRYPT_SLOTS = threading.BoundedSemaphore(3)


class Busy(RuntimeError):
    pass


def _scrypt(password, salt, n, r, p, dklen):
    if not SCRYPT_SLOTS.acquire(timeout=10):
        raise Busy("too many password checks at once")
    try:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=dklen)
    finally:
        SCRYPT_SLOTS.release()
MIN_PASSWORD = 12
MAX_PASSWORD = 1024


def hash_password(password, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P):
    salt = secrets.token_bytes(16)
    dk = _scrypt(password, salt, n, r, p, 32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_password(password, stored):
    try:
        if len(password) > MAX_PASSWORD:
            return False
        parts = stored.split("$")
        if parts[0] == "scrypt" and len(parts) == 6:
            n, r, p = (int(x) for x in parts[1:4])
            if n > 2 ** 20 or r > 32 or p > 16:  # a hash nobody here wrote: don't let it eat the memory
                return False
            salt, want = base64.b64decode(parts[4]), base64.b64decode(parts[5])
            dk = _scrypt(password, salt, n, r, p, len(want))
            return hmac.compare_digest(dk, want)
        if parts[0] == "pbkdf2_sha256" and len(parts) == 4:  # the first break-glass hashes (upgraded at login)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(parts[2]), int(parts[1]))
            return hmac.compare_digest(dk, base64.b64decode(parts[3]))
    except (ValueError, AttributeError, TypeError):
        pass
    return False


def needs_rehash(stored):
    parts = (stored or "").split("$")
    if parts[0] != "scrypt" or len(parts) != 6:
        return True
    try:
        return (int(parts[1]), int(parts[2]), int(parts[3])) < (SCRYPT_N, SCRYPT_R, SCRYPT_P)
    except ValueError:
        return True


def password_problem(password):
    """None when the password is acceptable, else what is wrong with it (the UI shows a strength hint too)."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        return f"at least {MIN_PASSWORD} characters"
    if len(password) > MAX_PASSWORD:
        return "too long"
    if len(set(password)) < 5:
        return "too repetitive"
    return None


DUMMY_HASH = hash_password(secrets.token_urlsafe(12))  # equal timing for unknown users


# --- TOTP (RFC 6238) --------------------------------------------------------------------------------------------------
TOTP_STEP, TOTP_DIGITS, TOTP_WINDOW = 30, 6, 1


def totp_new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_clean_secret(secret):
    """Normalise a base32 secret (spaces, lowercase, missing padding); ValueError when it is not one."""
    s = "".join(str(secret or "").split()).upper().rstrip("=")
    if not 16 <= len(s) <= 64:
        raise ValueError("secret must be 16-64 base32 characters")
    base64.b32decode(s + "=" * (-len(s) % 8))  # raises binascii.Error (a ValueError) on bad characters
    return s


def _hotp(key, counter):
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_code(secret, at=None):
    s = totp_clean_secret(secret)
    return _hotp(base64.b32decode(s + "=" * (-len(s) % 8)), int((time.time() if at is None else at) // TOTP_STEP))


def totp_verify(secret, code, last_step=0, at=None):
    """The time step the code belongs to (store it as the new last_step), or None. A step at or before last_step is
    refused: the same code (or an older one) can't be used twice."""
    code = "".join(str(code or "").split())
    if not (code.isdigit() and len(code) == TOTP_DIGITS):
        return None
    s = totp_clean_secret(secret)
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    now = int((time.time() if at is None else at) // TOTP_STEP)
    for step in range(now - TOTP_WINDOW, now + TOTP_WINDOW + 1):
        if step > (last_step or 0) and hmac.compare_digest(_hotp(key, step), code):
            return step
    return None


def totp_uri(secret, username, issuer):
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP}")


# --- recovery codes ---------------------------------------------------------------------------------------------------
RECOVERY_COUNT = 10
_B32 = "abcdefghijkmnpqrstuvwxyz23456789"  # no l/o/0/1


def _rc_norm(code):
    return "".join(c for c in str(code or "").lower() if c.isalnum())


def recovery_hash(code):
    return hashlib.sha256(("lab-recovery:" + _rc_norm(code)).encode()).hexdigest()


def recovery_new(n=RECOVERY_COUNT):
    """(plain codes for the user, their hashes for the database)."""
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(_B32) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [recovery_hash(c) for c in codes]


def looks_like_recovery(code):
    return len(_rc_norm(code)) == 10 and not _rc_norm(code).isdigit()
