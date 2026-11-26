// bazarr — subtitles in lab: wanted counts, providers, tasks, health. Backend = Bazarr's API with its key (X-API-KEY).
import { cached, soft, worstOf, clip } from '$lab/sdk.js';
import Facet from './Facet.svelte';

export default {
  id: 'bazarr',

  async load(ctx) {
    const k = (key) => `${ctx.id}:${key}`;
    const [status, badges, health, providers, tasks, eps, movies] = await Promise.all([
      cached(k('status'), 600000, () => ctx.api.get('/api/system/status')),
      ctx.api.get('/api/badges'),
      soft(ctx.api.get('/api/system/health')),
      soft(cached(k('providers'), 60000, () => ctx.api.get('/api/providers'))),
      soft(cached(k('tasks'), 30000, () => ctx.api.get('/api/system/tasks'))),
      soft(cached(k('eps'), 300000, () => ctx.api.get('/api/episodes/wanted', { start: 0, length: 8 }))),
      soft(cached(k('movies'), 300000, () => ctx.api.get('/api/movies/wanted', { start: 0, length: 8 }))),
    ]);
    return {
      version: status?.data?.bazarr_version, badges: badges || {},
      health: health?.data || [], providers: providers?.data || [], tasks: tasks?.data || [],
      wantedEps: { total: eps?.total ?? badges?.episodes, items: eps?.data || [] },
      wantedMovies: { total: movies?.total ?? badges?.movies, items: movies?.data || [] },
    };
  },

  objects(d, ctx) {
    const b = d.badges;
    const live = [b.sonarr_signalr, b.radarr_signalr].filter((x) => x && x !== 'LIVE').length;
    const st = worstOf([d.health.length ? 'warn' : 'ok', b.providers ? 'warn' : 'ok', live ? 'warn' : 'ok']);
    return [{ id: 'bazarr', type: 'service', name: 'bazarr', kind: 'subtitles', parent: ctx?.settings?.parent || undefined, status: st,
      meta: [d.version && `v${d.version}`, `${d.wantedEps.total ?? '–'} eps · ${d.wantedMovies.total ?? '–'} movies wanted`].filter(Boolean).join(' · ') }];
  },

  alerts(d) {
    const out = d.health.map((h, i) => ({ key: `bazarr:health:${h.object || i}`, status: 'warn', title: `Bazarr: ${clip(h.issue || h.object || 'health issue', 120)}`,
      detail: h.object || '', since: null, object: 'bazarr' }));
    for (const [k, v] of [['sonarr', d.badges.sonarr_signalr], ['radarr', d.badges.radarr_signalr]]) {
      if (v && v !== 'LIVE') out.push({ key: `bazarr:signalr:${k}`, status: 'warn', title: `Bazarr lost its live link to ${k} (${v})`, detail: '', since: null, object: 'bazarr' });
    }
    return out;
  },

  facets: { service: Facet },
};
