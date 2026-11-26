// mikrotik — a MikroTik RouterOS 7 switch/router over its REST API (the gateway holds the basic-auth login).
// RouterOS answers everything as strings; mikrotik.js turns them into ports/health/problems (unit-tested).
import { cached, soft, siteStatus } from '$lab/sdk.js';
import { buildPorts, health, problems, uptimeSecs, num } from './mikrotik.js';
import PortsView from './PortsView.svelte';
import Facet from './Facet.svelte';
import Tile from './Tile.svelte';

let prev = {};  // last counters per port, for rates and error growth (lives as long as the page)

const oid = (d, ctx) => ctx.settings.object_id || d.identity || 'switch';
const probs = (d, ctx) => problems(d, ctx.settings);

export default {
  id: 'mikrotik',

  async load(ctx) {
    const q = (keys) => ({ '.proplist': keys });
    const [identity, res, hl, ifaces, eth, poe] = await Promise.all([
      ctx.api.get('/system/identity'), ctx.api.get('/system/resource'), soft(ctx.api.get('/system/health'), []),
      ctx.api.get('/interface', q('name,type,running,disabled,comment,rx-byte,tx-byte,link-downs,last-link-up-time')),
      ctx.api.get('/interface/ethernet', q('name,rx-fcs-error,rx-error-events,tx-drop')),
      soft(ctx.api.get('/interface/ethernet/poe', q('name,poe-out,poe-priority')), []),
    ]);
    const names = (xs) => xs.map((x) => x.name).join(',');
    const [mon, poemon] = await Promise.all([
      soft(cached(`${ctx.id}:mon`, 30000, () => ctx.api.post('/interface/ethernet/monitor', { numbers: names(eth), once: '' })), []),
      poe.length ? soft(ctx.api.post('/interface/ethernet/poe/monitor', { numbers: names(poe), once: '' }), []) : [],
    ]);
    const { ports, next } = buildPorts({ ifaces, eth, poe, mon, poemon }, prev);
    prev = next;
    const mem = num(res['total-memory']);
    return {
      identity: identity.name, health: health(hl), ports, at: Date.now() / 1000,
      sys: { version: String(res.version || '').replace(/ \(.*\)/, ''), board: res['board-name'], uptime: uptimeSecs(res.uptime), cpu: num(res['cpu-load']),
        memPct: mem ? Math.round((100 * (mem - num(res['free-memory']))) / mem) : 0 },
    };
  },

  objects(d, ctx) {
    const up = d.ports.filter((p) => p.running).length;
    return [{ id: oid(d, ctx), type: 'switch', name: d.identity, kind: d.sys.board || 'switch', status: siteStatus(probs(d, ctx)),
      cpu: d.sys.cpu, mem: d.sys.memPct, meta: `${up}/${d.ports.length} ports up${d.health.poeW != null ? ` · poe ${d.health.poeW} W` : ''}` }];
  },

  alerts: (d, ctx) => probs(d, ctx).map((p) => ({ ...p, object: oid(d, ctx) })),

  kpis(d, ctx) {
    const up = d.ports.filter((p) => p.running).length;
    return [{ label: 'switch', value: `${up}/${d.ports.length}`, view: 'mikrotik', status: siteStatus(probs(d, ctx)),
      sub: `ports up${d.health.poeW != null ? ` · poe ${d.health.poeW} W` : ''}${d.health.temp != null ? ` · ${d.health.temp}°C` : ''}` }];
  },

  ticker: (d, ctx) => probs(d, ctx).map((p) => ({ g: '▲', c: 'var(--warn)', s: 'mikrotik', m: p.title, view: 'mikrotik', object: oid(d, ctx) })),

  status: (d, ref) => (ref ? (d.ports.find((p) => p.name === ref)?.running ? 'ok' : 'off') : siteStatus(problems(d))),

  facets: { switch: Facet },
  tiles: [{ id: 'switch', label: 'switch', w: 2, h: 1, component: Tile, min: 'admin' }],
  views: [{ id: 'mikrotik', label: 'Switch', icon: 'switch', component: PortsView, min: 'admin' }],
};

