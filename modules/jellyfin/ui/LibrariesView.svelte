<script>
  // ~/jellyfin-libraries — every library: folders, scan state, options, providers; add a new one. Writes: admin.
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import Bar from '$lab/Bar.svelte';
  import { qs } from '$lab/sdk.js';
  import { write } from './store.svelte.js';
  import LibraryEdit from './LibraryEdit.svelte';
  import DirPicker from './DirPicker.svelte';
  let { data, ctx } = $props();

  const TYPES = [['movies', 'movies'], ['tvshows', 'shows'], ['music', 'music'], ['musicvideos', 'music videos'], ['homevideos', 'home videos + photos'],
    ['boxsets', 'collections'], ['books', 'books'], ['mixed', 'mixed']];
  let open = $state(null);
  let adding = $state(false);
  let nl = $state({ name: '', type: 'movies', path: '', monitor: true, nfo: true, lang: 'en', country: 'NO' });
  const canAdd = $derived(ctx.can('POST', '/Library/VirtualFolders') !== 'no');
  const canScan = $derived(ctx.can('POST', '/Library/Refresh') !== 'no');
  const scanning = $derived((data?.libs || []).some((l) => l.refresh && l.refresh !== 'Idle'));

  async function add(e) {
    e.preventDefault();
    const name = nl.name.trim(), path = nl.path.trim();
    if (!name || !path) return ctx.notify('name + a folder', 'bad');
    // Jellyfin's own defaults for this content type: which savers/fetchers start enabled, image limits
    let a = null;
    try { a = await ctx.api.get('/Libraries/AvailableOptions', { libraryContentType: nl.type === 'mixed' ? '' : nl.type, isNewLibrary: 'true' }); } catch { /* defaults below */ }
    const on = (list) => (list || []).filter((f) => f.DefaultEnabled).map((f) => f.Name);
    const LibraryOptions = {
      Enabled: true, EnableRealtimeMonitor: nl.monitor, SaveLocalMetadata: nl.nfo, PreferredMetadataLanguage: nl.lang || null, MetadataCountryCode: nl.country || null,
      PathInfos: [{ Path: path }], MetadataSavers: nl.nfo ? on(a?.MetadataSavers) : [], AutomaticRefreshIntervalDays: 0,
      EnableChapterImageExtraction: false, ExtractChapterImagesDuringLibraryScan: false, EnableTrickplayImageExtraction: false,
      TypeOptions: (a?.TypeOptions || []).map((t) => ({ Type: t.Type, MetadataFetchers: on(t.MetadataFetchers), MetadataFetcherOrder: t.MetadataFetchers.map((f) => f.Name),
        ImageFetchers: on(t.ImageFetchers), ImageFetcherOrder: t.ImageFetchers.map((f) => f.Name), ImageOptions: t.DefaultImageOptions || [] })),
    };
    const q = qs({ name, collectionType: nl.type === 'mixed' ? null : nl.type, paths: [path], refreshLibrary: true });
    if (await write(ctx, ['libs', 'counts'], { path: `/Library/VirtualFolders?${q}`, body: { LibraryOptions }, label: `jellyfin: add library ${name}` })) {
      adding = false;
      nl = { ...nl, name: '', path: '' };
    }
  }
  const typeName = (t) => TYPES.find((x) => x[0] === t)?.[1] || t || 'mixed';
</script>

{#if !data}<p class="mono dim pad spin">loading jellyfin</p>{:else}
<div class="lv fade">
  <div class="bar">
    <span class="cap">~/jellyfin-libraries · {data.libs.length}</span>
    <span class="mono dim note">{scanning ? 'scanning…' : 'idle'} · {data.counts.MovieCount ?? '–'} movies · {data.counts.SeriesCount ?? '–'} series · {data.counts.EpisodeCount ?? '–'} episodes</span>
    {#if canScan}<button class="btn" onclick={() => write(ctx, ['libs'], { path: '/Library/Refresh', label: 'jellyfin: scan all libraries' })}><Icon name="restart" size={12} />scan all</button>{/if}
    {#if canAdd}<button class="btn primary" onclick={() => (adding = !adding)}><Icon name="archive" size={12} />add library</button>{/if}
  </div>

  {#if adding}
    <form class="new" onsubmit={add}>
      <div class="r">
        <input class="field mono n" placeholder="name" bind:value={nl.name} required aria-label="Library name" />
        <select class="field" bind:value={nl.type} aria-label="Content type">{#each TYPES as [v, l]}<option value={v}>{l}</option>{/each}</select>
      </div>
      <DirPicker bind:value={nl.path} {ctx} />
      <div class="r">
        <label class="mono"><input type="checkbox" bind:checked={nl.monitor} /> real-time monitoring</label>
        <label class="mono"><input type="checkbox" bind:checked={nl.nfo} /> nfo + artwork next to media</label>
        <label class="mono">lang <input class="field s" bind:value={nl.lang} /></label>
        <label class="mono">country <input class="field s" bind:value={nl.country} /></label>
      </div>
      <div class="r"><button class="btn primary">add + scan</button><span class="mono dim note">more options after it exists</span></div>
    </form>
  {/if}

  <div class="list">
    {#each data.libs as l (l.id)}
      {@const busy = l.refresh && l.refresh !== 'Idle'}
      <div class="lib" class:on={open === l.id}>
        <button class="lnk head" aria-expanded={open === l.id} onclick={() => (open = open === l.id ? null : l.id)}>
          <Glyph status={l.options.Enabled === false ? 'off' : busy ? 'warn' : 'ok'} size={10} />
          <span class="nm">{l.name}</span>
          <span class="mono dim t">{typeName(l.type)}</span>
          <span class="mono dim p">{l.paths.join(' · ')}</span>
          <span class="mono dim f">{l.options.EnableRealtimeMonitor ? 'watch' : ''}{l.options.SaveLocalMetadata ? ' · nfo' : ''}</span>
          {#if busy}<span class="pb"><Bar value={l.progress || 0} color="var(--sig)" /></span>{:else}<span class="pb mono dim">{l.refresh || ''}</span>{/if}
          <Icon name="wrench" size={11} />
        </button>
        {#if open === l.id}<div class="ed"><LibraryEdit lib={l} {ctx} /></div>{/if}
      </div>
    {:else}
      <span class="mono dim">no libraries</span>
    {/each}
  </div>
</div>
{/if}

<style>
  .lv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 12px; }
  .bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .note { font-size: 11px; flex: 1; }
  .new { display: flex; flex-direction: column; gap: 8px; padding: 10px; border: 1px solid var(--line); border-radius: 4px; }
  .r { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .r label { font-size: 11.5px; display: flex; gap: 4px; align-items: center; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 12px; color: var(--ink); }
  .n { width: 200px; max-width: 100%; }
  .s { width: 50px; }
  .list { display: flex; flex-direction: column; }
  .lib { border-bottom: 1px solid var(--line); }
  .lib.on { background: var(--panel); }
  .head { width: 100%; display: grid; grid-template-columns: 12px minmax(70px, 1fr) 80px minmax(0, 2fr) 70px 70px 12px; gap: 10px; align-items: center; padding: 8px 4px; font-size: 12.5px; }
  .nm, .p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .t, .p, .f, .pb { font-size: 10.5px; }
  .pb { display: flex; }
  .ed { padding: 4px 4px 14px 22px; }
  .pad { padding: 12px 16px; }
  @media (max-width: 640px) {
    .head { grid-template-columns: 12px minmax(0, 1fr) auto 60px 12px; }
    .p, .f { display: none; }
    .pb { width: 60px; }
    .ed { padding-left: 4px; }
  }
</style>
