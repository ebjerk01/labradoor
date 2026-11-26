"""Encryption at rest for module secrets (API tokens, passwords) — stdlib only, like the rest of the gateway.

Construction (encrypt-then-MAC, a PRF in counter mode):
  enc_key, mac_key = HMAC-SHA256(master, "enc"), HMAC-SHA256(master, "mac")
  keystream block i = HMAC-SHA256(enc_key, nonce ‖ module ‖ field ‖ i)      (16-byte random nonce per value)
  ciphertext = plaintext XOR keystream
  tag = HMAC-SHA256(mac_key, "v1" ‖ nonce ‖ module ‖ field ‖ ciphertext)
  stored as "v1:" + base64url(nonce ‖ ciphertext ‖ tag)

The module id and field name are bound into both the keystream and the tag, so a stored value can't be swapped onto
another module or field. What it protects: database copies (release backups, exports, a stolen sqlite file). The master
key lives in /etc/lab/master.key (root:lab 0640) and belongs in the password manager, NOT in the same backup as the
database (see deploy/install.sh)."""
import base64
import hashlib
import hmac
import os
import secrets

PREFIX = "v1:"


class SecretError(ValueError):
    pass


class SecretBox:
    def __init__(self, master):
        if not isinstance(master, (bytes, bytearray)) or len(master) < 32:
            raise SecretError("master key must be at least 32 bytes")
        self._enc = hmac.new(bytes(master), b"enc", hashlib.sha256).digest()
        self._mac = hmac.new(bytes(master), b"mac", hashlib.sha256).digest()

    @classmethod
    def from_file(cls, path):
        """None when the file is missing (secrets can't be stored or read until it exists)."""
        try:
            with open(path, encoding="ascii") as f:
                return cls(bytes.fromhex(f.read().strip()))
        except (OSError, ValueError):
            return None

    @staticmethod
    def new_master():
        return secrets.token_bytes(32).hex()

    def _ctx(self, module, field):
        return module.encode() + b"\0" + field.encode() + b"\0"

    def _stream(self, nonce, ctx, n):
        out, i = bytearray(), 0
        while len(out) < n:
            out += hmac.new(self._enc, nonce + ctx + i.to_bytes(8, "big"), hashlib.sha256).digest()
            i += 1
        return bytes(out[:n])

    def seal(self, module, field, plaintext):
        data = plaintext.encode("utf-8")
        nonce, ctx = os.urandom(16), self._ctx(module, field)
        ct = bytes(a ^ b for a, b in zip(data, self._stream(nonce, ctx, len(data))))
        tag = hmac.new(self._mac, b"v1" + nonce + ctx + ct, hashlib.sha256).digest()
        return PREFIX + base64.urlsafe_b64encode(nonce + ct + tag).decode()

    def open(self, module, field, sealed):
        if not isinstance(sealed, str) or not sealed.startswith(PREFIX):
            raise SecretError("not a sealed value")
        try:
            raw = base64.urlsafe_b64decode(sealed[len(PREFIX):].encode())
        except ValueError:
            raise SecretError("corrupt sealed value") from None
        if len(raw) < 48:
            raise SecretError("corrupt sealed value")
        nonce, ct, tag = raw[:16], raw[16:-32], raw[-32:]
        ctx = self._ctx(module, field)
        if not hmac.compare_digest(tag, hmac.new(self._mac, b"v1" + nonce + ctx + ct, hashlib.sha256).digest()):
            raise SecretError("sealed value fails its check (wrong master key, or moved to another module/field)")
        return bytes(a ^ b for a, b in zip(ct, self._stream(nonce, ctx, len(ct)))).decode("utf-8")
