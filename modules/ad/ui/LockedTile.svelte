<script>
  // AD: locked-out accounts now (and whether lockout is even on: threshold 0 = never locks).
  let { data, ctx } = $props();
  const locked = $derived(data.users.filter((u) => u.locked));
  const th = $derived(data.policy?.lockoutThreshold || 0);
</script>

<div class="v"><span class="mono big" class:bad={locked.length}>{locked.length}</span><span class="mono dim">locked · {th ? `after ${th} bad pw` : 'lockout off'}</span></div>
<div class="l">
  {#each locked as u (u.dn)}<button class="lnk mono" onclick={() => ctx.open(`aduser:${u.sam}`)}>■ {u.sam}</button>{/each}
</div>

<style>
  .v { display: flex; align-items: baseline; gap: 8px; font-size: 11px; }
  .big { font-size: 24px; font-weight: 500; }
  .bad { color: var(--bad); }
  .l { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; overflow: hidden; }
  .lnk { font-size: 11px; color: var(--bad); }
</style>
