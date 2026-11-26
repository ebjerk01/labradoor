// node --test modules/mikrotik/ui/mikrotik.test.mjs — helpers on RouterOS-shaped fixtures, plus the manifest rules.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { uptimeSecs, rateMbps, speedText, health, buildPorts, problems, vlanTable, poeBad, poeOn } from './mikrotik.js';

const ifaces = [
  { name: 'ether1', type: 'ether', running: 'true', disabled: 'false', 'rx-byte': '1000', 'tx-byte': '500', 'link-downs': '2', comment: 'AP' },
  { name: 'ether2', type: 'ether', running: 'true', disabled: 'false', 'rx-byte': '0', 'tx-byte': '0', 'link-downs': '868' },
  { name: 'ether3', type: 'ether', running: 'false', disabled: 'true', 'rx-byte': '0', 'tx-byte': '0', 'link-downs': '0' },
  { name: 'br-main', type: 'bridge', running: 'true', disabled: 'false', 'rx-byte': '1', 'tx-byte': '1' },
];
const eth = [{ name: 'ether1', 'rx-fcs-error': '0' }, { name: 'ether2', 'rx-fcs-error': '34000', 'tx-drop': '3' }, { name: 'ether3', 'rx-fcs-error': '0' }];
const poe = [{ name: 'ether1', 'poe-out': 'auto-on', 'poe-priority': '10' }, { name: 'ether2', 'poe-out': 'auto-on', 'poe-priority': '10' }];
const mon = [{ name: 'ether1', rate: '1Gbps', 'full-duplex': 'true' }, { name: 'ether2', rate: '10Mbps', 'full-duplex': 'true' }];
const poemon = [{ name: 'ether1', 'poe-out-status': 'powered-on', 'poe-out-power': '6.2', 'poe-out-current': '120' }, { name: 'ether2', 'poe-out-status': 'short-circuit' }];

test('uptime, rates, speed text', () => {
  assert.equal(uptimeSecs('23w4d2h28m57s'), 23 * 604800 + 4 * 86400 + 2 * 3600 + 28 * 60 + 57);
  assert.equal(uptimeSecs(''), 0);
  assert.deepEqual(['1Gbps', '100Mbps', '10Gbps', 'x', undefined].map(rateMbps), [1000, 100, 10000, 0, 0]);
  assert.deepEqual([1000, 100, 10000, 0].map(speedText), ['1G', '100M', '10G', '–']);
});

test('health reads the named sensors', () => {
  const h = health([{ name: 'cpu-temperature', value: '52' }, { name: 'poe-out-consumption', value: '5.8' }, { name: 'fan-state', value: 'ok' }]);
  assert.deepEqual([h.temp, h.poeW, h.fan, h.boardTemp], [52, 5.8, 'ok', null]);
  assert.equal(health(null).temp, null);
});

test('buildPorts joins the calls, keeps only ethernet and computes rates and error growth', () => {
  const a = buildPorts({ ifaces, eth, poe, mon, poemon }, {}, 100);
  assert.deepEqual(a.ports.map((p) => p.name), ['ether1', 'ether2', 'ether3']);
  const [p1, p2, p3] = a.ports;
  assert.equal(p1.speed, 1000); assert.equal(p1.comment, 'AP'); assert.equal(p1.rxRate, 0);
  assert.equal(p1.poe.watts, 6.2); assert.ok(poeOn(p1)); assert.ok(!poeOn(p2));
  assert.equal(p3.disabled, true); assert.equal(p3.speed, 0); assert.equal(p3.poe, null);
  assert.equal(p2.fcsGrowth, 0);
  const b = buildPorts({ ifaces: [{ ...ifaces[0], 'rx-byte': '3000', 'tx-byte': '500' }, { ...ifaces[1] }], eth: [eth[0], { ...eth[1], 'rx-fcs-error': '34010' }], poe, mon, poemon }, a.next, 110);
  assert.equal(b.ports[0].rxRate, 200); assert.equal(b.ports[0].txRate, 0);
  assert.equal(b.ports[1].fcsGrowth, 10);
  // a counter that went backwards (reboot) is a rate of 0, not negative
  const c = buildPorts({ ifaces: [{ ...ifaces[0], 'rx-byte': '10' }], eth, poe, mon, poemon }, b.next, 120);
  assert.equal(c.ports[0].rxRate, 0);
});

test('problems: slow links, CRC growth, PoE trouble, temperature, ignore list', () => {
  const d = { sys: { cpu: 10 }, health: { temp: 52 }, ports: buildPorts({ ifaces, eth, poe, mon, poemon }, {}, 1).ports };
  assert.deepEqual(problems(d).map((p) => p.key), ['mikrotik:slow:ether2']);
  assert.deepEqual(problems(d, { ignore_ports: ['ether2'] }), []);
  assert.deepEqual(problems(d, { slow_warn: false }), []);
  d.ports[1].fcsGrowth = 4; d.ports[0].poe.status = 'overload';
  assert.deepEqual(problems(d, { slow_warn: false }).map((p) => p.key).sort(), ['mikrotik:fcs:ether2', 'mikrotik:poe:ether1']);
  assert.equal(problems({ ...d, health: { temp: 85 } }, { temp_warn: 70 }, ).find((p) => p.key === 'mikrotik:temp').status, 'bad');
  assert.ok(poeBad('overload') && !poeBad('short-circuit') && !poeBad('powered-on'));
});

test('vlanTable expands ranges, merges entries and adds PVIDs', () => {
  const rows = vlanTable([
    { bridge: 'br', 'vlan-ids': '7', 'current-tagged': 'ether24', 'current-untagged': 'ether12,ether5', tagged: 'ether24', untagged: 'ether5' },
    { bridge: 'br', 'vlan-ids': '2', tagged: 'ether24,ether5' },
    { bridge: 'br', 'vlan-ids': '10-12', tagged: 'ether24' },
    { bridge: 'br', 'vlan-ids': '99', disabled: 'true', tagged: 'ether1' },
  ], [{ bridge: 'br', interface: 'ether10', pvid: '7' }]);
  assert.deepEqual(rows.map((r) => r.vlan), ['2', '7', '10', '11', '12']);
  assert.deepEqual(rows[1].untagged, ['ether5', 'ether12']);
  assert.deepEqual(rows[1].pvid, ['ether10']);
  assert.deepEqual(rows[0].tagged, ['ether5', 'ether24']);
});

test('manifest: writes need min + label, no installation values, only read routes unaudited', () => {
  const m = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'));
  assert.equal(m.manifest, 2);
  for (const r of m.routes) {
    if (r.method !== 'GET') { assert.ok(r.min || r.owner_only, `${r.method} ${r.path} needs min`); assert.ok(r.label, `${r.method} ${r.path} needs a label`); }
    if (r.audit === false) assert.ok(/monitor$/.test(r.path), `${r.path} is unaudited but not a read`);
  }
  assert.ok(!/\b\d+\.\d+\.\d+\.\d+\b/.test(JSON.stringify(m)), 'no IP addresses in the manifest');
  const secrets = m.config.fields.filter((f) => f.type === 'secret').map((f) => f.key);
  assert.deepEqual([m.backend.auth.type, m.backend.auth.username, secrets.includes(m.backend.auth.secret)], ['basic', 'username', true]);
  const cycle = m.routes.find((r) => r.path.endsWith('/power-cycle'));
  assert.deepEqual(cycle.body_keys, ['numbers', 'duration']);
});
