// node ui/src/lib/login.test.mjs — login helpers + the QR encoder (its output was checked with a real QR decoder,
// zxing-cpp, for versions 1, 7, 10 and 15; this pins that output so a change to qr.js shows up here)
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { newSecret, otpauth, strength, groupSecret } from './login.js';
import { qr, qrPath } from './qr.js';

// RFC 4648 base32 of "12345678901234567890" (the RFC 6238 test key)
assert.equal(newSecret(new TextEncoder().encode('12345678901234567890')), 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
assert.match(newSecret(), /^[A-Z2-7]{32}$/);
assert.equal(groupSecret('ABCDEFGH'), 'ABCD EFGH');
assert.equal(otpauth('ABC', 'a b', 'door'), 'otpauth://totp/door:a%20b?secret=ABC&issuer=door&algorithm=SHA1&digits=6&period=30');
assert.equal(strength('short').ok, false);
assert.equal(strength('aaaaaaaaaaaaaaa').ok, false);
assert.equal(strength('a fine long passphrase').ok, true);
assert.equal(strength('Tr0ub4dor&3-horse-battery').label, 'strong');

const hash = (t) => { const c = qr(t); return `${c.version}/${c.mask}/` + createHash('sha256').update(c.modules.map((r) => r.map((b) => (b ? 1 : 0)).join('')).join('\n')).digest('hex').slice(0, 16); };
const uri = 'otpauth://totp/labradoor:boss?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=labradoor&algorithm=SHA1&digits=6&period=30';
assert.equal(qr('hi').size, 21);
assert.equal(qr(uri).version, 7);
// pinned: these exact matrices decoded with zxing-cpp to the input text (2026-11-15)
assert.equal(hash('hi'), '1/2/81240590f3a630b0');
assert.equal(hash(uri), '7/4/996f5282f851a62f');
assert.equal(hash('x'.repeat(200)), '10/0/1e21180d1f36a922');
assert.throws(() => qr('x'.repeat(3000)));
assert.ok(qrPath(qr('hi')).startsWith('M4 4h1v1h-1z'));
console.log('login.test.mjs ok');
