// Login helpers shared by the first-run page, the 2FA enrolment and People (pure: tested by login.test.mjs).

const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

// a new TOTP secret: 20 random bytes as base32 (the browser makes it; the gateway checks a code against it before storing)
export function newSecret(bytes = crypto.getRandomValues(new Uint8Array(20))) {
  let bits = 0, val = 0, out = '';
  for (const b of bytes) {
    val = (val << 8) | b; bits += 8;
    while (bits >= 5) { out += B32[(val >>> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits > 0) out += B32[(val << (5 - bits)) & 31];
  return out;
}

export const groupSecret = (s) => s.replace(/(.{4})/g, '$1 ').trim();

export function otpauth(secret, username, issuer) {
  const e = encodeURIComponent;
  return `otpauth://totp/${e(issuer)}:${e(username)}?secret=${secret}&issuer=${e(issuer)}&algorithm=SHA1&digits=6&period=30`;
}

// strength hint: a rough entropy estimate (length × alphabet), the gateway's hard rule is ≥ 12 characters
export function strength(pw) {
  pw = pw || '';
  if (!pw) return { score: 0, label: '', ok: false };
  let alpha = 0;
  if (/[a-z]/.test(pw)) alpha += 26;
  if (/[A-Z]/.test(pw)) alpha += 26;
  if (/[0-9]/.test(pw)) alpha += 10;
  if (/[^a-zA-Z0-9]/.test(pw)) alpha += 33;
  const uniq = new Set(pw).size;
  const bits = Math.round(Math.min(pw.length, uniq * 2) * Math.log2(Math.max(alpha, 2)));
  const ok = pw.length >= 12 && uniq >= 5;
  const label = !ok ? (pw.length < 12 ? `${12 - pw.length} more characters` : 'too repetitive')
    : bits < 60 ? 'fair' : bits < 80 ? 'good' : 'strong';
  return { score: Math.min(100, Math.round(bits / 1.0)), bits, label, ok };
}

export const ROLES = ['guest', 'admin', 'owner'];
