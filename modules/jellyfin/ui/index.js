// jellyfin — all of Jellyfin's admin dashboard in lab: libraries (folders, options, scans), items (browse, detail, metadata,
// identify, refresh, delete), live sessions + devices (message, pause/stop, sign out; shown, never stored), the activity log
// (ticker + failed-login alerts), Jellyfin user accounts (objects `jellyfin-user:<name>`; every change is owner-only identity →
// admins ask), scheduled tasks + triggers, plugins + catalog, transcoding, logs, storage, API keys (owner only), restart.
import Facet from './Facet.svelte';
import UserFacet from './UserFacet.svelte';
import ItemFacet from './ItemFacet.svelte';
import PersonLink from './PersonLink.svelte';
import UsersView from './UsersView.svelte';
import LibrariesView from './LibrariesView.svelte';
import ItemsView from './ItemsView.svelte';
import SessionsView from './SessionsView.svelte';
import ServerView from './ServerView.svelte';
import PlayingTile from './PlayingTile.svelte';
import { session, user, access, label, UID, links } from './jf.js';
import { IID, opened } from './store.svelte.js';
import { ago, cached, soft, worstOf } from '$lab/sdk.js';

const RECENT = { Recursive: 'true', SortBy: 'DateCreated', SortOrder: 'Descending', IncludeItemTypes: 'Movie,Episode', Limit: 24,
  Fields: 'DateCreated', EnableImages: 'false', EnableUserData: 'false' };
const DAY = 86400;
const QUIET = new Set(['VideoPlayback', 'VideoPlaybackStopped', 'AudioPlayback', 'AudioPlaybackStopped', 'SessionStarted', 'SessionEnded']);
const BROKEN = new Set(['Malfunctioned', 'NotSupported']);
const looked = new Map();  // Ctrl-K lookups: item id → name, so an opened result has a title before its facet loads

