<script>
  // Facet on a jellyfin-item object: what it is (metadata, file, size, streams), edit the basics, identify (remote search +
  // apply), refresh, delete. Reads: admin. Writes: admin; delete removes the files too.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Icon from '$lab/Icon.svelte';
  import { bytes, ago, safeUrl } from '$lab/fmt.js';
  import { act } from '$lab/sdk.js';
  import { label, runtime } from './jf.js';
  import { lazy, qs, errText } from '$lab/sdk.js';
  import { remember, opened, IID } from './store.svelte.js';
  import RefreshOpts from './RefreshOpts.svelte';
  let { object, ctx } = $props();

  const FIELDS = 'Path,MediaSources,MediaStreams,ProviderIds,Overview,Genres,Tags,Studios,People,DateCreated,OriginalTitle,Taglines,ExternalUrls,SortName,CustomRating,DateLastRefreshed,ParentId,RecursiveItemCount,ChildCount,AirTime';
  // the fields Jellyfin's UpdateItem reads (the same set its own metadata editor sends); the manifest's body_keys
  const EDIT = ['Id', 'Name', 'OriginalTitle', 'ForcedSortName', 'CommunityRating', 'CriticRating', 'IndexNumber', 'AirsBeforeSeasonNumber', 'AirsAfterSeasonNumber',
    'AirsBeforeEpisodeNumber', 'ParentIndexNumber', 'DisplayOrder', 'Album', 'AlbumArtists', 'ArtistItems', 'Overview', 'Status', 'AirDays', 'AirTime', 'Genres', 'Tags',
    'Studios', 'PremiereDate', 'DateCreated', 'EndDate', 'ProductionYear', 'Height', 'AspectRatio', 'Video3DFormat', 'OfficialRating', 'CustomRating', 'People', 'LockData',
    'LockedFields', 'ProviderIds', 'PreferredMetadataLanguage', 'PreferredMetadataCountryCode', 'Taglines'];
  const RESULT = ['Name', 'ProviderIds', 'ProductionYear', 'IndexNumber', 'IndexNumberEnd', 'ParentIndexNumber', 'PremiereDate', 'ImageUrl', 'SearchProviderName', 'Overview', 'AlbumArtist', 'Artists'];

  const id = $derived(object.id.slice('jellyfin-item:'.length));
  const res = lazy(() => ctx, () => (id ? '/Items' : null), { query: () => ({ ids: id, Fields: FIELDS, EnableImages: 'false' }) });
  const it = $derived(res.data?.Items?.[0] || null);
  $effect(() => { if (it && !opened.list.some((x) => x.id === it.Id)) remember(it); });
  const src = $derived(it?.MediaSources?.[0] || null);
  const streams = $derived(src?.MediaStreams || it?.MediaStreams || []);
  const can = $derived(ctx.can('POST', `/Items/${id}`) !== 'no');
  const canDelete = $derived(ctx.can('DELETE', `/Items/${id}`) !== 'no');
  const identifiable = $derived(it && ['Movie', 'Series'].includes(it.Type));

  // --- edit ---
  let ed = $state(null);
  let lastId = null;
  $effect.pre(() => {
    if (it && it.Id !== lastId) {
      lastId = it.Id;
      ed = fresh(it);
      sq = { name: it.Name, year: it.ProductionYear || '' };
      results = null;
    }
  });
  function fresh(x) {
    return { Name: x.Name || '', OriginalTitle: x.OriginalTitle || '', ForcedSortName: x.ForcedSortName || '', ProductionYear: x.ProductionYear ?? '',
      PremiereDate: x.PremiereDate ? x.PremiereDate.slice(0, 10) : '', OfficialRating: x.OfficialRating || '', CommunityRating: x.CommunityRating ?? '',
      Overview: x.Overview || '', Genres: (x.Genres || []).join(', '), Tags: (x.Tags || []).join(', '), LockData: !!x.LockData };
  }
  const list = (s) => s.split(',').map((x) => x.trim()).filter(Boolean);
  const num = (v) => (v === '' || v == null ? null : Number(v));
  const dirty = $derived(it && ed && JSON.stringify(ed) !== JSON.stringify(fresh(it)));
  async function save() {
    const body = Object.fromEntries(EDIT.filter((k) => it[k] !== undefined).map((k) => [k, it[k]]));
    Object.assign(body, { Id: it.Id, Name: ed.Name.trim(), OriginalTitle: ed.OriginalTitle.trim() || null, ForcedSortName: ed.ForcedSortName.trim() || null,
      ProductionYear: num(ed.ProductionYear), PremiereDate: ed.PremiereDate ? `${ed.PremiereDate}T00:00:00.0000000Z` : null, OfficialRating: ed.OfficialRating.trim() || null,
      CommunityRating: num(ed.CommunityRating), Overview: ed.Overview, Genres: list(ed.Genres), Tags: list(ed.Tags), LockData: ed.LockData,
      ProviderIds: it.ProviderIds || {}, LockedFields: it.LockedFields || [], Taglines: it.Taglines || [] });
    if (await act(ctx, { path: `/Items/${it.Id}`, body, label: `jellyfin: edit ${label(it)}` })) res.reload();
  }

  // --- identify ---
  let sq = $state({ name: '', year: '' });
  let results = $state(null);
  let searching = $state(false);
  let images = $state(true);
  async function search(e) {
    e.preventDefault();
    searching = true;
    results = null;
    try {
      results = await ctx.api.post(`/Items/RemoteSearch/${it.Type}`, { SearchInfo: { Name: sq.name.trim(), Year: num(sq.year), ProviderIds: {} }, ItemId: it.Id, IncludeDisabledProviders: true });
    } catch (err) { ctx.notify(`identify: ${errText(err)}`, 'bad'); }
    searching = false;
  }
  async function apply(r) {
    const body = Object.fromEntries(RESULT.filter((k) => r[k] !== undefined).map((k) => [k, r[k]]));
    if (await act(ctx, { path: `/Items/RemoteSearch/Apply/${it.Id}?${qs({ replaceAllImages: images })}`, body, label: `jellyfin: identify ${label(it)} as ${r.Name}`, confirm: `Identify “${label(it)}” as “${r.Name}${r.ProductionYear ? ` (${r.ProductionYear})` : ''}”? Its metadata is replaced.` })) {
      results = null;
      setTimeout(() => res.reload(), 3000);
    }
  }

  async function del() {
    const r = await act(ctx, { method: 'DELETE', path: `/Items/${it.Id}`, label: `jellyfin: delete ${label(it)}`, confirm: `DELETE “${label(it)}”${it.Type === 'Series' ? ' with all its seasons and episodes' : ''}?\n\nThis removes the FILES on ${ctx.settings?.host || 'the server'}:\n${it.Path || ''}\n\nThere is no undo.` });
    if (r) {
      opened.list = opened.list.filter((x) => x.id !== it.Id);
      ctx.close();
    }
  }
  const openSeries = () => ctx.open(remember({ Id: it.SeriesId, Name: it.SeriesName, Type: 'Series' }));
  const streamText = (s) => s.Type === 'Video' ? `${s.Codec} ${s.Width}×${s.Height}${s.VideoRangeType && s.VideoRangeType !== 'SDR' ? ' ' + s.VideoRangeType : ''}${s.BitRate ? ' · ' + Math.round(s.BitRate / 1e6) + ' Mbit/s' : ''}`
    : s.Type === 'Audio' ? `${s.Codec} ${s.ChannelLayout || s.Channels + 'ch'}${s.Language ? ' · ' + s.Language : ''}`
    : `${s.Codec}${s.Language ? ' · ' + s.Language : ''}${s.IsExternal ? ' · external' : ''}${s.IsForced ? ' · forced' : ''}`;
