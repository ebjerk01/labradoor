<script>
  // the datastore: % used + trend, estimate, job glyphs. Click → the pbs object.
  import Spark from '$lab/Spark.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import { bytes } from '$lab/sdk.js';
  import { hostOf, jobsOf, jobOk, usageLevel } from './pbs.svelte.js';
  let { data, ctx } = $props();
  const h = $derived(hostOf(data));
  const u = $derived(h?.total ? h.used / h.total : 0);
  const left = $derived(h?.['estimated-full-date'] > 0 ? Math.round((h['estimated-full-date'] - data.at) / 86400) : null);
  const jobs = $derived(jobsOf(data).filter((j) => j.store === data.store));
</script>

<button class="t" onclick={() => ctx.open('pbs')} aria-label="pbs">
  {#if h}
    <div class="v">
      <span class="mono big" class:warn={usageLevel(u) === 'warn'} class:bad={usageLevel(u) === 'bad'}>{Math.round(u * 100)}%</span>
      <span class="mono dim">{bytes(h.avail, 0)} free{left != null ? ` · full ~${left}d` : ''}</span>
    </div>
    <Spark values={(h.history || []).filter((x) => x != null).map((x) => x * 100)} color="var(--sig)" height={18} area />
    <div class="j">
      {#each jobs as j (j.id)}<span class="mono dim"><Glyph status={!j.state ? 'unknown' : jobOk(j.raw) ? 'ok' : j.kind === 'sync' && !j.schedule ? 'off' : 'warn'} /> {j.kind}</span>{/each}
    </div>
  {:else}<span class="mono bad">{data.store}: missing</span>{/if}
</button>

<style>
  .t { flex: 1; display: flex; flex-direction: column; gap: 4px; border: none; background: none; padding: 0; text-align: left; min-width: 0; }
  .v { display: flex; align-items: baseline; gap: 8px; font-size: 11px; }
  .big { font-size: 24px; font-weight: 500; }
  .j { display: flex; gap: 10px; font-size: 10.5px; flex-wrap: wrap; }
</style>
