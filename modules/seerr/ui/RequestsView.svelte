<script>
  // ~/seerr-requests — every request with filters (admins) or your own (guests: the connector forces it).
  // Admins: approve / decline (also in bulk), retry, edit (seasons, server, profile, root, person), delete.
  // Guests: cancel their own pending requests.
  import { untrack } from 'svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Bar from '$lab/Bar.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago, safeUrl } from '$lab/fmt.js';
  import { act, ts } from '$lab/sdk.js';
  import Poster from './Poster.svelte';
  import { stateOf, progress, name, seasons } from './sr.js';
  let { data, ctx } = $props();

  const FILTERS = ['all', 'pending', 'approved', 'processing', 'available', 'failed'];
  let filter = $state('all');
  let by = $state('');
  let type = $state('');
  let rows = $state([]);
  let total = $state(0);
  let loading = $state(false);
  let err = $state('');
  let picked = $state([]);
  let edit = $state(null);   // {id, seasons, serverId, profileId, rootFolder, userId}
  let opts = $state(null);
  const admin = $derived(ctx.role !== 'guest');
  const blocked = $derived(data && !data.me?.linked && !admin);

  async function load(more = false) {
    loading = true;
    err = '';
    try {
      const q = { filter, take: 30, skip: more ? rows.length : 0, sort: 'added' };
      if (by) q.by = by;
      if (type) q.type = type;
      const r = await ctx.api.get('/api/requests', q);
      rows = more ? [...rows, ...r.results] : r.results;
      total = r.total;
      picked = picked.filter((id) => rows.some((x) => x.id === id && x.status === 'pending'));
    } catch (e) { err = e.body?.error || e.message; }
    loading = false;
  }
  $effect(() => { filter; by; type; if (!blocked) untrack(() => load()); });
  // follow the shell's 15 s refresh (cheap: one page)
  $effect(() => { data?.at; untrack(() => { if (!loading && !edit && rows.length && !blocked) load(); }); });

  async function run(method, path, body, label, confirmText) {
    const r = await act(ctx, { method, path, body, label, confirm: confirmText });
    if (r) load();
    return r;
  }
  const verb = (r, v, c) => run('POST', `/api/requests/${r.id}/${v}`, {}, `seerr: ${v} ${name(r)}`, c);
  async function bulk(v) {
    if (!picked.length) return;
    const n = picked.length;
    const r = await run('POST', '/api/requests/bulk', { verb: v, ids: picked }, `seerr: ${v} ${n} request${n > 1 ? 's' : ''}`,
      v === 'decline' ? `Decline ${n} request${n > 1 ? 's' : ''}?` : null);
    if (r) { picked = []; if (r.failed?.length) ctx.notify(`${r.failed.length} failed: ${r.failed[0].error}`, 'bad'); }
  }
  async function startEdit(r) {
    if (edit?.id === r.id) { edit = null; return; }
    if (!opts) { try { opts = await ctx.api.get('/api/request-options'); } catch (e) { return ctx.notify(e.message, 'bad'); } }
    edit = { id: r.id, type: r.type, seasons: (r.seasons || []).map((s) => s.n), serverId: r.serverId, profileId: r.profileId, rootFolder: r.rootFolder,
      userId: r.byId, allSeasons: '' };
  }
  const srv = $derived(edit && opts ? (opts[edit.type === 'tv' ? 'sonarr' : 'radarr'] || []) : []);
  const curSrv = $derived(srv.find((s) => s.id === Number(edit?.serverId)) || srv[0]);
  async function saveEdit(r) {
    const body = { serverId: Number(edit.serverId), profileId: Number(edit.profileId), rootFolder: edit.rootFolder, userId: Number(edit.userId) };
    if (r.type === 'tv') {
      body.seasons = String(edit.allSeasons || edit.seasons.join(',')).split(/[\s,]+/).filter(Boolean).map(Number).filter((n) => Number.isInteger(n) && n >= 0);
      if (!body.seasons.length) return ctx.notify('at least one season', 'bad');
    }
    if (await run('PUT', `/api/requests/${r.id}`, body, `seerr: edit request ${name(r)}`)) edit = null;
  }
  const canCancel = (r) => admin || (r.status === 'pending' && r.byId === data?.me?.id);
