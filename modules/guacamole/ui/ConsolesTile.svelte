<script>
  // Guacamole: active sessions now + where; connection count.
  import { objectFor } from './guac.js';
  let { data, ctx } = $props();
  const act = $derived(data.connections.filter((c) => c.active));
  const n = $derived(act.reduce((s, c) => s + c.active, 0));
</script>

<div class="v"><span class="mono big" class:sig={n}>{n}</span><span class="mono dim">sessions · {data.connections.length} consoles</span></div>
<div class="l">
  {#each act as c (c.id)}<button class="lnk mono" onclick={() => ctx.open(objectFor(c, ctx))}>● {objectFor(c, ctx)} <span class="dim">{c.protocol}</span></button>{/each}
</div>

<style>
  .v { display: flex; align-items: baseline; gap: 8px; font-size: 11px; }
  .big { font-size: 24px; font-weight: 500; }
  .l { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; overflow: hidden; }
  .lnk { font-size: 11px; color: var(--sig); }
</style>
