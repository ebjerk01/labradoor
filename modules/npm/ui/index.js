// npm — NPMplus in lab, through connectors/npm (session login lives there; the NPM user is the non-admin lab-gateway).
// Hostnames are `domain` objects (made by the domains module, which joins DNS → NPM → backend → checks);
// this module adds the proxy facet to them, plus the proxy machine's facet and the ~/proxy view.
import ProxyView from './ProxyView.svelte';
import MachineFacet from './MachineFacet.svelte';
import DomainFacet from './DomainFacet.svelte';
import ProxyTile from './ProxyTile.svelte';
import { days, dayTxt, certLevel } from './net.js';
import { worst } from '$lab/sdk.js';

const hostOf = (d, name) => d.hosts.find((h) => h.domains.includes(name));

export default {
  id: 'npm',

  async load(ctx) {
    return ctx.api.get('/api/overview');
  },

  alerts(d, ctx) {
    const out = [];
    for (const h of d.hosts) {
      if (h.enabled && h.online === false) {
        out.push({ key: `npm:nginx:${h.id}`, status: 'bad', title: `NPM host #${h.id} ${h.domains[0]}: nginx config error`,
          detail: h.err || 'nginx_online false', object: h.domains[0] });
      }
    }
    for (const c of d.certs) {
      const lv = certLevel(days(c.expires));
      if (lv === 'bad' || lv === 'warn') {
        out.push({ key: `npm:cert:${c.id}`, status: lv, title: `NPM cert ${c.name} expires in ${dayTxt(days(c.expires))}`,
          detail: 'short-lived Let\'s Encrypt cert (~6.7 d) — renewal should have happened by now', object: ctx?.settings?.machine || undefined });
      }
    }
    return out;
  },

  kpis(d) {
    const on = d.hosts.filter((h) => h.enabled && h.online !== false).length;
    const min = Math.min(...d.certs.map((c) => days(c.expires)).filter((x) => x != null));
    const lv = certLevel(isFinite(min) ? min : null);
    return [{ label: 'proxy hosts', value: `${on}/${d.hosts.length}`, sub: `cert min ${dayTxt(isFinite(min) ? min : null)}`,
      status: on < d.hosts.filter((h) => h.enabled).length ? 'bad' : lv === 'ok' ? null : lv, view: 'proxy' }];
  },

  ticker(d) {
    const bad = d.hosts.filter((h) => h.enabled && h.online === false);
    return bad.map((h) => ({ g: '■', c: 'var(--bad)', s: 'npm', m: `#${h.id} ${h.domains[0]} nginx error`, object: h.domains[0] }));
  },

  // topology ref "hosts" → are all enabled proxy hosts online in nginx?
  status(d, ref) {
    if (ref === 'hosts') return worst(...d.hosts.filter((h) => h.enabled).map((h) => (h.online === false ? 'bad' : 'ok')));
    return null;
  },

  search(d) {
    return d.hosts.map((h) => ({ label: h.domains.join(' '), sub: `npm #${h.id} → ${h.scheme}://${h.host}:${h.port}`,
      status: !h.enabled ? 'off' : h.online === false ? 'bad' : 'ok', object: h.domains[0] }));
  },

  actions(obj, d) {
    if (obj.type !== 'domain') return [];
    const h = hostOf(d, obj.id);
    if (!h) return [];
    return [
      { label: h.enabled ? 'disable host' : 'enable host', icon: h.enabled ? 'close' : 'check', method: 'POST',
        path: `/api/hosts/${h.id}/${h.enabled ? 'disable' : 'enable'}`,
        confirm: h.enabled ? `Disable NPM host #${h.id} (${h.domains.join(', ')})? It stops answering at once.` : false },
      { label: 'delete host', icon: 'close', method: 'DELETE', path: `/api/hosts/${h.id}`,
        confirm: `DELETE NPM host #${h.id} (${h.domains.join(', ')})? This cannot be undone from lab.` },
    ];
  },

  views: [{ id: 'proxy', label: 'Proxy', icon: 'proxy', component: ProxyView, min: 'admin' }],
  facets: { machine: MachineFacet, external: MachineFacet, domain: DomainFacet }, // the proxy is a topology node too
  tiles: [{ id: 'proxy', label: 'proxy hosts', w: 2, h: 1, component: ProxyTile, min: 'admin' }],
};
