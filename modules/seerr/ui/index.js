// seerr — Seerr in lab, all of it: requests (per person — the connector `seerr` on :8114 maps the signed-in lab user to their
// Seerr account, so guests see and request only as themselves), discover/search with posters, media objects
// (seerr:<type>:<tmdb>), issues, users + quotas + permissions, and Seerr's settings / jobs / caches.
import Facet from './Facet.svelte';
import MediaFacet from './MediaFacet.svelte';
import MineTile from './MineTile.svelte';
import RecentTile from './RecentTile.svelte';
import RequestsTile from './RequestsTile.svelte';
import DiscoverView from './DiscoverView.svelte';
import RequestsView from './RequestsView.svelte';
import IssuesView from './IssuesView.svelte';
import UsersView from './UsersView.svelte';
import SettingsView from './SettingsView.svelte';
import { stateOf, name, rankTitles } from './sr.js';
import { GLYPH, statusVar, ts } from '$lab/sdk.js';

const uniq = (lists) => {
  const seen = new Set();
  return lists.flat().filter((r) => r && !seen.has(r.id) && seen.add(r.id));
};

export default {
  id: 'seerr',
  load: (ctx) => ctx.api.get('/api/overview'),

  objects(d, ctx) {
    const out = [];
    if (d.counts) {
      out.push({ id: 'seerr', type: 'service', name: 'seerr', kind: 'requests', parent: ctx?.settings?.host || undefined,
        status: d.failed?.length ? 'warn' : 'ok',
        meta: [d.version && `v${d.version}`, `${d.counts.total} requests`, d.counts.pending ? `${d.counts.pending} pending` : null,
          d.issues?.open ? `${d.issues.open} issues` : null, d.updateAvailable ? 'update' : null].filter(Boolean).join(' · ') });
    }
    // one object per requested title (admins: the latest + pending + failed; guests: their own)
    const byObj = new Map();
    for (const r of uniq([d.pending || [], d.failed || [], d.all || [], d.mine || []])) {
      if (!r.object || byObj.has(r.object)) continue;
      byObj.set(r.object, r);
      const st = stateOf(r);
      out.push({ id: r.object, type: 'seerr-media', name: name(r), kind: r.type === 'tv' ? 'series' : 'movie', parent: d.counts ? 'seerr' : undefined,
        status: st.s, meta: [st.t, r.by && `by ${r.by}`].filter(Boolean).join(' · ') });
    }
    return out;
  },

  alerts(d, ctx) {
    const out = [];
    const min = Number(ctx?.settings?.alert_pending_min) || 0;
    const now = Date.now() / 1000;
    const waiting = (d.pending || []).filter((r) => now - ts(r.created) >= min * 60);
    if (d.counts && waiting.length) {
      out.push({ key: 'seerr:pending', status: 'warn', title: `${waiting.length} media request${waiting.length > 1 ? 's' : ''} waiting for approval`,
        detail: waiting.slice(0, 3).map((r) => `${name(r)} (${r.by})`).join(', '), since: ts(waiting.at(-1).created), object: 'seerr' });
    }
    if (d.failed?.length) {
      out.push({ key: 'seerr:failed', status: 'warn', title: `${d.failed.length} media request${d.failed.length > 1 ? 's' : ''} failed`,
        detail: d.failed.slice(0, 3).map((r) => name(r)).join(', '), since: ts(d.failed[0].updated), object: 'seerr' });
    }
    if (d.issues?.open) {
      out.push({ key: 'seerr:issues', status: 'warn', title: `${d.issues.open} open Seerr issue${d.issues.open > 1 ? 's' : ''}`, detail: 'reported playback problems', since: null, object: 'seerr' });
    }
    if (d.updateAvailable) {
      out.push({ key: 'seerr:update', status: 'warn', title: `Seerr update available (v${d.version}, ${d.commitsBehind || '?'} behind)`, detail: 'rebuild on CT 115, see memory seerr.md', since: null, object: 'seerr' });
    }
    return out;
  },

  kpis(d) {
    if (!d.counts) return [];
    return [{ label: 'requests', value: `${d.counts.processing + d.counts.pending}`,
      sub: `open · ${d.counts.pending} to approve · ${d.failed?.length || 0} failed · ${d.issues?.open || 0} issues`,
      status: d.counts.pending || d.failed?.length ? 'warn' : null, open: 'seerr' }];
  },

  ticker(d) {
    const day = Date.now() / 1000 - 86400;
    const fresh = (d.all || d.mine || []).filter((r) => ts(r.created) > day).slice(0, 3)
      .map((r) => ({ g: '●', c: 'var(--sig)', s: 'seerr', m: `new request · ${name(r)}${r.by ? ' · ' + r.by : ''}`, object: r.object }));
    const moved = (d.all || d.mine || []).filter((r) => ts(r.updated) > day && ts(r.created) <= day).slice(0, 3).map((r) => {
      const st = stateOf(r);
      return { g: GLYPH[st.s], c: statusVar(st.s), s: 'seerr', m: `${name(r)}${r.by ? ' · ' + r.by : ''} · ${st.t}`, object: r.object };
    });
    return [...fresh, ...moved];
  },

  search(d) {
    return uniq([d.mine || [], d.all || []])
      .map((r) => ({ label: name(r), sub: `request · ${stateOf(r).t}${r.by ? ' · ' + r.by : ''}`, status: stateOf(r).s, object: r.object }));
  },

  // Ctrl-K: anything in TMDB through Seerr (q ≥ 3). A title lab already has as an object opens its panel; others open
  // in Seerr (request them in ~/seerr-discover).
  async lookup(q, ctx) {
    if (ctx.data()?.me?.linked === false && ctx.role === 'guest') return [];
    const r = await ctx.api.get('/api/search', { q });
    const pub = ctx.data()?.me?.public;
    return rankTitles(q, (r.results || []).filter((x) => x.type !== 'person')).slice(0, 4).map((x) => ({
      label: `${x.title}${x.year ? ` (${x.year})` : ''}`, sub: `${x.type === 'tv' ? 'series' : 'movie'} · ${x.status === 'unknown' ? 'not in the library — request in ~/seerr-discover' : x.status}`,
      status: { available: 'ok', partial: 'ok', processing: 'ok', pending: 'warn' }[x.status] || 'off',
      ...(ctx.object(`seerr:${x.type}:${x.tmdb}`) ? { object: `seerr:${x.type}:${x.tmdb}` } : pub ? { url: `${pub}/${x.type}/${x.tmdb}` } : {}),
    }));
  },

  actions(obj, d) {
    if (obj.id === 'seerr' && d.counts) return [{ label: 'open seerr', icon: 'ext', url: d.me.public }];
    if (obj.type !== 'seerr-media') return [];
    const reqs = uniq([d.pending || [], d.failed || [], d.all || [], d.mine || []]).filter((r) => r.object === obj.id);
    const r = reqs[0];
    if (!r) return [];
    const out = [];
    for (const p of reqs.filter((x) => x.status === 'pending')) {
      out.push({ label: `approve #${p.id}${p.by ? ` (${p.by})` : ''}`, icon: 'check', method: 'POST', path: `/api/requests/${p.id}/approve`, body: {} });
      out.push({ label: `decline #${p.id}`, icon: 'close', method: 'POST', path: `/api/requests/${p.id}/decline`, body: {}, confirm: `Decline ${name(p)} requested by ${p.by}?` });
    }
    for (const f of reqs.filter((x) => x.status === 'failed')) out.push({ label: `retry #${f.id}`, icon: 'restart', method: 'POST', path: `/api/requests/${f.id}/retry`, body: {} });
    if (r.mediaId) {
      out.push({ label: 'mark available', icon: 'check', method: 'POST', path: `/api/media/${r.mediaId}/status`, body: { status: 'available', is4k: !!r.is4k } });
      out.push({ label: 'clear media data', icon: 'restart', method: 'POST', path: `/api/media/${r.mediaId}/clear`, body: {},
        confirm: `Clear Seerr's data for ${name(r)}? Its requests go too; the files and the Sonarr/Radarr entry stay.` });
      out.push({ label: 'delete files', icon: 'close', method: 'POST', path: `/api/media/${r.mediaId}/delete-file`, body: { is4k: !!r.is4k },
        confirm: `DELETE ${name(r)} from ${r.type === 'tv' ? 'Sonarr' : 'Radarr'} INCLUDING THE FILES on disk? This cannot be undone.` });
    }
    out.push({ label: 'open in seerr', icon: 'ext', url: r.seerr });
    return out;
  },

  facets: { service: Facet, machine: Facet, 'seerr-media': MediaFacet },
  views: [
    { id: 'seerr-discover', label: 'Discover', icon: 'search', component: DiscoverView },
    { id: 'seerr-requests', label: 'Requests', icon: 'download', component: RequestsView },
    { id: 'seerr-issues', label: 'Issues', icon: 'bell', component: IssuesView, min: 'admin' },
    { id: 'seerr-users', label: 'Users', icon: 'user', component: UsersView, min: 'admin' },
    { id: 'seerr-settings', label: 'Settings', icon: 'wrench', component: SettingsView, min: 'admin' },
  ],
  tiles: [
    { id: 'mine', label: 'my requests', w: 4, h: 2, component: MineTile },
    { id: 'recent', label: 'recently added', w: 4, h: 2, component: RecentTile },
    { id: 'requests', label: 'requests', w: 4, h: 2, component: RequestsTile, min: 'admin' },
  ],
};
