<script>
  // One library: folders (add/remove), options (monitoring, metadata, images, providers + their order), rename, refresh, remove.
  // Writes need admin; removing the library keeps the files (Jellyfin forgets the items and their watch state).
  import { untrack } from 'svelte';
  import Icon from '$lab/Icon.svelte';
  import { lazy, qs } from '$lab/sdk.js';
  import { write } from './store.svelte.js';
  import DirPicker from './DirPicker.svelte';
  import FetcherList from './FetcherList.svelte';
  import RefreshOpts from './RefreshOpts.svelte';
  let { lib, ctx } = $props();

  const can = $derived(ctx.can('POST', '/Library/VirtualFolders/LibraryOptions') !== 'no');
  const avail = lazy(() => ctx, () => '/Libraries/AvailableOptions', { query: () => ({ libraryContentType: lib.type || '', isNewLibrary: 'false' }) });
  let opt = $state({});
  let base = $state('{}');
  let newPath = $state('');
  let newName = $state('');
  let lastId = null;
  $effect.pre(() => {
    if (lib.id !== lastId) {  // a fresh copy when another library is shown; keep edits across the 15 s refreshes
      lastId = lib.id;
      base = JSON.stringify(lib.options || {});
      opt = JSON.parse(base);
      newName = lib.name;
      newPath = '';
    }
  });
  const dirty = $derived(JSON.stringify(opt) !== base);
  const tv = $derived(lib.type === 'tvshows');
  const unscanned = $derived(lib.id.startsWith('new:'));  // Jellyfin gives it an id at its first scan

  const FLAGS = [
    ['Enabled', 'library enabled'], ['EnableRealtimeMonitor', 'real-time monitoring'], ['SaveLocalMetadata', 'save artwork + nfo next to the media'],
    ['EnableInternetProviders', 'internet metadata providers'], ['EnableEmbeddedTitles', 'prefer embedded titles'],
    ['EnableChapterImageExtraction', 'chapter images'], ['ExtractChapterImagesDuringLibraryScan', '… during the scan'],
    ['EnableTrickplayImageExtraction', 'trickplay images'], ['ExtractTrickplayImagesDuringLibraryScan', '… during the scan'],
    ['SaveTrickplayWithMedia', 'trickplay next to the media'], ['SaveSubtitlesWithMedia', 'subtitles next to the media'],
    ['EnableLUFSScan', 'audio normalisation (LUFS)'], ['AutomaticallyAddToCollection', 'auto collections'], ['EnablePhotos', 'photos'],
  ];
  const TV = [['EnableAutomaticSeriesGrouping', 'merge series spread over folders'], ['EnableEmbeddedEpisodeInfos', 'prefer embedded episode info']];

  // per item type (Movie, Series, Season, Episode …): metadata + image fetchers with their order. Types the library has no
  // entry for yet get Jellyfin's defaults (as its own dashboard does); that alone does not count as a change.
  $effect(() => {
    const a = avail.data;
    if (!a) return;
    untrack(() => {
      const clean = JSON.stringify(opt) === base;
      const have = new Set((opt.TypeOptions || []).map((x) => x.Type));
      const add = a.TypeOptions.filter((t) => !have.has(t.Type)).map((t) => ({ Type: t.Type,
        MetadataFetchers: t.MetadataFetchers.filter((f) => f.DefaultEnabled).map((f) => f.Name), MetadataFetcherOrder: t.MetadataFetchers.map((f) => f.Name),
        ImageFetchers: t.ImageFetchers.filter((f) => f.DefaultEnabled).map((f) => f.Name), ImageFetcherOrder: t.ImageFetchers.map((f) => f.Name),
        ImageOptions: t.DefaultImageOptions || [] }));
      if (!add.length) return;
      opt.TypeOptions = [...(opt.TypeOptions || []), ...add];
      if (clean) base = JSON.stringify(opt);
    });
  });
  const typeIdx = (t) => (opt.TypeOptions || []).findIndex((x) => x.Type === t);

  const L = ['libs'];
  async function save() {
    const sent = JSON.stringify(opt);
    if (await write(ctx, L, { path: '/Library/VirtualFolders/LibraryOptions', body: { Id: lib.id, LibraryOptions: opt }, label: `jellyfin: options · ${lib.name}` })) base = sent;
  }
  const addPath = async () => {
    const p = newPath.trim();
    if (!p) return;
    if (await write(ctx, L, { path: `/Library/VirtualFolders/Paths?${qs({ refreshLibrary: true })}`, body: { Name: lib.name, PathInfo: { Path: p } }, label: `jellyfin: add ${p} to ${lib.name}` })) newPath = '';
  };
  const rmPath = (p) => write(ctx, L, { method: 'DELETE', path: `/Library/VirtualFolders/Paths?${qs({ name: lib.name, path: p, refreshLibrary: true })}`, label: `jellyfin: remove ${p} from ${lib.name}`, confirm: `Remove ${p} from “${lib.name}”? The files stay; Jellyfin forgets their items.` });
  const rename = () => write(ctx, L, { path: `/Library/VirtualFolders/Name?${qs({ name: lib.name, newName: newName.trim(), refreshLibrary: true })}`, label: `jellyfin: rename ${lib.name} → ${newName.trim()}` });
  const remove = () => write(ctx, L, { method: 'DELETE', path: `/Library/VirtualFolders?${qs({ name: lib.name, refreshLibrary: false })}`, label: `jellyfin: remove library ${lib.name}`, confirm: `Remove the library “${lib.name}”?\n\nThe files on disk stay. Jellyfin forgets its items, their metadata and everyone's watch state for them.` });
