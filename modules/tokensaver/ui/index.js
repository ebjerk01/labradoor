// tokenSaver — UI half. Shows the plugin's lifetime savings from workstation's Claude Code
// sessions. Reads only $lab/ + its own files (manifest:2 deploy gate).
import { soft, siteStatus, cached } from '$lab/sdk.js';
import Facet from './Facet.svelte';
import Tile from './Tile.svelte';

function problems(data) {
  const out = [];
  if (!data.status?.ok) {
    out.push({ key: 'tokensaver:down', status: 'warn', title: 'tokenSaver stats unavailable',
               detail: data.status?.error || '', object: 'tokensaver' });
  }
  return out;
}

function fmtNum(n) {
  n = Number(n || 0);
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(Math.round(n));
}
function fmtTime(ms) {
  const s = Number(ms || 0) / 1000;
  if (s < 60) return s.toFixed(0) + 's';
  const m = s / 60;
  if (m < 60) return m.toFixed(0) + 'm';
  const h = m / 60;
  if (h < 24) return h.toFixed(1) + 'h';
  return (h / 24).toFixed(1) + 'd';
}

function disp(lt) {
  return {
    cost: '$' + Number(lt.costSavedInUsd || 0).toFixed(2),
    tokens: fmtNum(lt.tokensSaved),
    calls: fmtNum(lt.callsSaved),
    time: fmtTime(lt.timeSavedInMs),
    sessions: Number(lt.sessionCount || 0),
  };
}

export default {
  id: 'tokensaver',

  async load(ctx) {
    const [status, stats] = await Promise.all([
      ctx.api.get('/api/status'),
      soft(cached(`${ctx.id}:stats`, 60000, () => ctx.api.get('/api/stats')), {}),
    ]);
    const lt = (stats && stats.lifetime) || {};
    return { status, lt, disp: disp(lt), enabled: stats?.enabled, version: stats?.version,
             at: Date.now() / 1000 };
  },

  objects(data) {
    return [{ id: 'tokensaver', type: 'service', name: 'tokenSaver', kind: 'service',
              status: siteStatus(problems(data)), meta: `${data.disp.cost} saved` }];
  },

  alerts: (data) => problems(data),
  kpis: (data) => [
    { label: 'saved', value: data.disp.cost, sub: `${data.disp.tokens} tokens`, status: siteStatus(problems(data)) },
    { label: 'calls saved', value: data.disp.calls, sub: `${data.disp.sessions} sessions` },
  ],

  facets: { service: Facet },
  tiles: [{ id: 'tokensaver', label: 'tokenSaver', w: 2, h: 1, component: Tile }],
};
