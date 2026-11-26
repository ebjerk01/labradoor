// qbit — qBittorrent through the lab connector `qbit` (connectors/qbit, port 8113). The connector holds the WebUI login;
// the browser only ever sees compact torrent rows (no tracker URLs: private ones carry passkeys).
import Facet from './Facet.svelte';
import Tile from './Tile.svelte';
import TorrentsView from './TorrentsView.svelte';
import { summary, groupOf } from './qb.js';
import { bits, clip } from '$lab/sdk.js';

export default {
  id: 'qbit',

  async load(ctx) {
    const d = await ctx.api.get('/api/overview');
    return { ...d, ...summary(d) };
  },

  objects(d, ctx) {
    const c = d.counts, x = d.transfer;
    const lim = Number(ctx?.settings?.stalled_alert) || 0;
    const st = x.connection_status === 'disconnected' ? 'bad' : c.error || (lim && c.stalled >= lim) ? 'warn' : 'ok';
    return [{ id: 'qbittorrent', type: 'service', name: 'qbittorrent', kind: 'downloads', parent: ctx?.settings?.host || undefined, status: st,
      meta: `${d.version} · ↓ ${bits(x.dl_info_speed)} ↑ ${bits(x.up_info_speed)} · ${d.torrents.length} torrents` }];
  },

  alerts(d, ctx) {
    const out = [];
    if (d.transfer.connection_status === 'disconnected') {
      out.push({ key: 'qbit:disconnected', status: 'bad', title: 'qBittorrent is disconnected', detail: '', since: null, object: 'qbittorrent' });
    }
    const err = d.torrents.filter((t) => groupOf(t) === 'error');
    if (err.length) {
      out.push({ key: 'qbit:errored', status: 'warn', title: `qBittorrent: ${err.length} torrent${err.length > 1 ? 's' : ''} errored`,
        detail: err.slice(0, 3).map((t) => clip(t.name, 50)).join(', '), since: null, object: 'qbittorrent' });
    }
    const lim = Number(ctx?.settings?.stalled_alert) || 0;
    if (lim && d.counts.stalled >= lim) {
      out.push({ key: 'qbit:stalled', status: 'warn', title: `qBittorrent: ${d.counts.stalled} downloads stalled`, detail: '', since: null, object: 'qbittorrent' });
    }
    return out;
  },

  kpis(d) {
    const c = d.counts;
    return [{ label: 'torrents', value: `${c.downloading}↓`, sub: `${bits(d.transfer.dl_info_speed)} · ${c.queued} queued · ${c.stalled} stalled`,
      status: c.error ? 'warn' : null, open: 'qbittorrent' }];
  },

  ticker(d) {
    const day = Date.now() / 1000 - 86400;
    return d.torrents.filter((t) => t.completion_on > day).sort((a, b) => b.completion_on - a.completion_on).slice(0, 3)
      .map((t) => ({ g: '●', c: 'var(--ok)', s: 'qbit', m: `done: ${clip(t.name, 70)}`, object: 'qbittorrent' }));
  },

  search(d) {
    return d.torrents.slice(0, 400).map((t) => ({ label: t.name, sub: `${t.category || '—'} · ${t.state}`, object: 'qbittorrent' }));
  },

  facets: { service: Facet },
  views: [{ id: 'torrents', label: 'Torrents', icon: 'download', component: TorrentsView, min: 'admin' }],
  tiles: [{ id: 'downloads', label: 'downloads', w: 4, h: 1, component: Tile, min: 'admin' }],
};