</script>

<div class="le">
  <fieldset disabled={!can}>
    <legend class="cap">folders</legend>
    {#each lib.paths as p (p)}
      <div class="p"><span class="mono">{p}</span>
        {#if lib.paths.length > 1}<button class="btn x" aria-label="remove folder {p}" onclick={() => rmPath(p)}><Icon name="close" size={11} /></button>{/if}
      </div>
    {/each}
    <div class="add"><DirPicker bind:value={newPath} {ctx} /><button class="btn" disabled={!newPath.trim()} onclick={addPath}>add folder</button></div>
  </fieldset>

  <fieldset disabled={!can}>
    <legend class="cap">options</legend>
    <div class="flags">
      {#each [...FLAGS, ...(tv ? TV : [])] as [k, l] (k)}
        {#if k in opt || k === 'EnableRealtimeMonitor'}<label class="mono"><input type="checkbox" bind:checked={opt[k]} /> {l}</label>{/if}
      {/each}
    </div>
    <div class="nums">
      <label class="mono">metadata language <input class="field s" maxlength="10" bind:value={opt.PreferredMetadataLanguage} placeholder="en" /></label>
      <label class="mono">country <input class="field s" maxlength="4" bind:value={opt.MetadataCountryCode} placeholder="NO" /></label>
      <label class="mono">auto refresh
        <select class="field" bind:value={opt.AutomaticRefreshIntervalDays}>{#each [0, 30, 60, 90, 180, 365] as d}<option value={d}>{d ? `${d} d` : 'never'}</option>{/each}</select>
      </label>
      {#if tv}<label class="mono">season 0 <input class="field m" bind:value={opt.SeasonZeroDisplayName} /></label>{/if}
    </div>
    {#if avail.data}
      <div class="fetch">
        <FetcherList title="metadata savers" all={avail.data.MetadataSavers.map((f) => f.Name)} bind:enabled={opt.MetadataSavers} disabled={!can} />
        <FetcherList title="local metadata (order)" all={avail.data.MetadataReaders.map((f) => f.Name)} bind:enabled={opt.DisabledLocalMetadataReaders} bind:order={opt.LocalMetadataReaderOrder} inverted disabled={!can} />
        <FetcherList title="subtitle downloaders" all={avail.data.SubtitleFetchers.map((f) => f.Name)} bind:enabled={opt.DisabledSubtitleFetchers} bind:order={opt.SubtitleFetcherOrder} inverted disabled={!can} />
      </div>
      {#each avail.data.TypeOptions as t (t.Type)}
        {@const i = typeIdx(t.Type)}
        {#if i >= 0}
          <div class="fetch">
            <FetcherList title="{t.Type.toLowerCase()} · metadata" all={t.MetadataFetchers.map((f) => f.Name)} bind:enabled={opt.TypeOptions[i].MetadataFetchers} bind:order={opt.TypeOptions[i].MetadataFetcherOrder} disabled={!can} />
            <FetcherList title="{t.Type.toLowerCase()} · images" all={t.ImageFetchers.map((f) => f.Name)} bind:enabled={opt.TypeOptions[i].ImageFetchers} bind:order={opt.TypeOptions[i].ImageFetcherOrder} disabled={!can} />
          </div>
        {/if}
      {/each}
    {:else if avail.error}<span class="mono bad note">{avail.error}</span>{:else}<span class="mono dim spin note">providers</span>{/if}
    <div class="row">
      <button class="btn" class:primary={dirty} disabled={!dirty || unscanned} onclick={save}>save options</button>
      {#if unscanned}<span class="mono dim note">scan the libraries once first (no id yet)</span>{/if}
      {#if dirty}<button class="btn" onclick={() => (opt = JSON.parse(base))}>undo</button>{/if}
    </div>
  </fieldset>

  <fieldset>
    <legend class="cap">refresh</legend>
    {#if unscanned}<span class="mono dim note">not scanned yet: use “scan all” above</span>{:else}<RefreshOpts id={lib.id} name={lib.name} {ctx} library />{/if}
  </fieldset>

  {#if can}
    <div class="row">
      <input class="field m" bind:value={newName} aria-label="New name for {lib.name}" />
      <button class="btn" disabled={!newName.trim() || newName.trim() === lib.name} onclick={rename}>rename</button>
      <span class="grow"></span>
      <button class="btn danger" onclick={remove}><Icon name="close" size={12} />remove library</button>
    </div>
  {/if}
</div>

<style>
  .le { display: flex; flex-direction: column; gap: 10px; }
  fieldset { border: 1px solid var(--line); border-radius: 4px; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; margin: 0; min-width: 0; }
  legend { padding: 0 4px; }
  .p { display: flex; align-items: center; gap: 8px; font-size: 12px; }
  .p .mono { flex: 1; word-break: break-all; }
  .add { display: flex; gap: 6px; align-items: flex-start; flex-wrap: wrap; }
  .flags { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 2px 12px; }
  label { font-size: 11.5px; display: flex; align-items: center; gap: 6px; }
  .nums { display: flex; flex-wrap: wrap; gap: 6px 14px; }
  .fetch { display: flex; flex-wrap: wrap; gap: 8px 18px; padding-top: 6px; border-top: 1px dashed var(--line); }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 4px 7px; font-size: 12px; color: var(--ink); }
  .s { width: 56px; }
  .m { width: 160px; }
  .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .grow { flex: 1; }
  .x { padding: 3px 6px; }
  .danger:not(:disabled) { color: var(--bad); border-color: var(--bad); }
  .bad { color: var(--bad); }
  .note { font-size: 10.5px; }
</style>
