<script>
  // One movie / series: what it is, where it stands, and the request form. Guests request as themselves (the connector
  // drops anything else); admins may pick the person, server, quality profile and root folder.
  import { untrack } from 'svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago, safeUrl } from '$lab/fmt.js';
  import { act, ts } from '$lab/sdk.js';
  import Poster from './Poster.svelte';
  import { mediaState } from './sr.js';
  let { type, tmdb, ctx, data, onclose } = $props();

  let d = $state(null);
  let err = $state('');
  let picked = $state([]);
  let k4 = $state(false);
  let adv = $state(false);
  let opts = $state(null);
  let f = $state({ userId: null, serverId: null, profileId: null, rootFolder: null });
  let busy = $state(false);
  const admin = $derived(ctx.role !== 'guest');
  const me = $derived(data?.me || {});

  async function load() {
    err = '';
    try {
      d = await ctx.api.get(`/api/${type}/${tmdb}`);
      picked = (d.seasons || []).filter((s) => free(s)).map((s) => s.n);
    } catch (e) { err = e.body?.error || e.message; }
  }
  $effect(() => { if (type && tmdb) untrack(() => { d = null; adv = false; load(); }); });

  // a season can be requested unless it is in the library or already asked for
  const taken = $derived(new Set((d?.media?.requests || []).filter((r) => !['declined', 'failed'].includes(r.status) && r.is4k === k4).flatMap((r) => r.seasons)));
  const free = (s) => !['available', 'partial', 'processing', 'pending'].includes(s.status) && !taken.has(s.n);
  const st = $derived(mediaState(k4 ? d?.media?.status4k : d?.media?.status));
  const servers = $derived(opts ? opts[type === 'tv' ? 'sonarr' : 'radarr'].filter((s) => s.is4k === k4) : []);
  const server = $derived(servers.find((s) => s.id === f.serverId) || servers.find((s) => s.isDefault) || servers[0]);
  const canRequest = $derived(d && (type === 'movie' ? !['available', 'processing', 'pending'].includes(k4 ? d.media.status4k : d.media.status) : picked.length > 0));

  async function openAdv() {
    adv = !adv;
    if (adv && !opts) {
      try { opts = await ctx.api.get('/api/request-options'); } catch (e) { ctx.notify(e.message, 'bad'); adv = false; return; }
    }
    if (adv) f = { userId: f.userId ?? me.id ?? opts.users[0]?.id ?? null, serverId: server?.id ?? null, profileId: server?.profile ?? null, rootFolder: server?.root ?? null };
  }

  async function request() {
    const body = { type, tmdb };
    if (type === 'tv') { body.seasons = picked; if (d.tvdb) body.tvdb = d.tvdb; }
    if (k4) body.is4k = true;
    if (admin && adv) {
      for (const k of ['userId', 'serverId', 'profileId']) if (f[k] != null && f[k] !== '') body[k] = Number(f[k]);
      if (f.rootFolder) body.rootFolder = f.rootFolder;
    } else if (admin && !me.linked) {
      return ctx.notify('you have no Seerr account: open "advanced" and pick who it is for', 'bad');
    }
    busy = true;
    const r = await act(ctx, { path: '/api/requests', body, label: `seerr: request ${d.title}${type === 'tv' ? ` S${picked.join(',')}` : ''}` });
    busy = false;
    if (r) load();
  }
</script>

