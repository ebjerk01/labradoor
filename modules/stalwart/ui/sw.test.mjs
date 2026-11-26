// node --test modules/stalwart/ui/sw.test.mjs — alert rules on connector-shaped data, plus the manifest's write rules.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { problems, statusOf, blockedSince, objId, logQuery, secs } from './sw.js';

const NOW = Date.parse('2026-11-16T12:00:00Z') / 1000;
const iso = (s) => new Date(s * 1000).toISOString();
const base = () => ({
  counts: { queue: 0, failing: 0, blocked: 0, accounts: 2, domains: 1 },
  queue: [], blocked: [], allowed: [], certificates: [{ id: 'c', names: ['*.example.org'], notAfter: iso(NOW + 60 * 86400) }],
  reports: { dmarc: 0, tls: 0, arf: 0, dmarcOut: 0, tlsOut: 0 },
});

test('a quiet server has no problems', () => {
  assert.deepEqual(problems(base(), {}, NOW), []);
  assert.equal(statusOf(base(), {}), 'ok');
});

test('queue size, stuck and bounced messages', () => {
  const d = base();
  d.queue = [
    { id: 'a', from: 'x@example.org', created: iso(NOW - 3600), status: 'Scheduled', recipients: [{ to: 'a@b.c' }] },
    { id: 'b', from: 'x@example.org', created: iso(NOW - 8 * 3600), status: 'TemporaryFailure', recipients: [{ to: 'd@e.f' }] },
    { id: 'c', from: 'x@example.org', created: iso(NOW - 600), status: 'PermanentFailure', recipients: [{ to: 'g@h.i' }] },
  ];
  d.counts.queue = 3;
  d.counts.failing = 2;
  const keys = problems(d, { queue_alert: 3, stuck_hours: 6 }, NOW).map((p) => p.key);
  assert.deepEqual(keys, ['stalwart:queue', 'stalwart:stuck', 'stalwart:bounced']);
  assert.deepEqual(problems(d, { queue_alert: 0, stuck_hours: 0 }, NOW).map((p) => p.key), ['stalwart:bounced']);
  const stuck = problems(d, { stuck_hours: 6 }, NOW).find((p) => p.key === 'stalwart:stuck');
  assert.match(stuck.detail, /d@e\.f/);
  assert.equal(stuck.object, 'stalwart');
  assert.equal(problems(d, { object: 'mail01' }, NOW)[0].object, 'mail01');
});

test('many new blocks in 24 h, certificate expiry', () => {
  const d = base();
  d.blocked = Array.from({ length: 5 }, (_, i) => ({ id: `b${i}`, address: `192.0.2.${i}`, created: iso(NOW - i * 3600) }));
  d.blocked.push({ id: 'old', address: '198.51.100.1', created: iso(NOW - 3 * 86400) });
  assert.equal(blockedSince(d, NOW - 86400), 5);
  assert.deepEqual(problems(d, { blocked_day_alert: 5 }, NOW).map((p) => p.key), ['stalwart:blocked']);
  assert.deepEqual(problems(d, { blocked_day_alert: 0 }, NOW), []);
  d.certificates[0].notAfter = iso(NOW + 2 * 86400);
  const c = problems(d, { blocked_day_alert: 0 }, NOW);
  assert.equal(c[0].status, 'bad');
});

test('helpers', () => {
  assert.equal(objId({}), 'stalwart');
  assert.equal(objId({ object: ' mx ' }), 'mx');
  assert.equal(secs('2026-11-16T12:00:00Z'), NOW);
  assert.equal(secs(null), null);
  assert.match(logQuery('', 'auth'), /^source:stalwart AND message:\("Authentication failed"/);
});

test('manifest: every write is owner-only except retry, and nothing removes an allowed IP', () => {
  const m = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url)));
  const writes = m.routes.filter((r) => r.method !== 'GET');
  for (const r of writes) {
    assert.ok(r.label, `${r.method} ${r.path} needs a label`);
    if (r.path !== '/api/queue/*/retry') assert.equal(r.owner_only, true, `${r.method} ${r.path} must be owner-only`);
  }
  assert.ok(!m.routes.some((r) => r.path.includes('allowed')), 'no route touches allowed IPs');
  assert.deepEqual(m.routes.find((r) => r.path === '/api/accounts/*/password').body_keys, ['password']);
  assert.equal(m.backend.url, 'http://127.0.0.1:8121');
});
