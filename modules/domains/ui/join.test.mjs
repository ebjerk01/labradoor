// node --test modules/domains/ui/join.test.mjs — the hostname join and the dead-host rule on a small fixture.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { join } from './join.js';

const now = Date.now() / 1000;
const host = (id, d, ip, port, backend, extra = {}) => ({ id, domains: [d], scheme: 'http', host: ip, port, enabled: true, online: true,
  certId: 1, originLock: false, accessLists: [], authRequest: 'none', advanced: '', extra: [], extraBackend: [],
  backend: backend && { state: backend }, ...extra });
const data = {
  npm: { certs: [{ id: 1, name: '*.example.com', expires: now + 4 * 86400 }], redirections: [], hosts: [
    host(1, 'live.example.com', '192.0.2.5', 8080, 'up'),
    host(2, 'gone.example.com', '192.0.2.6', 8080, 'refused'),
    host(3, 'checked.example.com', '192.0.2.7', 8080, 'timeout'),
    host(4, 'pointed.example.com', '192.0.2.8', 8080, 'refused'),
    host(5, 'locked.example.com', '192.0.2.9', 8080, 'up', { originLock: true }),
  ] },
  cloudflare: { zones: [{ id: 'z', name: 'example.com' }], apps: [{ name: 'live', domain: 'live.example.com', policies: [{ name: 'Homelab admins', decision: 'allow' }] }],
    records: [
      { name: 'example.com', type: 'A', content: '1.2.3.4', zone: 'example.com' },
      { name: '*.example.com', type: 'A', content: '1.2.3.4', zone: 'example.com' },
      { name: 'live.example.com', type: 'CNAME', content: 'example.com', proxied: true, zone: 'example.com' },
      { name: 'locked.example.com', type: 'CNAME', content: 'example.com', proxied: false, zone: 'example.com' },
      { name: 'alias.example.com', type: 'CNAME', content: 'pointed.example.com', zone: 'example.com' },
      { name: 'orphan.example.com', type: 'CNAME', content: 'example.com', zone: 'example.com' },
      { name: 'x.sub.example.com', type: 'CNAME', content: 'example.com', zone: 'example.com' },
      { name: 'sub.example.com', type: 'CNAME', content: 'example.com', zone: 'example.com' },
    ] },
  drift: { overview: { guests: [{ name: 'web' }], hosts: [], checks: [
    { name: 'checked backend', target: 'http://192.0.2.7:8080/healthz', ok: true },
    { name: 'live.example.com (live)', target: 'https://live.example.com/', ok: true },
  ] } },
  unifi: { clients: [{ name: 'web (CT 122)', fixedIp: '192.0.2.5', reserved: true, online: true, mac: 'm' }] },
};
const rows = Object.fromEntries(join(data).map((r) => [r.name, r]));

test('chain fields', () => {
  const r = rows['live.example.com'];
  assert.equal(r.dns.kind, 'record');
  assert.equal(r.dns.proxied, true);
  assert.equal(r.access.length, 1);
  assert.equal(r.machine.machine, 'web');
  assert.equal(r.checks.passing, 1);
  assert.equal(r.status, 'ok');
  assert.equal(r.dead, false);
});

test('dead = backend silent + no passing check + unreferenced', () => {
  assert.equal(rows['gone.example.com'].dead, true);
  assert.equal(rows['gone.example.com'].dns.kind, 'wildcard');
  assert.equal(rows['checked.example.com'].dead, false, 'a passing backend check keeps it');
  assert.equal(rows['pointed.example.com'].dead, false, 'a CNAME pointing at it keeps it');
  assert.deepEqual(rows['pointed.example.com'].refs, ['CNAME alias.example.com']);
});

test('dns-only names and wildcard shadowing', () => {
  assert.equal(rows['orphan.example.com'].dnsOnly, true);
  assert.equal(rows['locked.example.com'].status, 'warn', 'origin lock without proxy');
  assert.equal(join({ ...data, cloudflare: { ...data.cloudflare, records: data.cloudflare.records.filter((r) => r.name !== 'x.sub.example.com') },
    npm: { ...data.npm, hosts: [host(9, 'y.sub.example.com', '192.0.2.9', 80, 'up')] } }).find((r) => r.name === 'y.sub.example.com').dns.kind, 'none',
  '*.example.com does not cover y.sub.example.com once sub.example.com exists');
});