</script>

<div class="rv fade">
  <div class="bar">
    <span class="cap">~/seerr-requests{admin ? '' : ' · yours'} · {total}</span>
    <div class="seg" role="group" aria-label="Filter">
      {#each FILTERS as f (f)}<button aria-pressed={filter === f} onclick={() => (filter = f)}>{f}{f === 'pending' && data?.counts?.pending ? ` ${data.counts.pending}` : ''}</button>{/each}
    </div>
    <select bind:value={type} aria-label="Type"><option value="">movies + tv</option><option value="movie">movies</option><option value="tv">series</option></select>
    {#if admin && data?.users}
      <select bind:value={by} aria-label="Requested by"><option value="">everyone</option>{#each data.users as u (u.id)}<option value={String(u.id)}>{u.name} · {u.requests}</option>{/each}</select>
    {/if}
  </div>
  {#if admin && ctx.can('POST', '/api/requests/bulk') !== 'no'}
    {@const pend = rows.filter((r) => r.status === 'pending')}
    <div class="bulk mono s">
      <label><input type="checkbox" checked={pend.length > 0 && picked.length === pend.length} disabled={!pend.length}
        onchange={(e) => (picked = e.currentTarget.checked ? pend.map((r) => r.id) : [])} /> {picked.length ? `${picked.length} selected` : 'select pending'}</label>
      <button class="btn" disabled={!picked.length} onclick={() => bulk('approve')}><Icon name="check" size={11} />approve</button>
      <button class="btn" disabled={!picked.length} onclick={() => bulk('decline')}><Icon name="close" size={11} />decline</button>
    </div>
  {/if}
  {#if blocked}<p class="mono dim">○ no Seerr account is linked to you yet — ask owner.</p>{/if}
  {#if err}<p class="mono bad">■ {err}</p>{/if}

  <div class="list">
    {#each rows as r (r.id)}
      {@const st = stateOf(r)}
      {@const dl = progress(r)}
      <div class="r" class:g={!admin}>
        {#if admin}<input type="checkbox" value={r.id} bind:group={picked} disabled={r.status !== 'pending'} aria-label="select {name(r)}" />{/if}
        <Poster src={r.poster} kind={r.type} w={34} />
        <div class="m">
          <span class="t">
            <button class="lnk tt" onclick={() => ctx.open(r.object)} title="open">{name(r)}</button>{#if seasons(r)}<span class="mono dim"> {seasons(r)}</span>{/if}{#if r.is4k}<span class="mono sig"> 4K</span>{/if}
          </span>
          <span class="mono dim sub"><Glyph status={st.s} size={9} /> {st.t} · {r.type === 'tv' ? 'series' : 'movie'}{r.by ? ` · ${r.by}` : ''} · {ago(ts(r.created), ctx.now)} ago{r.modifiedBy && r.modifiedBy !== r.by ? ` · by ${r.modifiedBy}` : ''}</span>
          {#if dl?.pct != null}<Bar value={dl.pct} color="var(--sig)" height={3} label="{dl.pct}% of {dl.n} download(s)" />{/if}
        </div>
        <span class="acts">
          {#if admin && r.status === 'pending'}
            <button class="btn x" title="approve" aria-label="approve {name(r)}" onclick={() => verb(r, 'approve')}><Icon name="check" size={11} /></button>
            <button class="btn x" title="decline" aria-label="decline {name(r)}" onclick={() => verb(r, 'decline', `Decline ${name(r)} requested by ${r.by}?`)}><Icon name="close" size={11} /></button>
          {:else if admin && r.status === 'failed'}
            <button class="btn x" title="retry" aria-label="retry {name(r)}" onclick={() => verb(r, 'retry')}><Icon name="restart" size={11} /></button>
          {/if}
          {#if admin}<button class="btn x" title="edit" aria-expanded={edit?.id === r.id} aria-label="edit {name(r)}" onclick={() => startEdit(r)}><Icon name="wrench" size={11} /></button>{/if}
          <a class="btn x" href={safeUrl(r.url)} target="_blank" rel="noopener" title="open in {r.media === 'available' || r.media === 'partial' ? 'Jellyfin' : 'Seerr'}" aria-label="open {name(r)}"><Icon name="ext" size={11} /></a>
          {#if canCancel(r)}
            <button class="btn x" title={admin ? 'delete request' : 'cancel request'} aria-label="{admin ? 'delete' : 'cancel'} {name(r)}"
              onclick={() => run('DELETE', `/api/requests/${r.id}`, undefined, `seerr: ${admin ? 'delete' : 'cancel'} request ${name(r)}`,
                admin ? `Delete the request for ${name(r)} (${r.by})? The media stays in Sonarr/Radarr; use "clear media data" / "delete files" on the object for that.` : `Cancel your request for ${name(r)}?`)}>
              <Icon name="close" size={11} /><span class="mono s">{admin ? 'del' : 'cancel'}</span></button>
          {/if}
        </span>
        {#if edit?.id === r.id}
          <div class="edit mono s">
            {#if r.type === 'tv'}<label>seasons <input class="field n" value={edit.seasons.join(',')} oninput={(e) => (edit.allSeasons = e.currentTarget.value)} aria-label="Seasons (comma separated)" /></label>{/if}
            <label>for <select bind:value={edit.userId} aria-label="Requested by">{#each opts.users as u (u.id)}<option value={u.id}>{u.name}</option>{/each}</select></label>
            <label>server <select bind:value={edit.serverId} aria-label="Server">{#each srv as s (s.id)}<option value={s.id}>{s.name}{s.is4k ? ' 4K' : ''}</option>{/each}</select></label>
            <label>profile <select bind:value={edit.profileId} aria-label="Profile">{#each curSrv?.profiles || [] as p (p.id)}<option value={p.id}>{p.name}</option>{/each}</select></label>
            <label>root <select bind:value={edit.rootFolder} aria-label="Root folder">{#each curSrv?.roots || [] as f (f.path)}<option value={f.path}>{f.path}</option>{/each}</select></label>
            <button class="btn primary" onclick={() => saveEdit(r)}>save</button>
            <span class="dim">approved requests are already in {r.type === 'tv' ? 'Sonarr' : 'Radarr'}: an edit changes Seerr's record only</span>
          </div>
        {/if}
      </div>
    {:else}
      {#if !loading && !blocked}<span class="mono dim s">no requests{filter !== 'all' ? ` (${filter})` : ''}</span>{/if}
    {/each}
  </div>
  {#if loading && !rows.length}<p class="mono dim spin">loading </p>
  {:else if rows.length < total}<button class="btn more" onclick={() => load(true)}>more ({total - rows.length})</button>{/if}
</div>

<style>
  .rv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 10px; }
  .bar, .bulk { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .bulk label { display: flex; gap: 6px; align-items: center; }
  .seg { flex-wrap: wrap; }
  select { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 6px; font: 11.5px "Geist Mono Variable", monospace; max-width: 180px; }
  .s { font-size: 11px; }
  .list { display: flex; flex-direction: column; }
  .r { display: grid; grid-template-columns: auto 34px minmax(0, 1fr) auto; gap: 4px 10px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--q); }
  .r.g { grid-template-columns: 34px minmax(0, 1fr) auto; }
  .m { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12.5px; }
  .tt { font-size: 12.5px; }
  .sub { font-size: 10.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .acts { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
  .x { padding: 3px 6px; text-decoration: none; }
  .edit { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding: 6px 0 4px 44px; }
  .edit label { display: flex; gap: 6px; align-items: center; }
  .n { width: 110px; padding: 4px 6px; }
  .more { align-self: center; }
  @media (max-width: 520px) {
    .r { grid-template-columns: auto 28px minmax(0, 1fr); }
    .r.g { grid-template-columns: 28px minmax(0, 1fr); }
    .acts { grid-column: 2 / -1; justify-content: flex-start; }
    .edit { padding-left: 0; }
  }
</style>
