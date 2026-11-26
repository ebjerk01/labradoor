<script>
  // Refresh options for a library or one item (POST /Items/{id}/Refresh): scan for new files, fill in missing metadata,
  // or replace it all; images and trickplay optional. A full replace on a whole library is slow: it asks first.
  import Icon from '$lab/Icon.svelte';
  import { act } from '$lab/sdk.js';
  import { qs } from '$lab/sdk.js';
  let { id, name, ctx, library = false, done = () => {} } = $props();
  const MODES = [['scan', 'scan for new + changed files'], ['missing', 'search missing metadata'], ['all', 'replace all metadata']];
  let mode = $state('scan');
  let images = $state(false);
  let trick = $state(false);
  const can = $derived(ctx.can('POST', `/Items/${id}/Refresh`) !== 'no');

  async function go() {
    const full = mode !== 'scan';
    if (!full) images = false;
    const q = qs({ metadataRefreshMode: full ? 'FullRefresh' : 'Default', imageRefreshMode: full ? 'FullRefresh' : 'Default',
      replaceAllMetadata: mode === 'all', replaceAllImages: images, regenerateTrickplay: trick });
    const warn = library && (mode === 'all' || images) ? `Replace ${mode === 'all' ? 'all metadata' : ''}${mode === 'all' && images ? ' and ' : ''}${images ? 'all images' : ''} in the whole “${name}” library? This runs for a long time.` : null;
    if (await act(ctx, { path: `/Items/${id}/Refresh?${q}`, label: `jellyfin: ${MODES.find((m) => m[0] === mode)[1]} · ${name}`, confirm: warn })) done();
  }
</script>

{#if can}
  <div class="ro">
    <select class="field" bind:value={mode} aria-label="Refresh mode">
      {#each MODES as [v, l]}<option value={v}>{l}</option>{/each}
    </select>
    <label class="mono"><input type="checkbox" bind:checked={images} disabled={mode === 'scan'} /> replace images</label>
    <label class="mono"><input type="checkbox" bind:checked={trick} /> trickplay</label>
    <button class="btn" onclick={go}><Icon name="restart" size={12} />refresh</button>
  </div>
{/if}

<style>
  .ro { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }
  .ro label { font-size: 11px; display: flex; gap: 4px; align-items: center; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font-size: 12px; color: var(--ink); }
</style>
