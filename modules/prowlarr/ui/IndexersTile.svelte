<script>
  // Wall tile: every indexer as a chip, status = shape + colour.
  import Glyph from '$lab/Glyph.svelte';
  let { data, ctx } = $props();
  const on = $derived(data.indexers.filter((x) => x.status !== 'off'));
  const bad = $derived(on.filter((x) => x.status !== 'ok').length);
</script>

<button class="lnk chips" title="{on.length} indexers{bad ? ` · ${bad} failing` : ' · all answering'}" onclick={() => ctx.open('prowlarr')}>
  {#each on as x (x.id)}
    <span class="chip mono" title="{x.name} · {x.queries ?? 0} queries · {x.grabs ?? 0} grabs · {Math.round(x.failPct || 0)}% failed"><Glyph status={x.status} size={9} />{x.name}</span>
  {/each}
</button>

<style>
  .chips { display: flex; flex-wrap: wrap; gap: 4px 10px; overflow: hidden; flex: 1; align-content: flex-start; }
  .chip { display: inline-flex; gap: 4px; align-items: baseline; font-size: 11px; white-space: nowrap; }
</style>
