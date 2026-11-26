// cloudflare — DNS records, proxied flags and Access for the zones the API token sees, straight from the Cloudflare API
// through the gateway (the token is module config; the browser never sees it). Zones and the account are discovered.
import EdgeView from './EdgeView.svelte';
import CloudFacet from './CloudFacet.svelte';
import DomainFacet from './DomainFacet.svelte';
import DnsTile from './DnsTile.svelte';
import { loadSlow, loadRecords, staleA } from './cf.js';

const ADDR = ['A', 'AAAA', 'CNAME'];

export default {
  id: 'cloudflare',

  async load(ctx) {
    const s = await loadSlow(ctx);
    const records = await loadRecords(ctx, s.zones);
    return { zones: s.zones, apps: s.apps, policies: s.policies, accountId: s.accountId, records };
  },

  alerts(d) {
    return staleA(d.records).map((r) => ({ key: `cloudflare:stale:${r.name}`, status: 'warn', title: `${r.name} A ${r.content} ≠ apex`,
      detail: 'explicit A record differs from the zone apex: add it to your dynamic-DNS updater or make it a CNAME → apex', object: r.name }));
  },

  kpis(d) {
    const addr = d.records.filter((r) => ADDR.includes(r.type));
    return [{ label: 'dns', value: `${addr.length}`, sub: `${addr.filter((r) => r.proxied).length} proxied · ${d.apps.length} access`, view: 'edge' }];
  },

  search(d) {
    return d.records.filter((r) => ADDR.includes(r.type) && !r.name.startsWith('*.'))
      .map((r) => ({ label: r.name, sub: `${r.type} ${r.content}${r.proxied ? ' · proxied' : ''}`, object: r.name }));
  },

  actions(obj, d) {
    if (obj.type !== 'domain') return [];
    const r = d.records.find((x) => x.name === obj.id && ADDR.includes(x.type));
    const z = d.zones.find((x) => obj.id === x.name || obj.id.endsWith(`.${x.name}`));
    const out = [];
    if (r?.proxiable) {
      out.push(r.proxied
        ? { label: 'stop proxying', icon: 'cloud', method: 'PATCH', path: `/zones/${r.zoneId}/dns_records/${r.id}`, body: { proxied: false },
          confirm: `Stop proxying ${r.name}? Hosts with the origin lock (Authenticated Origin Pulls) answer 400 without Cloudflare.` }
        : { label: 'proxy via cloudflare', icon: 'cloud', method: 'PATCH', path: `/zones/${r.zoneId}/dns_records/${r.id}`, body: { proxied: true } });
    }
    if (z && (r?.proxied || obj.id === z.name)) {
      out.push({ label: 'purge cache', icon: 'restart', method: 'POST', path: `/zones/${z.id}/purge_cache`, body: { hosts: [obj.id] } });
    }
    return out;
  },

  views: [{ id: 'edge', label: 'Cloudflare', icon: 'cloud', component: EdgeView, min: 'admin' }],
  facets: { external: CloudFacet, domain: DomainFacet },
  tiles: [{ id: 'edge-dns', label: 'dns · cloudflare', w: 2, h: 1, component: DnsTile, min: 'admin' }],
};
