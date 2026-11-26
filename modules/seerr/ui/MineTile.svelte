<script>
  // Wall tile for everyone: MY requests (the connector filters by the signed-in person) + how far their downloads are.
  import RequestRow from './RequestRow.svelte';
  import { stateOf } from './sr.js';
  let { data, ctx } = $props();
  const mine = $derived(data.mine || []);
  const active = $derived(mine.filter((r) => !['available', 'declined'].includes(stateOf(r).t)).length);
</script>

{#if !data.me?.linked}
  <span class="mono dim s">○ no Seerr account linked to you yet — ask owner.</span>
  <a class="mono s" href={data.me?.public} target="_blank" rel="noopener">seerr.example.com ↗</a>
{:else}
  <div class="v">
    <span class="mono big">{active}</span><span class="mono dim">on the way · {mine.length} requested</span>
    {#if ctx.canGo('seerr-discover')}<button class="lnk mono req" onclick={() => ctx.go('seerr-discover')}>request more →</button>
    {:else}<a class="mono req" href={data.me.public} target="_blank" rel="noopener">request more ↗</a>{/if}
  </div>
  <div class="l">
    {#each mine.slice(0, 6) as r (r.id)}<RequestRow {r} {ctx} />{:else}<span class="mono dim s">nothing requested yet</span>{/each}
  </div>
{/if}

<style>
  .v { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .big { font-size: 26px; font-weight: 500; letter-spacing: -.03em; }
  .v .dim { font-size: 11px; }
  .req { margin-left: auto; font-size: 11px; color: var(--sig); }
  .l { display: flex; flex-direction: column; overflow: hidden; }
  .s { font-size: 11.5px; }
</style>