</script>

{#if res.error}
  <Section title="jellyfin item" src="jellyfin"><span class="mono bad s">{res.error}</span></Section>
{:else if !it}
  <Section title="jellyfin item" src="jellyfin"><span class="mono dim spin s">{res.loading ? 'loading' : 'not found (deleted?)'}</span></Section>
{:else}
  <Section title={it.Type.toLowerCase()} src="jellyfin">
    {#if it.Type === 'Episode' && it.SeriesId}<button class="lnk mono s" onclick={openSeries}>{it.SeriesName} →</button>{/if}
    <Stats items={[
      { n: 'year', v: it.ProductionYear || '–' },
      { n: 'runtime', v: runtime(it.RunTimeTicks) },
      { n: 'size', v: src?.Size ? bytes(src.Size) : it.RecursiveItemCount != null ? `${it.RecursiveItemCount} items` : '–' },
      { n: 'added', v: it.DateCreated ? ago(Date.parse(it.DateCreated) / 1000, ctx.now) : '–' },
    ]} />
    {#if it.Path}<span class="mono dim path">{it.Path}</span>{/if}
    <span class="mono s">{[it.OfficialRating, it.CommunityRating && `★ ${it.CommunityRating.toFixed(1)}`, src?.Container, (it.Genres || []).join(', ')].filter(Boolean).join(' · ')}</span>
    {#if it.ProviderIds && Object.keys(it.ProviderIds).length}
      <span class="mono s ids">{#each Object.entries(it.ProviderIds) as [k, v]}{@const u = safeUrl((it.ExternalUrls || []).find((x) => x.Name.toLowerCase().includes(k.toLowerCase().slice(0, 4)))?.Url)}{#if u}<a href={u} target="_blank" rel="noopener noreferrer">{k} {v}</a>{:else}<span>{k} {v}</span>{/if}{/each}</span>
    {:else if identifiable}<span class="mono warn s">▲ not identified: no provider ids</span>{/if}
    {#if it.Overview}<p class="ov">{it.Overview}</p>{/if}
    {#if streams.length}
      <div class="streams mono">
        {#each streams as s (s.Index)}
          <span class="dim">{s.Type === 'Subtitle' ? 'sub' : s.Type.toLowerCase()}</span><span class="ell" title={s.DisplayTitle || ''}>{streamText(s)}{s.IsDefault ? ' · default' : ''}</span>
        {/each}
      </div>
    {/if}
    {#if it.LockData}<span class="mono dim s">metadata locked (refreshes leave it alone)</span>{/if}
  </Section>

  {#if can}
    <Section title="metadata" src="admin">
      <div class="form">
        <label class="mono">name <input class="field" bind:value={ed.Name} /></label>
        <label class="mono">original title <input class="field" bind:value={ed.OriginalTitle} /></label>
        <label class="mono">sort title <input class="field" bind:value={ed.ForcedSortName} placeholder={it.SortName || ''} /></label>
        <div class="two">
          <label class="mono">year <input class="field" type="number" min="1870" max="2100" bind:value={ed.ProductionYear} /></label>
          <label class="mono">premiere <input class="field" type="date" bind:value={ed.PremiereDate} /></label>
        </div>
        <div class="two">
          <label class="mono">rating <input class="field" bind:value={ed.OfficialRating} placeholder="e.g. 12" /></label>
          <label class="mono">score <input class="field" type="number" min="0" max="10" step="0.1" bind:value={ed.CommunityRating} /></label>
        </div>
        <label class="mono">genres <input class="field" bind:value={ed.Genres} placeholder="comma separated" /></label>
        <label class="mono">tags <input class="field" bind:value={ed.Tags} placeholder="comma separated" /></label>
        <label class="mono">overview <textarea class="field" rows="4" bind:value={ed.Overview}></textarea></label>
        <label class="mono chk"><input type="checkbox" bind:checked={ed.LockData} /> lock (refreshes keep these values)</label>
        <div class="row">
          <button class="btn" class:primary={dirty} disabled={!dirty || !ed.Name.trim()} onclick={save}>save</button>
          {#if dirty}<button class="btn" onclick={() => (ed = fresh(it))}>undo</button>{/if}
        </div>
      </div>
    </Section>

    {#if identifiable}
      <Section title="identify" src="remote search">
        <form class="row" onsubmit={search}>
          <input class="field grow" bind:value={sq.name} aria-label="Title to search" />
          <input class="field yr" type="number" bind:value={sq.year} placeholder="year" aria-label="Year" />
          <button class="btn" disabled={searching || !sq.name.trim()}><Icon name="search" size={12} />{searching ? '…' : 'search'}</button>
        </form>
        {#if results}
          <label class="mono chk"><input type="checkbox" bind:checked={images} /> replace images too</label>
          <div class="res">
            {#each results.slice(0, 12) as r, i (i)}
              <div class="r">
                <div class="m">
                  <span>{r.Name}{r.ProductionYear ? ` (${r.ProductionYear})` : ''}</span>
                  <span class="mono dim s">{r.SearchProviderName} · {Object.entries(r.ProviderIds || {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</span>
                  {#if r.Overview}<span class="dim s ell2">{r.Overview}</span>{/if}
                </div>
                <button class="btn" onclick={() => apply(r)}>apply</button>
              </div>
            {:else}<span class="mono dim s">no matches</span>{/each}
          </div>
        {/if}
      </Section>
    {/if}

    <Section title="refresh" src="admin">
      <RefreshOpts id={it.Id} name={label(it)} {ctx} done={() => setTimeout(() => res.reload(), 3000)} />
      {#if it.DateLastRefreshed}<span class="mono dim s">last refreshed {ago(Date.parse(it.DateLastRefreshed) / 1000, ctx.now)} ago</span>{/if}
    </Section>
  {/if}

  {#if canDelete}
    <Section title="danger" src="admin · deletes files">
      <button class="btn danger" onclick={del}><Icon name="close" size={12} />delete {it.Type.toLowerCase()} + files</button>
    </Section>
  {/if}
{/if}

<style>
  .s { font-size: 10.5px; }
  .path { font-size: 10.5px; word-break: break-all; }
  .ids { display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .ids a { color: var(--sig); }
  .ov { margin: 0; font-size: 12px; line-height: 1.5; color: var(--dim); display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
  .streams { display: grid; grid-template-columns: 36px minmax(0, 1fr); gap: 2px 8px; font-size: 11px; }
  .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .form { display: flex; flex-direction: column; gap: 6px; }
  .form label { display: flex; flex-direction: column; gap: 2px; font-size: 10.5px; color: var(--dim); }
  .form label.chk, .chk { flex-direction: row; align-items: center; gap: 6px; font-size: 11px; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font-size: 12px; color: var(--ink); font-family: inherit; min-width: 0; }
  textarea.field { resize: vertical; }
  .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .grow { flex: 1; }
  .yr { width: 70px; }
  .res { display: flex; flex-direction: column; gap: 8px; }
  .r { display: flex; gap: 8px; align-items: center; }
  .m { display: flex; flex-direction: column; flex: 1; min-width: 0; font-size: 12.5px; }
  .ell2 { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .danger:not(:disabled) { color: var(--bad); border-color: var(--bad); align-self: flex-start; }
  .bad { color: var(--bad); }
  .warn { color: var(--warn); }
</style>
