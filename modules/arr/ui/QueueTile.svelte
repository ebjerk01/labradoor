<script>
  // Wall tile (admin): download pipeline at a glance — speed, queue sizes, the stuck ones.
  import { bits } from '$lab/sdk.js';
  import Glyph from '$lab/Glyph.svelte';
  import { get, stuckGroups } from './media.js';
  let { ctx } = $props();
  const S = $derived(get(ctx, 'sonarr')), R = $derived(get(ctx, 'radarr')), Q = $derived(get(ctx, 'qbit'));
  const stuck = $derived(stuckGroups(ctx).map((g) => ({ ...g, app: g.app === 'sonarr' ? 'tv' : 'mv' }))
    .sort((a, b) => (a.level === b.level ? 0 : a.level === 'bad' ? -1 : 1)));
</script>

<button class="lnk v" onclick={() => ctx.go('media')}>
  {#if Q}<span class="mono big">↓{bits(Q.transfer.dl_info_speed)}</span>{/if}
  <span class="mono dim">{S ? `${S.queue.total} tv` : ''}{R ? ` · ${R.queue.total} movies` : ''}{Q ? ` · ${Q.counts.downloading} active` : ''}</span>
</button>
<div class="l">
  {#each stuck.slice(0, 5) as g (g.app + g.key)}
    <div class="r" title={g.reason}><Glyph status={g.level} size={9} /><span class="mono k">{g.app}</span><span class="t">{g.title}</span></div>
  {:else}
    <span class="mono dim s">● nothing stuck</span>
  {/each}
  {#if stuck.length > 5}<span class="mono dim s">+{stuck.length - 5} more stuck</span>{/if}
</div>

<style>
  .v { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .big { font-size: 26px; font-weight: 500; letter-spacing: -.03em; }
  .v .dim { font-size: 11px; }
  .l { display: flex; flex-direction: column; overflow: hidden; }
  .r { display: grid; grid-template-columns: 12px 18px minmax(0, 1fr); gap: 6px; align-items: baseline; padding: 2px 0; font-size: 12px; }
  .k { font-size: 10px; color: var(--sig); }
  .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .s { font-size: 10.5px; }
</style>
