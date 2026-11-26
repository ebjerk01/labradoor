<script>
  // ~/jellyfin-items — browse + search the libraries; a row opens the item (object panel: detail, metadata, identify,
  // refresh, delete). "hints": duplicate movies (same TMDb/IMDb id), unidentified movies/series, missing episodes.
  import Icon from '$lab/Icon.svelte';
  import { ago, bytes } from '$lab/fmt.js';
  import { label } from './jf.js';
  import { lazy } from '$lab/sdk.js';
  import { remember } from './store.svelte.js';
  let { data, ctx } = $props();

  const TYPES = [['Movie,Series', 'movies + series'], ['Movie', 'movies'], ['Series', 'series'], ['Episode', 'episodes']];
  const SORTS = [['DateCreated', 'added'], ['SortName', 'name'], ['ProductionYear', 'year'], ['CommunityRating', 'score']];
  const PAGE = 50;
  let tab = $state('browse');
  let q = $state('');
  let term = $state('');
  let types = $state('Movie,Series');
  let parent = $state('');
  let sort = $state('DateCreated');
  let start = $state(0);
  let timer;
  $effect(() => { const v = q; clearTimeout(timer); timer = setTimeout(() => { term = v.trim(); start = 0; }, 300); return () => clearTimeout(timer); });

  const list = lazy(() => ctx, () => (tab === 'browse' ? '/Items' : null), { query: () => ({
    Recursive: 'true', IncludeItemTypes: types, SortBy: sort === 'SortName' ? 'SortName' : `${sort},SortName`, SortOrder: sort === 'SortName' ? 'Ascending' : 'Descending',
    StartIndex: start, Limit: PAGE, Fields: 'DateCreated,Path,ProductionYear,ProviderIds,MediaSources', EnableImages: 'false', EnableUserData: 'false',
    EnableTotalRecordCount: 'true', ...(term ? { searchTerm: term } : {}), ...(parent ? { ParentId: parent } : {}) }) });
  const total = $derived(list.data?.TotalRecordCount ?? 0);

  // hints, on demand
  const movies = lazy(() => ctx, () => (tab === 'hints' ? '/Items' : null), { query: () => ({ Recursive: 'true', IncludeItemTypes: 'Movie,Series',
    Fields: 'ProviderIds,Path,ProductionYear', EnableImages: 'false', EnableUserData: 'false', Limit: 5000 }) });
  const missing = lazy(() => ctx, () => (tab === 'hints' ? '/Items' : null), { query: () => ({ Recursive: 'true', IncludeItemTypes: 'Episode', IsMissing: 'true',
    IsUnaired: 'false', SortBy: 'SeriesSortName,ParentIndexNumber,IndexNumber', Fields: 'ProductionYear', EnableImages: 'false', EnableUserData: 'false',
    Limit: 200, EnableTotalRecordCount: 'true' }) });
  const dupes = $derived.by(() => {
    const by = new Map();
    for (const it of (movies.data?.Items || []).filter((x) => x.Type === 'Movie')) {
      const k = it.ProviderIds?.Tmdb ? `tmdb ${it.ProviderIds.Tmdb}` : it.ProviderIds?.Imdb ? `imdb ${it.ProviderIds.Imdb}` : null;
      if (k) by.set(k, [...(by.get(k) || []), it]);
    }
    return [...by.entries()].filter(([, v]) => v.length > 1);
  });
  const unknown = $derived((movies.data?.Items || []).filter((x) => !x.ProviderIds || !Object.keys(x.ProviderIds).length));

  const size = (it) => it.MediaSources?.[0]?.Size;
  const open = (it) => ctx.open(remember(it));
  const glyph = (t) => ({ Movie: 'mv', Series: 'tv', Episode: 'ep', Season: 'se' }[t] || '··');
</script>

