<script>
  // Stuck/failed downloads, one row per download: "import files" (manual import candidates, for downloads waiting on an
  // import; `imports`) and "remove" (remove + blocklist + search again; admin, confirmed).
  // In one app's facet, `ctx` is that app's (sonarr/radarr). In the media hub, groups carry `app` and every action runs
  // through ctx.via(app), so THAT module's manifest decides who may do it (the hub shows the app as a tag).
  import { ago, forget } from '../sdk.js';
  import Glyph from '../Glyph.svelte';
  import ActionButton from '../ActionButton.svelte';
  import ManualImport from './ManualImport.svelte';
  import { A } from './logic.js';
  let { groups = [], ctx, limit = 8, empty = '● nothing stuck', imports = true } = $props();
  let importing = $state(null);
  const own = (g) => (g.app ? ctx.via(g.app) : ctx);
</script>

<div class="list">
  {#each groups.slice(0, limit) as g ((g.app || '') + g.key)}
    {@const app = own(g)}
    <div class="r row">
      <Glyph status={g.level || 'warn'} size={10} />
      <div class="main">
        <span class="t" title={g.title}>{#if g.app}<span class="mono sig tag">{g.app}</span>{/if}{g.title}{#if g.n > 1}<span class="mono dim"> ×{g.n}</span>{/if}</span>
        <span class="mono dim why" title={g.reason}>{g.state} · {g.reason}</span>
      </div>
      <span class="mono dim a">{ago(g.added, ctx.now)}</span>
      {#if app}
        <span class="acts">
          {#if imports && g.needsImport && app.can('POST', `${A}/command`) !== 'no'}
            {@const folders = (app.settings?.import_paths || []).length}
            <button class="btn sm" aria-pressed={importing === g.key} disabled={!folders}
              title={folders ? 'pick the files to import' : `manual import is off: the owner sets its allowed folders in Settings → ${app.id}`}
              onclick={() => (importing = importing === g.key ? null : g.key)}>import files</button>
          {/if}
          <ActionButton ctx={app} method="DELETE" path="{A}/queue/{g.id}" query={{ removeFromClient: true, blocklist: true, skipRedownload: false }}
            label="remove {g.title}" icon="close" small title="remove from {g.app || 'the app'} and the download client, blocklist the release, search again"
            confirm="remove{g.n > 1 ? ` ${g.n} items` : ''} + blocklist?" done={() => { forget(`${app.id}:problems`); }} />
        </span>
      {/if}
    </div>
    {#if app && importing === g.key}<ManualImport ctx={app} downloadId={g.downloadId} onclose={() => (importing = null)} />{/if}
  {:else}
    {#if empty}<span class="mono dim s">{empty}</span>{/if}
  {/each}
  {#if groups.length > limit}<span class="mono dim s">+{groups.length - limit} more</span>{/if}
</div>

<style>
  .list { display: flex; flex-direction: column; }
  .r { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto auto; gap: 8px; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--q); }
  .main { display: flex; flex-direction: column; min-width: 0; }
  .t, .why { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .t { font-size: 12.5px; }
  .why, .a, .s { font-size: 10.5px; }
  .acts { display: flex; gap: 6px; align-items: center; }
  .btn.sm { padding: 3px 8px; font-size: 11px; }
  .tag { font-size: 10px; margin-right: 6px; }
</style>
