<script>
  // Wall tile: speeds + how many torrents are in each state.
  import { bits } from '$lab/fmt.js';
  import { STATUS } from './qb.js';
  import Glyph from '$lab/Glyph.svelte';
  let { data, ctx } = $props();
  const x = $derived(data.transfer);
</script>

<button class="lnk v" onclick={() => ctx.open('qbittorrent')}>
  <span class="mono big">↓{bits(x.dl_info_speed)}</span>
  <span class="mono dim">↑{bits(x.up_info_speed)} · {data.torrents.length} torrents</span>
</button>
<div class="st mono">
  {#each Object.entries(data.counts).filter(([, n]) => n) as [g, n] (g)}
    <span><Glyph status={STATUS[g]} size={9} /> {n} {g}</span>
  {/each}
</div>

<style>
  .v { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-top: auto; }
  .big { font-size: 26px; font-weight: 500; letter-spacing: -.03em; }
  .v .dim { font-size: 11px; }
  .st { display: flex; flex-wrap: wrap; gap: 2px 12px; font-size: 11px; color: var(--dim); }
</style>
