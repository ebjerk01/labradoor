// unifi — the UniFi Network app through the lab connector `unifi`: clients as objects (`client:<mac>`), DHCP
// reservations, devices, networks, port forwards. Machines get a network facet when a UniFi client carries their name.
import NetworkView from './NetworkView.svelte';
import ClientFacet from './ClientFacet.svelte';
import MachineFacet from './MachineFacet.svelte';
import UdrFacet from './UdrFacet.svelte';
import ClientsTile from './ClientsTile.svelte';
import { ago } from '$lab/sdk.js';
import { mismatch, label } from './uf.js';

export default {
  id: 'unifi',

  async load(ctx) {
    return ctx.api.get('/api/overview');
  },

  objects(d, ctx) {
    return d.clients.map((c) => ({
      id: `client:${c.mac}`, type: 'client', name: label(c), kind: c.network || (c.wired ? 'wired' : 'wifi'),
      status: c.blocked ? 'bad' : mismatch(c) ? 'warn' : c.online ? 'ok' : 'off', mac: c.mac,
      meta: `${c.ip || '–'}${c.reserved ? ' · reserved' : ''}${c.blocked ? ' · BLOCKED' : ''}${c.online ? '' : ` · seen ${ago(c.lastSeen, ctx?.now)} ago`}`,
    }));
  },

  alerts(d) {
    return d.clients.filter(mismatch).map((c) => ({ key: `unifi:fixed:${c.mac}`, status: 'warn',
      title: `${label(c)} has ${c.ip}, reserved ${c.fixedIp}`, detail: 'reservation not in effect (static IP in the guest, or an old lease)',
      object: `client:${c.mac}` }));
  },

  kpis(d) {
    const wan = d.health.wan;
    return [{ label: 'clients', value: `${d.clients.filter((c) => c.online).length}`,
      sub: `${d.clients.filter((c) => c.reserved).length} reserved · ${wan?.status === 'ok' ? 'wan ok' : 'wan ' + (wan?.status || '?')}`,
      status: wan && wan.status !== 'ok' ? 'bad' : null, view: 'network' }];
  },

  // topology refs: "wan" → WAN health, "devices" → every adopted device online
  status(d, ref) {
    if (ref === 'wan') return d.health.wan ? (d.health.wan.status === 'ok' ? 'ok' : 'bad') : null;
    if (ref === 'devices') return d.devices.filter((x) => x.adopted !== false).every((x) => x.online) ? 'ok' : 'warn';
    return null;
  },

  search(d) {
    return d.clients.filter((c) => c.reserved || c.online).map((c) => ({ label: label(c),
      sub: `${c.ip || ''} ${c.mac} ${c.network || ''}`, status: c.online ? 'ok' : 'off', object: `client:${c.mac}` }));
  },

  actions(obj, d) {
    if (obj.type !== 'client') return [];
    const c = d.clients.find((x) => `client:${x.mac}` === obj.id);
    if (!c) return [];
    const out = [];
    if (!c.reserved && c.online && c.ip) {
      out.push({ label: `reserve ${c.ip}`, icon: 'key', method: 'POST', path: '/api/reservations', body: { mac: c.mac, ip: c.ip } });
    }
    if (c.reserved) {
      out.push({ label: 'remove reservation', icon: 'close', method: 'DELETE', path: `/api/reservations/${c.mac}`,
        confirm: `Remove the ${c.fixedIp} reservation of ${label(c)}? It gets a pool address at its next lease.` });
    }
    out.push(c.blocked
      ? { label: 'unblock client', icon: 'check', method: 'POST', path: `/api/clients/${c.mac}/unblock` }
      : { label: 'block client', icon: 'shield', method: 'POST', path: `/api/clients/${c.mac}/block`,
        confirm: `Block ${label(c)} from the network? It is disconnected and cannot rejoin until unblocked.` });
    return out;
  },

  views: [{ id: 'network', label: 'Network', icon: 'router', component: NetworkView, min: 'admin' }],
  facets: { client: ClientFacet, machine: MachineFacet, external: UdrFacet },
  tiles: [{ id: 'clients', label: 'clients · unifi', w: 2, h: 1, component: ClientsTile, min: 'admin' }],
};