export default {
  id: 'jellyfin',

  async load(ctx) {
    const [info, libs, counts, recent, sessions, tasks, users, activity, plugins] = await Promise.all([
      cached(`${ctx.id}:info`, 120000, () => ctx.api.get('/System/Info')),
      cached(`${ctx.id}:libs`, 60000, () => ctx.api.get('/Library/VirtualFolders')),
      soft(cached(`${ctx.id}:counts`, 300000, () => ctx.api.get('/Items/Counts'))),
      soft(cached(`${ctx.id}:recent`, 60000, () => ctx.api.get('/Items', RECENT))),
      ctx.api.get('/Sessions', { ActiveWithinSeconds: 960 }),
      soft(cached(`${ctx.id}:tasks`, 20000, () => ctx.api.get('/ScheduledTasks', { IsHidden: 'false' }))),
      soft(cached(`${ctx.id}:users`, 60000, () => ctx.api.get('/Users'))),
      soft(cached(`${ctx.id}:activity`, 45000, () => ctx.api.get('/System/ActivityLog/Entries', { limit: 60 }))),
      soft(cached(`${ctx.id}:plugins`, 300000, () => ctx.api.get('/Plugins'))),
    ]);
    return {
      version: info?.Version, server: info?.ServerName, restart: !!info?.HasPendingRestart, update: !!info?.HasUpdateAvailable,
      canRestart: info?.CanSelfRestart !== false, paths: info ? { data: info.ProgramDataPath, cache: info.CachePath, logs: info.LogPath,
        metadata: info.InternalMetadataPath, transcodes: info.TranscodingTempPath, web: info.WebPath } : {},
      libs: (libs || []).map((l) => ({ id: l.ItemId || `new:${l.Name}`, name: l.Name,  // no ItemId until its first scan (new / renamed)
         type: l.CollectionType, paths: l.Locations || [], refresh: l.RefreshStatus,
        progress: l.RefreshProgress, options: l.LibraryOptions || {} })),
      counts: counts || {},
      recent: (recent?.Items || []).map((it) => ({ id: it.Id, label: label(it), name: it.Name, type: it.Type, added: Date.parse(it.DateCreated) / 1000 })),
      sessions: (sessions || []).map(session),
      tasks: (tasks || []).map((t) => ({ id: t.Id, key: t.Key, name: t.Name, state: t.State, progress: t.CurrentProgressPercentage,
        category: t.Category, description: t.Description, triggers: t.Triggers || [],
        last: t.LastExecutionResult ? { status: t.LastExecutionResult.Status, start: Date.parse(t.LastExecutionResult.StartTimeUtc) / 1000,
          end: Date.parse(t.LastExecutionResult.EndTimeUtc) / 1000, error: t.LastExecutionResult.ErrorMessage } : null })),
      users: (users || []).map((u) => user(u, libs)).sort((a, b) => a.name.localeCompare(b.name)),
      usersOk: !!users,
      activity: (activity?.Items || []).map((a) => ({ id: a.Id, name: a.Name, short: a.ShortOverview || '', overview: a.Overview || '', type: a.Type,
        at: Date.parse(a.Date) / 1000, userId: a.UserId, itemId: a.ItemId || null, severity: a.Severity })),
      activityOk: !!activity,
      plugins: (plugins || []).map((p) => ({ id: p.Id, name: p.Name, version: p.Version, status: p.Status, canUninstall: !!p.CanUninstall, description: p.Description })),
    };
  },

  objects(d, ctx) {
    const playing = d.sessions.filter((s) => s.playing).length;
    const failed = d.tasks.filter((t) => t.last?.status === 'Failed').length;
    const out = [{ id: 'jellyfin', type: 'service', name: 'jellyfin', kind: 'media', parent: ctx?.settings?.host || undefined,
      status: d.restart || failed || d.plugins.some((p) => BROKEN.has(p.status)) ? 'warn' : 'ok',
      meta: [d.version && `v${d.version}`, `${playing} playing`, d.counts.MovieCount != null ? `${d.counts.MovieCount} movies · ${d.counts.SeriesCount} series` : null].filter(Boolean).join(' · ') }];
    for (const u of d.users) {
      out.push({ id: UID(u.name), type: 'jellyfin-user', name: u.name, kind: u.admin ? 'jellyfin admin' : 'jellyfin user', parent: 'jellyfin',
        status: u.disabled ? 'off' : 'ok', ownerOnly: 'identity · jellyfin',
        meta: `${access(u)} · ${u.lastActivity ? 'seen ' + ago(u.lastActivity) + ' ago' : 'never seen'}${u.disabled ? ' · disabled' : ''}` });
    }
    // items: the ones opened in this browser, plus whatever item the URL points at (deep links)
    const items = [...opened.list];
    const sel = ctx?.selected();
    if (sel?.startsWith('jellyfin-item:') && !items.some((x) => IID(x.id) === sel)) {
      const id = sel.slice(14);
      items.push({ id, name: looked.get(id) || `item ${id.slice(0, 8)}`, type: 'item' });
    }
    for (const it of items) {
      out.push({ id: IID(it.id), type: 'jellyfin-item', name: it.name, kind: (it.type || 'item').toLowerCase(), parent: 'jellyfin', status: 'ok', meta: 'jellyfin item' });
    }
    return out;
  },

  kpis(d) {
    const playing = d.sessions.filter((s) => s.playing);
    const tc = playing.filter((s) => s.method === 'Transcode').length;
    return [
      { label: 'jellyfin streams', value: String(playing.length), sub: tc ? `${tc} transcoding` : 'all direct', status: tc ? 'warn' : null, open: 'jellyfin' },
      { label: 'jellyfin library', value: String(d.counts.MovieCount ?? '–'), sub: `movies · ${d.counts.SeriesCount ?? '–'} series · ${d.counts.EpisodeCount ?? '–'} ep`, open: 'jellyfin' },
    ];
  },

  alerts(d, ctx) {
    const out = [];
    if (d.restart) out.push({ key: 'jellyfin:restart', status: 'warn', title: 'Jellyfin needs a restart', detail: 'pending plugin or settings change', since: null, object: 'jellyfin' });
    for (const t of d.tasks.filter((x) => x.last?.status === 'Failed')) {
      out.push({ key: `jellyfin:task:${t.key}`, status: 'warn', title: `Jellyfin task failed: ${t.name}`, detail: t.last.error || '', since: t.last.end, object: 'jellyfin' });
    }
    for (const p of d.plugins.filter((x) => BROKEN.has(x.status))) {
      out.push({ key: `jellyfin:plugin:${p.id}`, status: 'warn', title: `Jellyfin plugin ${p.name}: ${p.status}`, detail: p.version, since: null, object: 'jellyfin' });
    }
    const limit = ctx?.settings?.failed_login_alert ?? 1;
    const fails = d.activity.filter((a) => a.type === 'AuthenticationFailed' && a.at > Date.now() / 1000 - DAY);
    if (limit > 0 && fails.length >= limit) {
      out.push({ key: `jellyfin:failed-logins:${fails[fails.length - 1].id}`, status: fails.length >= 5 ? 'bad' : 'warn',
        title: `Jellyfin: ${fails.length} failed login${fails.length > 1 ? 's' : ''} (24 h)`,
        detail: [...new Set(fails.map((a) => `${a.name.replace(/^Failed login attempt from /i, '')} ${a.short.replace(/^IP address: /i, '@')}`))].slice(0, 4).join(', '),
        since: fails[fails.length - 1].at, object: 'jellyfin' });
    }
    return out;
  },

  ticker(d, ctx) {
    const out = d.sessions.filter((s) => s.playing && !s.paused).slice(0, 3)
      .map((s) => ({ g: '▶', c: 'var(--sig)', s: 'jellyfin', m: `${s.user} · ${s.playing.type === 'Episode' ? s.playing.series : s.playing.name}`, object: 'jellyfin' }));
    const day = Date.now() / 1000 - DAY;
    for (const it of d.recent.filter((x) => x.added > day).slice(0, 3)) out.push({ g: '●', c: 'var(--ok)', s: 'jellyfin', m: `added ${it.label}`, object: 'jellyfin' });
    if (ctx?.settings?.ticker_activity !== false) {
      for (const a of d.activity.filter((x) => x.at > day && !QUIET.has(x.type)).slice(0, 3)) {
        const bad = a.severity === 'Error' || a.type === 'AuthenticationFailed';
        out.push({ g: bad ? '■' : '●', c: bad ? 'var(--bad)' : 'var(--dim)', s: 'jellyfin', m: a.name, object: 'jellyfin' });
      }
    }
    return out;
  },

  search(d, ctx) {
    const l = links(ctx?.settings);
    return d.users.map((u) => ({ label: u.name, sub: `jellyfin user · ${access(u)} · authentik ${l.toAuthentik(u.name)}`, status: u.disabled ? 'off' : 'ok', object: UID(u.name) }));
  },

  // Ctrl-K: movies, series and episodes by title (3+ characters)
  async lookup(q, ctx) {
    const r = await ctx.api.get('/Items', { searchTerm: q, Recursive: 'true', IncludeItemTypes: 'Movie,Series,Episode', Limit: 8,
      Fields: 'ProductionYear', EnableImages: 'false', EnableUserData: 'false' });
    return (r?.Items || []).slice(0, 4).map((it) => {
      looked.set(it.Id, label(it));
      return { label: label(it), sub: `jellyfin ${it.Type.toLowerCase()}${it.Type === 'Episode' ? ' · ' + it.Name : ''}`, object: IID(it.Id) };
    });
  },

  actions(obj, d) {
    if (obj.id === 'jellyfin') return [{ label: 'scan all libraries', icon: 'restart', method: 'POST', path: '/Library/Refresh', body: {} }];
    if (obj.type !== 'jellyfin-user') return [];
    const u = d.users.find((x) => UID(x.name) === obj.id);
    if (!u) return [];
    return [
      { label: u.disabled ? 'enable' : 'disable', icon: 'lock', method: 'POST', path: `/Users/${u.id}/Policy`, body: { ...u.policy, IsDisabled: !u.disabled },
        confirm: u.disabled ? null : `Disable the Jellyfin user ${u.name}? They are signed out of every device.` },
    ];
  },

  facets: { service: Facet, 'jellyfin-user': UserFacet, 'jellyfin-item': ItemFacet, person: PersonLink },
  views: [
    { id: 'jellyfin-libraries', label: 'Libraries', icon: 'archive', component: LibrariesView, min: 'admin' },
    { id: 'jellyfin-items', label: 'Items', icon: 'search', component: ItemsView, min: 'admin' },
    { id: 'jellyfin-sessions', label: 'Sessions & activity', icon: 'activity', component: SessionsView, min: 'admin' },
    { id: 'jellyfin-users', label: 'Jellyfin users', icon: 'people', component: UsersView, min: 'admin' },
    { id: 'jellyfin-server', label: 'Server', icon: 'node', component: ServerView, min: 'admin' },
  ],
  tiles: [{ id: 'playing', label: 'now playing', w: 4, h: 1, component: PlayingTile, min: 'admin' }],
};