{#if !data}<p class="mono dim pad spin">loading jellyfin</p>{:else}
<div class="iv fade">
  <div class="bar">
    <div class="seg" role="group" aria-label="items tabs">
      <button aria-pressed={tab === 'browse'} onclick={() => (tab = 'browse')}>browse</button>
      <button aria-pressed={tab === 'hints'} onclick={() => (tab = 'hints')}>hints</button>
    </div>
    {#if tab === 'browse'}
      <input class="field q" placeholder="search titles" bind:value={q} aria-label="Search" />
      <select class="field" bind:value={types} onchange={() => (start = 0)} aria-label="Type">{#each TYPES as [v, l]}<option value={v}>{l}</option>{/each}</select>
      <select class="field" bind:value={parent} onchange={() => (start = 0)} aria-label="Library">
        <option value="">all libraries</option>{#each data.libs as l (l.id)}<option value={l.id}>{l.name}</option>{/each}
      </select>
      <select class="field" bind:value={sort} onchange={() => (start = 0)} aria-label="Sort">{#each SORTS as [v, l]}<option value={v}>{l}</option>{/each}</select>
    {/if}
    {#if list.loading || movies.loading}<span class="mono dim spin"></span>{/if}
  </div>

  {#if tab === 'browse'}
    {#if list.error}<p class="mono bad s">{list.error}</p>{/if}
    <div class="scroll-x"><div class="t">
      {#each list.data?.Items || [] as it (it.Id)}
        <button class="lnk row r" onclick={() => open(it)}>
          <span class="mono dim g">{glyph(it.Type)}</span>
          <span class="nm">{label(it)}{#if it.Type === 'Episode'}<span class="dim"> · {it.Name}</span>{/if}</span>
          <span class="mono s u">{it.ProviderIds && Object.keys(it.ProviderIds).length ? '' : '▲ unidentified'}</span>
          <span class="mono dim s r1">{size(it) ? bytes(size(it)) : ''}</span>
          <span class="mono dim s r1">{it.DateCreated ? ago(Date.parse(it.DateCreated) / 1000, ctx.now) : ''}</span>
        </button>
      {:else}
        {#if !list.loading}<span class="mono dim s">nothing found</span>{/if}
      {/each}
    </div></div>
    {#if total > PAGE}
      <div class="pager mono">
        <button class="btn x" disabled={start === 0} onclick={() => (start = Math.max(0, start - PAGE))}>←</button>
        <span class="dim s">{start + 1}–{Math.min(start + PAGE, total)} of {total}</span>
        <button class="btn x" disabled={start + PAGE >= total} onclick={() => (start += PAGE)}>→</button>
      </div>
    {:else if total}<span class="mono dim s">{total} items</span>{/if}
  {:else}
    {#if movies.error}<p class="mono bad s">{movies.error}</p>{/if}
    <h3 class="cap h">~/duplicate movies · same TMDb/IMDb id ({dupes.length})</h3>
    {#each dupes as [k, v] (k)}
      <div class="grp">
        <span class="mono dim s">{k}</span>
        {#each v as it (it.Id)}
          <button class="lnk row r2" onclick={() => open(it)}><span class="nm">{label(it)}</span><span class="mono dim s ell">{it.Path}</span><span class="mono dim s">{size(it) ? bytes(size(it)) : ''}</span></button>
        {/each}
      </div>
    {:else}{#if movies.data}<span class="mono dim s">● none</span>{/if}{/each}
    <h3 class="cap h">~/unidentified · no provider ids ({unknown.length})</h3>
    {#each unknown.slice(0, 100) as it (it.Id)}
      <button class="lnk row r2" onclick={() => open(it)}><span class="nm">{label(it)}</span><span class="mono dim s ell">{it.Path}</span><span class="mono dim s">{it.Type.toLowerCase()}</span></button>
    {:else}{#if movies.data}<span class="mono dim s">● none</span>{/if}{/each}
    <h3 class="cap h">~/missing episodes · aired, no file ({missing.data?.TotalRecordCount ?? '–'})</h3>
    {#if missing.error}<p class="mono bad s">{missing.error}</p>{/if}
    {#each missing.data?.Items || [] as it (it.Id)}
      <button class="lnk row r2" onclick={() => open(it)}><span class="nm">{label(it)}</span><span class="mono dim s ell">{it.Name}</span><span class="mono dim s">{it.PremiereDate ? it.PremiereDate.slice(0, 10) : ''}</span></button>
    {:else}{#if missing.data}<span class="mono dim s">● none known (Jellyfin lists missing episodes only for series with metadata)</span>{/if}{/each}
  {/if}
  <span class="mono dim s foot"><Icon name="search" size={10} /> Ctrl-K finds titles too</span>
</div>
{/if}

<style>
  .iv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 10px; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 12px; color: var(--ink); }
  .q { flex: 1 1 160px; min-width: 0; }
  .t { display: flex; flex-direction: column; min-width: 520px; }
  .r { display: grid; grid-template-columns: 22px minmax(0, 1fr) 90px 60px 40px; gap: 10px; align-items: baseline; padding: 4px 4px; font-size: 12.5px; border-bottom: 1px solid var(--q); }
  .r2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) 60px; gap: 10px; align-items: baseline; padding: 3px 4px; font-size: 12.5px; }
  .nm, .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .g { font-size: 10px; }
  .s { font-size: 10.5px; }
  .r1 { text-align: right; }
  .pager { display: flex; gap: 10px; align-items: center; }
  .x { padding: 3px 8px; }
  .h { margin: 8px 0 2px; font-weight: 400; }
  .grp { display: flex; flex-direction: column; padding: 4px 0 6px; border-bottom: 1px solid var(--q); }
  .foot { display: flex; gap: 4px; align-items: center; margin-top: 6px; }
  .bad { color: var(--bad); }
  .pad { padding: 12px 16px; }
  .u { color: var(--warn); }
  @media (max-width: 640px) {
    .t { min-width: 0; }
    .r { grid-template-columns: 18px minmax(0, 1fr) 44px 30px; gap: 6px; }
    .r .u { display: none; }
    .r2 { grid-template-columns: minmax(0, 1fr) 60px; } .r2 .ell { display: none; }
  }
</style>
