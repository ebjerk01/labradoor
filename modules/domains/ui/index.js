// domains — the cross-cutting hostname view. No backend of its own: every hook joins what the npm, cloudflare, unifi and
// drift modules already loaded (ctx.peer, read-only; unifi and drift are optional). Hostnames become `domain` objects (id = the FQDN); npm and
// cloudflare add their facets to them. "dead?" flags feed the planned NPMplus cleanup; nothing is ever deleted here.
import DomainsView from './DomainsView.svelte';
import ChainFacet from './ChainFacet.svelte';
import DomainsTile from './DomainsTile.svelte';
import { rows } from './rows.js';

const meta = (r) => [
  r.npm ? `→ ${r.machine?.machine || r.machine?.name || r.npm.host}:${r.npm.port}` : r.dns.kind === 'record' ? `${r.dns.type} ${r.dns.content}` : r.dns.kind,
  r.dns.proxied ? 'proxied' : r.dns.kind === 'wildcard' ? 'wildcard' : null,
  r.access.length ? 'access' : null, r.npm?.originLock ? 'cf-only' : null, r.dead ? 'DEAD?' : null,
].filter(Boolean).join(' · ');

export default {
  id: 'domains',

  async load() {
    return { at: Date.now() / 1000 }; // the data lives in the other modules
  },

  objects(data, ctx) {
    return rows(ctx).map((r) => ({ id: r.name, type: 'domain', name: r.name, kind: r.npm ? 'site' : 'dns name',
      status: r.status, meta: meta(r), parent: r.machine?.machine || undefined, dead: r.dead || undefined }));
  },

  kpis(data, ctx) {
    const rs = rows(ctx);
    if (!rs.length) return [];
    const dead = rs.filter((r) => r.dead || r.dnsOnly).length;
    return [{ label: 'domains', value: `${rs.filter((r) => r.status === 'ok').length}/${rs.length}`,
      sub: dead ? `${dead} cleanup candidates` : 'no dead hosts', status: rs.some((r) => r.status === 'bad') ? 'bad' : null, view: 'domains' }];
  },

  search(data, ctx) {
    return rows(ctx).map((r) => ({ label: r.name, sub: meta(r), status: r.status, object: r.name }));
  },

  views: [{ id: 'domains', label: 'Domains', icon: 'globe', component: DomainsView, min: 'admin' }],
  facets: { domain: ChainFacet },
  tiles: [{ id: 'domains', label: 'domains', w: 2, h: 1, component: DomainsTile, min: 'admin' }],
};
