<script>
  import Lines from '$lab/Lines.svelte';
  import { ERRORS, anyOf, hm, one, short } from './gl.js';
  import { searchLogs } from './state.svelte.js';
  let { data, ctx } = $props();
  const e = $derived(data.errors);
</script>
<div class="v">
  <button class="lnk mono big" class:bad={e.total} onclick={() => searchLogs(ctx, { q: ERRORS })} title="search errors">{short(e.total)}</button>
  <span class="srcs">
    {#each e.bySrc.slice(0, 4) as [src, n]}
      <button class="lnk mono chip" onclick={() => searchLogs(ctx, { q: `${ERRORS} AND ${anyOf('source', [src])}` })}>{src} <span class="dim">{short(n)}</span></button>
    {/each}
  </span>
</div>
<Lines items={e.lines.slice(0, 5).map((m) => ({ p: `■ ${hm(m.timestamp)}`, s: 'bad', t: one(`${m.source} ${m.application_name || ''}: ${m.message}`, 200) }))}
  empty="no errors in the last hour" />
<style>
  .v { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .big { font-size: 26px; font-weight: 500; letter-spacing: -.03em; }
  .big.bad { color: var(--bad); }
  .srcs { display: flex; flex-wrap: wrap; gap: 4px; overflow: hidden; max-height: 44px; }
  .chip { font-size: 10.5px; padding: 1px 6px; border: 1px solid var(--line); border-radius: 3px; }
</style>
