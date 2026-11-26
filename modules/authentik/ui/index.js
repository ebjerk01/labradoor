// authentik — identity in lab: users, groups, app access, login events. Backend = Authentik's own API through the gateway
// with a service-account token from the module config (RBAC role, not superuser). Every change is owner-only.
import IdentityView from './IdentityView.svelte';
import PersonFacet from './PersonFacet.svelte';
import GroupFacet from './GroupFacet.svelte';
import PeopleTile from './PeopleTile.svelte';
import LoginsTile from './LoginsTile.svelte';
import { humans, U } from './ak.js';
import { ago, cached, soft } from '$lab/sdk.js';

// Authentik lists only the apps the CALLER may open (the full list is superuser-only, and the gateway's account is
// deliberately not), so: provider list (view_provider) → app slugs → each app by slug. That is ~20 requests and apps
// rarely change, so they are fetched once per 10 min, in the background: load() never waits for them.
let appsNow = [];
let appsAsked = false;
function fetchApps(ctx) {
  return cached(`${ctx.id}:apps`, 600000, async () => {
    const prov = await ctx.api.get('/api/v3/providers/all/', { page_size: 300 });
    const slugs = [...new Set(prov.results.map((p) => p.assigned_application_slug).filter(Boolean))];
    const got = await Promise.allSettled(slugs.map((s) => ctx.api.get(`/api/v3/core/applications/${encodeURIComponent(s)}/`)));
    return got.filter((r) => r.status === 'fulfilled').map((r) => r.value).sort((a, b) => a.name.localeCompare(b.name));
  });
}
function apps(ctx) {
  const first = !appsAsked;
  appsAsked = true;
  fetchApps(ctx).then((a) => {
    const changed = first || a.length !== appsNow.length || a.some((x, i) => x.pk !== appsNow[i]?.pk);
    appsNow = a;
    if (changed) ctx.refresh();
  }, () => { appsAsked = false; });
  return { list: appsNow, ready: appsNow.length > 0 || !first };
}

const LOGIN = new Set(['login', 'login_failed', 'logout', 'user_write', 'password_set', 'model_created', 'model_deleted']);

export default {
  id: 'authentik',

  async load(ctx) {
    // users, groups and bindings change rarely: 20 s cache (a write through lab drops it). Events are always fresh.
    const q = { page_size: 300 };
    const [users, groups, bindings, events] = await Promise.all([
      cached(`${ctx.id}:d:users`, 20000, () => ctx.api.get('/api/v3/core/users/', { ...q, ordering: 'username' })),
      cached(`${ctx.id}:d:groups`, 20000, () => ctx.api.get('/api/v3/core/groups/', { ...q, ordering: 'name', include_users: 'false' })),
      cached(`${ctx.id}:d:bindings`, 20000, () => ctx.api.get('/api/v3/policies/bindings/', { page_size: 500 })),
      soft(ctx.api.get('/api/v3/events/events/', { page_size: Number(ctx.settings.events) || 60, ordering: '-created' }), { results: [] }),
    ]);
    const a = apps(ctx);
    return { users: users.results, groups: groups.results, apps: a.list, appsReady: a.ready, bindings: bindings.results,
      events: events.results.filter((e) => LOGIN.has(e.action)) };
  },

  objects(d, ctx) {
    const out = [];
    for (const u of humans(d.users)) {
      const gs = (u.groups_obj || []).map((g) => g.name);
      out.push({ id: `user:${u.username}`, type: 'person', name: u.name || u.username, kind: u.is_superuser ? 'superuser' : u.type,
        status: u.is_active ? 'ok' : 'off', meta: `${u.username} · ${gs.length} groups · ${u.last_login ? 'seen ' + ago(Date.parse(u.last_login) / 1000, ctx.now) + ' ago' : 'never logged in'}`,
        ownerOnly: 'identity · authentik', pk: u.pk });
    }
    for (const g of d.groups) {
      out.push({ id: `group:${g.name}`, type: 'group', name: g.name, kind: g.is_superuser ? 'superuser group' : 'group',
        status: 'ok', meta: `${(g.users || []).length} members`, ownerOnly: 'identity · authentik', pk: g.pk });
    }
    return out;
  },

  alerts(d) {
    const hour = Date.now() / 1000 - 3600;
    const fails = d.events.filter((e) => e.action === 'login_failed' && Date.parse(e.created) / 1000 > hour);
    return fails.length >= 5 ? [{ key: 'authentik:login_failed', status: 'warn', title: `${fails.length} failed Authentik logins in the last hour`,
      detail: [...new Set(fails.map((e) => e.context?.username || e.user?.username))].join(', '), since: Date.parse(fails.at(-1).created) / 1000, object: null }] : [];
  },

  kpis(d) {
    const hs = humans(d.users);
    return [{ label: 'people', value: `${hs.filter((u) => u.is_active).length}`, sub: `${d.groups.length} groups · ${d.appsReady ? d.apps.length : '…'} apps`, view: 'identity' }];
  },

  ticker(d, ctx) {
    return d.events.slice(0, 5).map((e) => ({
      g: e.action === 'login_failed' ? '▲' : '●', c: e.action === 'login_failed' ? 'var(--warn)' : 'var(--ok)', s: 'auth',
      object: e.user?.username ? `user:${e.user.username}` : undefined, m: `${e.user?.username || e.context?.username || '?'} ${e.action.replace('_', ' ')} · ${ago(Date.parse(e.created) / 1000, ctx.now)} ago`,
    }));
  },

  actions(obj, d) {
    if (obj.type !== 'person') return [];
    const u = d.users.find((x) => x.pk === obj.pk);
    if (!u) return [];
    return [
      { label: u.is_active ? 'deactivate user' : 'activate user', icon: 'lock', method: 'PATCH', path: `${U}${u.pk}/`, body: { is_active: !u.is_active } },
    ];
  },

  views: [{ id: 'identity', label: 'Identity', icon: 'shield', component: IdentityView, min: 'admin' }],
  facets: { person: PersonFacet, group: GroupFacet },
  tiles: [
    { id: 'people', label: 'people', w: 4, h: 2, component: PeopleTile, min: 'admin' },
    { id: 'logins', label: 'logins', w: 4, h: 2, component: LoginsTile, min: 'admin' },
  ],
};
