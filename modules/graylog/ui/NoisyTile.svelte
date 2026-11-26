<script>
  import Bar from '$lab/Bar.svelte';
  import { anyOf, short } from './gl.js';
  import { searchLogs } from './state.svelte.js';
  let { data, ctx } = $props();
  const top = $derived(data.sources.filter((s) => s.n1h).slice(0, 9));
  const max = $derived(Math.max(1, ...top.map((s) => s.n1h)));
  const open = (s) => (s.known ? ctx.open(s.id) : searchLogs(ctx, { q: anyOf('source', [s.src]) }));
</script>
<div class="rows">
  {#each top as s (s.src)}
    <button class="r lnk" onclick={() => open(s)} title={s.known ? `open ${s.id}` : `search ${s.src}`}>
      <span class="mono nm">{s.src}{#if !s.known}<span class="faint"> ?</span>{/if}</span>
      <Bar value={(100 * s.n1h) / max} color="var(--sig2)" />
      <span class="mono n">{short(s.n1h)}</span>
    </button>
  {:else}
    <span class="mono dim">no lines in the last hour</span>
  {/each}
</div>
<style>
  .rows { display: flex; flex-direction: column; gap: 3px; }
  .r { display: grid; grid-template-columns: 120px 1fr 44px; gap: 8px; align-items: center; font-size: 11.5px; }
  .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .n { text-align: right; color: var(--dim); }
</style>
