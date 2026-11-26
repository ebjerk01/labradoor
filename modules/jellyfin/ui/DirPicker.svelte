<script>
  // A folder on the Jellyfin server, as Jellyfin sees it (GET /Environment/DirectoryContents): type a path or click through.
  import { lazy } from '$lab/sdk.js';
  let { value = $bindable(''), ctx, start = '/opt/media' } = $props();
  let at = $state('/');
  let open = $state(false);
  const dirs = lazy(() => ctx, () => (open ? '/Environment/DirectoryContents' : null), { query: () => ({ path: at, includeDirectories: 'true', includeFiles: 'false' }) });
  const up = (p) => p.replace(/\/[^/]+\/?$/, '') || '/';
  function into(p) { at = p; value = p; }
</script>

<div class="dp">
  <div class="row">
    <input class="field mono" placeholder="/opt/media/…" bind:value aria-label="Folder path" />
    <button class="btn x" type="button" aria-expanded={open} onclick={() => { if (!open) at = value || start; open = !open; }}>browse</button>
  </div>
  {#if open}
    <div class="list mono">
      <span class="dim at">{at}{#if dirs.loading} <span class="spin"></span>{/if}</span>
      {#if at !== '/'}<button class="lnk d" type="button" onclick={() => into(up(at))}>..</button>{/if}
      {#each dirs.data || [] as d (d.Path)}
        <button class="lnk d" type="button" class:faint={d.Name.startsWith('.')} onclick={() => into(d.Path)}>{d.Name}/</button>
      {:else}
        {#if !dirs.loading}<span class="dim">{dirs.error || 'no folders here'}</span>{/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .dp { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
  .row { display: flex; gap: 6px; }
  .row .field { flex: 1; min-width: 0; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font-size: 12px; color: var(--ink); }
  .x { padding: 3px 8px; }
  .list { display: flex; flex-direction: column; max-height: 200px; overflow: auto; border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 11.5px; background: var(--bg); }
  .at { font-size: 10.5px; padding-bottom: 4px; word-break: break-all; }
  .d { padding: 2px 0; }
</style>
