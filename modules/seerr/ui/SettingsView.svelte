<script>
  // ~/seerr-settings — Seerr's own settings without its admin pages: general, access (owner), Jellyfin libraries + sync,
  // Radarr / Sonarr defaults, notification agents, jobs, caches, version. API keys / webhook URLs / tokens never get here.
  import { untrack } from 'svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago, bytes } from '$lab/fmt.js';
  import { act, ts } from '$lab/sdk.js';
  import PermEdit from './PermEdit.svelte';
  let { data, ctx } = $props();

  let s = $state(null);
  let err = $state('');
  let main = $state({});
  let acc = $state({});
  let srv = $state({});   // "radarr:0" -> {form, opts}
  let busy = $state(false);

  const MAIN_TEXT = [['applicationTitle', 'title'], ['applicationUrl', 'public URL'], ['locale', 'language'], ['discoverRegion', 'discover region'],
    ['streamingRegion', 'streaming region'], ['originalLanguage', 'original language filter'], ['youtubeUrl', 'YouTube URL']];
  const MAIN_BOOL = [['partialRequestsEnabled', 'allow partial series requests'], ['enableSpecialEpisodes', 'allow specials'],
    ['hideAvailable', 'hide available media'], ['hideBlocklisted', 'hide blocklisted'], ['cacheImages', 'cache images'], ['versionCheck', 'check for updates']];

  async function load(reset = false) {
    try {
      s = await ctx.api.get('/api/settings');
      err = '';
      if (reset || !Object.keys(main).length) {
        main = Object.fromEntries([...MAIN_TEXT, ...MAIN_BOOL].map(([k]) => [k, s.main[k] ?? (MAIN_BOOL.some(([b]) => b === k) ? false : '')]));
        acc = { localLogin: s.main.localLogin, mediaServerLogin: s.main.mediaServerLogin, defaultPermissions: s.main.defaultPermissions,
          mq: s.main.defaultQuotas?.movie?.quotaLimit ?? '', md: s.main.defaultQuotas?.movie?.quotaDays ?? '',
          tq: s.main.defaultQuotas?.tv?.quotaLimit ?? '', td: s.main.defaultQuotas?.tv?.quotaDays ?? '' };
      }
      for (const app of ['radarr', 'sonarr']) {
        for (const x of s[app]) {
          const k = `${app}:${x.id}`;
          if (!srv[k] || reset) {
            srv[k] = { form: { activeProfileId: x.activeProfileId, activeDirectory: x.activeDirectory, isDefault: x.isDefault, syncEnabled: x.syncEnabled,
              preventSearch: x.preventSearch, tagRequests: x.tagRequests, externalUrl: x.externalUrl || '',
              ...(app === 'radarr' ? { minimumAvailability: x.minimumAvailability } : { activeAnimeProfileId: x.activeAnimeProfileId,
                activeAnimeDirectory: x.activeAnimeDirectory, enableSeasonFolders: x.enableSeasonFolders }) }, opts: srv[k]?.opts || null };
            if (!srv[k].opts) ctx.api.get(`/api/settings/${app}/${x.id}/options`).then((o) => (srv[k].opts = o)).catch(() => {});
          }
        }
      }
    } catch (e) { err = e.body?.error || e.message; }
  }
  $effect(() => { untrack(() => load()); });
  // follow the jellyfin sync + running jobs while something runs
  $effect(() => { data?.at; untrack(() => { if (s && (s.jellyfin.sync.running || s.jobs.some((j) => j.running))) load(); }); });

  async function run(method, path, body, label, c) {
    busy = true;
    const r = await act(ctx, { method, path, body, label, confirm: c });
    busy = false;
    if (r) await load(true);
    return r;
  }
  function diff(obj, cur) {
    return Object.fromEntries(Object.entries(obj).filter(([k, v]) => v !== (cur[k] ?? (typeof v === 'boolean' ? false : ''))));
  }
  const mainDiff = $derived(s ? diff(main, s.main) : {});
  function saveAccess() {
    const n = (v) => (v === '' || v == null ? null : Number(v));
    const body = { localLogin: acc.localLogin, mediaServerLogin: acc.mediaServerLogin, defaultPermissions: acc.defaultPermissions,
      defaultQuotas: { movie: { quotaLimit: n(acc.mq), quotaDays: n(acc.md) }, tv: { quotaLimit: n(acc.tq), quotaDays: n(acc.td) } } };
    run('POST', '/api/settings/main/access', body, 'seerr: login methods / default permissions + quotas',
      !acc.mediaServerLogin && !acc.localLogin ? 'Turn off BOTH login methods? Nobody can sign in to Seerr then.' : null);
  }
  function saveServer(app, x) {
    const f = srv[`${app}:${x.id}`].form;
    const body = Object.fromEntries(Object.entries(f).filter(([k, v]) => v !== (x[k] ?? (typeof v === 'boolean' ? false : '')) && v !== undefined)
      .map(([k, v]) => [k, /ProfileId$/.test(k) ? Number(v) : v]));
    if (!Object.keys(body).length) return ctx.notify('nothing changed');
    run('POST', `/api/settings/${app}/${x.id}`, body, `seerr: ${x.name} defaults (${Object.keys(body).join(', ')})`);
  }
  const at = (iso) => (iso ? new Date(iso).toLocaleString('nb-NO', { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : '–');
  const ownerAccess = $derived(ctx.can('POST', '/api/settings/main/access'));
</script>

{#if err}<p class="mono bad pad">■ {err}</p>
{:else if !s}<p class="mono dim pad spin">loading seerr settings </p>
{:else}
<div class="sv fade">
  <section>
    <div class="hd"><span class="cap">~/seerr · about</span></div>
    <div class="kv mono s">
      <span>version</span><span>{s.about.version}{#if s.about.updateAvailable}<span class="warn"> ▲ update available ({s.about.commitsBehind} behind)</span>{:else}<span class="ok"> ● current</span>{/if}{#if s.about.restartRequired}<span class="warn"> · restart needed</span>{/if}</span>
      <span>media</span><span>{s.about.media} items · {s.about.requests} requests</span>
      <span>jellyfin</span><span>{s.jellyfin.name} · {s.jellyfin.host} · {s.jellyfin.external || '–'}</span>
    </div>
  </section>

  <section>
    <div class="hd"><span class="cap">general</span>
      <button class="btn" class:primary={Object.keys(mainDiff).length} disabled={!Object.keys(mainDiff).length || busy || ctx.can('POST', '/api/settings/main') === 'no'}
        onclick={() => run('POST', '/api/settings/main', mainDiff, `seerr: general settings (${Object.keys(mainDiff).join(', ')})`)}>apply {Object.keys(mainDiff).length || ''}</button></div>
    <div class="form">
      {#each MAIN_TEXT as [k, label] (k)}<label class="mono s"><span>{label}</span><input class="field" bind:value={main[k]} aria-label={label} /></label>{/each}
      {#each MAIN_BOOL as [k, label] (k)}<label class="mono s chk"><input type="checkbox" bind:checked={main[k]} /> {label}</label>{/each}
    </div>
  </section>

  {#if ownerAccess !== 'no'}
    <section>
      <div class="hd"><span class="cap">access · owner</span>
        <button class="btn" disabled={busy} onclick={saveAccess}>{#if ownerAccess === 'ask'}<Icon name="lock" size={11} />ask owner to apply{:else}apply{/if}</button></div>
      <div class="form">
        <label class="mono s chk"><input type="checkbox" bind:checked={acc.mediaServerLogin} /> Jellyfin login</label>
        <label class="mono s chk"><input type="checkbox" bind:checked={acc.localLogin} /> local (e-mail) login</label>
        <span class="mono s q">default quota · movies <input class="field n" type="number" min="0" placeholder="∞" bind:value={acc.mq} aria-label="Default movie limit" /> per <input class="field n" type="number" min="0" placeholder="–" bind:value={acc.md} aria-label="Default movie days" />d
          · series <input class="field n" type="number" min="0" placeholder="∞" bind:value={acc.tq} aria-label="Default series limit" /> per <input class="field n" type="number" min="0" placeholder="–" bind:value={acc.td} aria-label="Default series days" />d</span>
      </div>
      <span class="cap">default permissions for new users</span>
      <PermEdit bind:value={acc.defaultPermissions} perms={s.perms} identity={false} />
    </section>
  {/if}

  <section>
    <div class="hd"><span class="cap">jellyfin libraries</span>
      <span class="btns">
        <button class="btn" disabled={busy} onclick={() => run('POST', '/api/settings/jellyfin/libraries/refresh', {}, 'seerr: reload Jellyfin library list')}><Icon name="restart" size={11} />reload list</button>
        {#if s.jellyfin.sync.running}<button class="btn" onclick={() => run('POST', '/api/settings/jellyfin/sync/cancel', {}, 'seerr: cancel Jellyfin sync')}><Icon name="close" size={11} />cancel sync</button>
        {:else}<button class="btn" disabled={busy} onclick={() => run('POST', '/api/settings/jellyfin/sync/start', {}, 'seerr: full Jellyfin sync')}><Icon name="download" size={11} />full sync now</button>{/if}
      </span></div>
    {#if s.jellyfin.sync.running}<span class="mono sig s spin">syncing {s.jellyfin.sync.library || ''} {s.jellyfin.sync.progress}/{s.jellyfin.sync.total} </span>{/if}
    <div class="libs">
      {#each s.jellyfin.libraries as l (l.id)}
        <label class="mono s chk"><input type="checkbox" checked={l.enabled} disabled={busy}
          onchange={(e) => run('POST', `/api/settings/jellyfin/libraries/${l.id}`, { enabled: e.currentTarget.checked }, `seerr: ${e.currentTarget.checked ? 'enable' : 'disable'} library ${l.name}`)} /> {l.name} <span class="dim">{l.type}</span></label>
      {:else}<span class="mono dim s">no libraries — reload the list</span>{/each}
    </div>
  </section>

  {#each ['radarr', 'sonarr'] as app (app)}
    <section>
      <div class="hd"><span class="cap">{app}</span>{#if ctx.object(app)}<button class="lnk mono s" onclick={() => ctx.open(app)}>{app} object →</button>{/if}</div>
      {#each s[app] as x (x.id)}
        {@const st = srv[`${app}:${x.id}`]}
        <div class="srv">
          <span class="mono s"><Glyph status="ok" size={9} /> {x.name}{x.is4k ? ' · 4K' : ''}{x.isDefault ? ' · default' : ''} · {x.hostname}:{x.port}{x.baseUrl || ''} · <span class="dim">API key stored in Seerr</span></span>
          {#if st}
            <div class="form">
              <label class="mono s"><span>profile</span><select bind:value={st.form.activeProfileId} aria-label="{x.name} quality profile">
                {#each st.opts?.profiles || [{ id: x.activeProfileId, name: x.activeProfileName }] as p (p.id)}<option value={p.id}>{p.name}</option>{/each}</select></label>
              <label class="mono s"><span>root folder</span><select bind:value={st.form.activeDirectory} aria-label="{x.name} root folder">
                {#each st.opts?.roots || [{ path: x.activeDirectory }] as r (r.path)}<option value={r.path}>{r.path}{r.free ? ` · ${bytes(r.free)} free` : ''}</option>{/each}</select></label>
              {#if app === 'radarr'}
                <label class="mono s"><span>available from</span><select bind:value={st.form.minimumAvailability} aria-label="Minimum availability">
                  {#each ['announced', 'inCinemas', 'released'] as v (v)}<option value={v}>{v}</option>{/each}</select></label>
              {:else}
                <label class="mono s"><span>anime profile</span><select bind:value={st.form.activeAnimeProfileId} aria-label="Anime profile">
                  {#each st.opts?.profiles || [{ id: x.activeAnimeProfileId, name: x.activeAnimeProfileName }] as p (p.id)}<option value={p.id}>{p.name}</option>{/each}</select></label>
                <label class="mono s"><span>anime root</span><select bind:value={st.form.activeAnimeDirectory} aria-label="Anime root folder">
                  {#each st.opts?.roots || [{ path: x.activeAnimeDirectory }] as r (r.path)}<option value={r.path}>{r.path}</option>{/each}</select></label>
                <label class="mono s chk"><input type="checkbox" bind:checked={st.form.enableSeasonFolders} /> season folders</label>
              {/if}
              <label class="mono s"><span>external URL</span><input class="field" bind:value={st.form.externalUrl} aria-label="External URL" /></label>
              <label class="mono s chk"><input type="checkbox" bind:checked={st.form.isDefault} /> default server</label>
              <label class="mono s chk"><input type="checkbox" bind:checked={st.form.syncEnabled} /> scan (sync) enabled</label>
              <label class="mono s chk"><input type="checkbox" bind:checked={st.form.preventSearch} /> don't search on add</label>
              <label class="mono s chk"><input type="checkbox" bind:checked={st.form.tagRequests} /> tag requests with user</label>
            </div>
            <span class="btns">
              <button class="btn" disabled={busy || ctx.can('POST', `/api/settings/${app}/${x.id}`) === 'no'} onclick={() => saveServer(app, x)}>apply</button>
              <button class="btn" disabled={busy} onclick={async () => { const r = await run('POST', `/api/settings/${app}/${x.id}/test`, {}, `seerr: test ${x.name}`); if (r?.ok) ctx.notify(`${x.name}: reachable · ${r.profiles} profiles · ${r.roots} root folders`); }}><Icon name="check" size={11} />test</button>
            </span>
          {/if}
        </div>
      {:else}<span class="mono dim s">no {app} server in Seerr</span>{/each}
    </section>
  {/each}

  <section>
    <div class="hd"><span class="cap">notifications</span></div>
    <div class="tbl">
      {#each s.notifications as n (n.agent)}
        <Glyph status={n.enabled ? 'ok' : 'off'} size={10} />
        <span class="mono s">{n.agent}</span>
        <span class="mono dim s ell">{n.agent === 'webpush' ? 'browser push' : n.configured ? 'configured' : 'not configured (set it up in Seerr: it holds credentials)'}</span>
        <label class="mono s chk"><input type="checkbox" checked={n.enabled} disabled={busy || (!n.configured && !n.enabled)}
          onchange={(e) => run('POST', `/api/settings/notifications/${n.agent}/enabled`, { enabled: e.currentTarget.checked }, `seerr: ${n.agent} notifications ${e.currentTarget.checked ? 'on' : 'off'}`)} /> on</label>
        <button class="btn x" disabled={busy || !n.enabled} title="send a test" aria-label="test {n.agent}" onclick={() => run('POST', `/api/settings/notifications/${n.agent}/test`, {}, `seerr: test ${n.agent} notification`)}><Icon name="bell" size={11} /></button>
      {/each}
    </div>
  </section>

  <section>
    <div class="hd"><span class="cap">jobs</span></div>
    <div class="tbl jobs">
      {#each s.jobs as j (j.id)}
        <Glyph status={j.running ? 'ok' : 'off'} size={10} />
        <span class="s">{j.name}</span>
        <span class="mono dim s">{j.cronSchedule}</span>
        <span class="mono dim s">{j.running ? 'running' : `next ${at(j.nextExecutionTime)}`}</span>
        {#if j.running}<button class="btn x" title="cancel" aria-label="cancel {j.name}" onclick={() => run('POST', `/api/jobs/${j.id}/cancel`, {}, `seerr: cancel ${j.name}`)}><Icon name="close" size={11} /></button>
        {:else}<button class="btn x" title="run now" aria-label="run {j.name} now" disabled={busy} onclick={() => run('POST', `/api/jobs/${j.id}/run`, {}, `seerr: run ${j.name}`)}><Icon name="play" size={11} /></button>{/if}
      {/each}
    </div>
  </section>

  <section>
    <div class="hd"><span class="cap">caches</span></div>
    <div class="tbl caches">
      {#each s.caches as c (c.id)}
        <span class="s">{c.name}</span>
        <span class="mono dim s">{c.keys ?? 0} keys · {c.hits ?? 0} hits · {c.misses ?? 0} misses</span>
        <button class="btn x" title="flush" aria-label="flush {c.name}" disabled={busy || !c.keys} onclick={() => run('POST', `/api/cache/${c.id}/flush`, {}, `seerr: flush ${c.name} cache`)}><Icon name="restart" size={11} /></button>
      {/each}
    </div>
  </section>
</div>
{/if}

<style>
  .sv { padding: 4px 16px 16px; display: flex; flex-direction: column; }
  section { padding: 12px 0; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px; }
  .hd { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
  .btns { display: flex; gap: 6px; flex-wrap: wrap; }
  .s { font-size: 11.5px; }
  .kv { display: grid; grid-template-columns: max-content 1fr; gap: 3px 14px; }
  .kv > span:nth-child(odd) { color: var(--dim); }
  .form { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 6px 16px; align-items: center; }
  .form label { display: flex; flex-direction: column; gap: 2px; }
  .form label > span { color: var(--dim); font-size: 10.5px; }
  .form .field, select { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 7px; font: 11.5px "Geist Mono Variable", monospace; width: 100%; }
  label.chk { flex-direction: row; align-items: center; gap: 6px; }
  .q { grid-column: 1 / -1; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .n { width: 60px !important; padding: 3px 5px; }
  .libs { display: flex; gap: 6px 18px; flex-wrap: wrap; }
  .srv { display: flex; flex-direction: column; gap: 8px; padding: 6px 0; }
  .tbl { display: grid; grid-template-columns: 12px auto minmax(0, 1fr) auto auto; gap: 5px 12px; align-items: center; }
  .jobs { grid-template-columns: 12px minmax(0, 1fr) auto auto auto; }
  .caches { grid-template-columns: minmax(0, 1fr) auto auto; }
  .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .x { padding: 3px 6px; }
  .pad { padding: 12px 16px; }
  @media (max-width: 520px) {
    .jobs { grid-template-columns: 12px minmax(0, 1fr) auto; }
    .jobs > :nth-child(5n + 3) { display: none; }
    .jobs > :nth-child(5n + 4) { display: none; }
    .tbl:not(.jobs):not(.caches) { grid-template-columns: 12px auto minmax(0, 1fr) auto auto; }
  }
</style>