<div class="dt fade">
  {#if err}<p class="mono bad">■ {err}</p>
  {:else if !d}<p class="mono dim spin">loading </p>
  {:else}
    <div class="top">
      <Poster src={d.poster} alt="" kind={type} w={92} />
      <div class="info">
        <div class="h">
          <span class="t">{d.title}{d.year ? ` (${d.year})` : ''}</span>
          <button class="btn x" aria-label="close" onclick={onclose}><Icon name="close" size={11} /></button>
        </div>
        <span class="mono dim s">{type === 'tv' ? 'series' : 'movie'}{d.genres.length ? ` · ${d.genres.join(', ')}` : ''}{d.runtime ? ` · ${d.runtime}m` : ''}{d.rating ? ` · ★${d.rating}` : ''}{d.network ? ` · ${d.network}` : ''}</span>
        <span class="mono s state">{#if st.t}<Glyph status={st.s} size={10} /> {st.t}{:else}<span class="dim">not in the library</span>{/if}</span>
        <span class="links mono s">
          {#if d.media.jellyfin}<a href={safeUrl(d.media.jellyfin)} target="_blank" rel="noopener">jellyfin ↗</a>{/if}
          <a href={safeUrl(d.seerr)} target="_blank" rel="noopener">seerr ↗</a>
          {#if d.media.service}<a href={safeUrl(d.media.service)} target="_blank" rel="noopener">{type === 'tv' ? 'sonarr' : 'radarr'} ↗</a>{/if}
          {#if admin && ctx.object(d.object)}<button class="lnk" onclick={() => ctx.open(d.object)}>object →</button>{/if}
        </span>
      </div>
    </div>
    {#if d.overview}<p class="ov">{d.overview}</p>{/if}

    {#if d.media.requests.length}
      <div class="reqs">
        <span class="cap">{admin ? 'requests' : 'your requests'}</span>
        {#each d.media.requests as r (r.id)}
          <span class="mono s">{r.status === 'pending' ? '▲' : r.status === 'failed' ? '■' : r.status === 'declined' ? '○' : '●'} #{r.id} {r.status}{r.is4k ? ' · 4K' : ''}{r.seasons.length ? ` · S${r.seasons.join(',')}` : ''} · {r.by} · {ago(ts(r.created), ctx.now)} ago</span>
        {/each}
      </div>
    {/if}
    {#if d.media.downloads.length}<span class="mono dim s">↓ {d.media.downloads.length} download(s) running</span>{/if}

    {#if ctx.can('POST', '/api/requests') !== 'no'}
      <div class="form">
        {#if type === 'tv' && d.seasons?.length}
          <div class="seas">
            <label class="mono s all"><input type="checkbox" checked={picked.length === d.seasons.filter(free).length && picked.length > 0}
              onchange={(e) => (picked = e.currentTarget.checked ? d.seasons.filter(free).map((s) => s.n) : [])} /> all free</label>
            {#each d.seasons as s (s.n)}
              <label class="mono s" title={s.name}>
                <input type="checkbox" value={s.n} bind:group={picked} disabled={!free(s)} />
                S{s.n}<span class="dim"> {s.episodes}ep</span>{#if !free(s)}<span class="sig"> {mediaState(s.status).t || 'requested'}</span>{/if}
              </label>
            {/each}
          </div>
        {/if}
        <div class="row">
          {#if d.can4k}<label class="mono s"><input type="checkbox" bind:checked={k4} /> 4K</label>{/if}
          {#if admin}<button class="btn" aria-expanded={adv} onclick={openAdv}><Icon name="wrench" size={11} />advanced</button>{/if}
          <button class="btn primary" disabled={!canRequest || busy} onclick={request}><Icon name="download" size={12} />request{type === 'tv' && picked.length ? ` ${picked.length} season${picked.length > 1 ? 's' : ''}` : ''}</button>
        </div>
        {#if adv && opts}
          <div class="adv">
            <label class="mono s">for <select bind:value={f.userId} aria-label="Request for">
              {#each opts.users as u (u.id)}<option value={u.id}>{u.name}{u.id === me.id ? ' (you)' : ''}</option>{/each}</select></label>
            {#if servers.length}
              <label class="mono s">server <select bind:value={f.serverId} aria-label="Server">{#each servers as s (s.id)}<option value={s.id}>{s.name}</option>{/each}</select></label>
              <label class="mono s">profile <select bind:value={f.profileId} aria-label="Quality profile">{#each server?.profiles || [] as p (p.id)}<option value={p.id}>{p.name}</option>{/each}</select></label>
              <label class="mono s">root <select bind:value={f.rootFolder} aria-label="Root folder">{#each server?.roots || [] as r (r.path)}<option value={r.path}>{r.path}</option>{/each}</select></label>
            {:else}<span class="mono dim s">no {k4 ? '4K ' : ''}{type === 'tv' ? 'Sonarr' : 'Radarr'} server</span>{/if}
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .dt { display: flex; flex-direction: column; gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 4px; background: var(--panel); }
  .top { display: flex; gap: 12px; }
  .info { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
  .h { display: flex; justify-content: space-between; gap: 8px; align-items: start; }
  .t { font-size: 15px; font-weight: 500; }
  .s { font-size: 11px; }
  .state { display: flex; gap: 4px; align-items: center; }
  .links { display: flex; gap: 10px; flex-wrap: wrap; }
  .ov { margin: 0; font-size: 12.5px; color: var(--dim); display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
  .reqs { display: flex; flex-direction: column; gap: 2px; }
  .form { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--line); padding-top: 10px; }
  .seas { display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .seas label { display: flex; gap: 4px; align-items: center; }
  .all { width: 100%; }
  .row, .adv { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .adv label { display: flex; gap: 6px; align-items: center; }
  select { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 4px 6px; font-size: 11.5px; max-width: 200px; }
  .x { padding: 3px 6px; }
</style>
