<script>
  // AD: most recently changed objects (whenChanged; a logon that updates lastLogonTimestamp counts as a change).
  import { ago } from '$lab/sdk.js';
  import { recent, computerId } from './ad.js';
  let { data, ctx } = $props();
  const rows = $derived(recent(data, 7));
  const open = (x) => (x.c ? ctx.open(computerId(x.c, ctx).id) : x.id && ctx.open(x.id));
</script>

<div class="v"><span class="mono dim">last changes in {data.domain}</span></div>
<div class="l">
  {#each rows as x (x.k + x.name)}
    <button class="r lnk" onclick={() => open(x)} disabled={!x.id && !x.c}><span class="mono k">{x.k}</span><span class="nm">{x.name}</span><span class="mono dim">{ago(x.t, ctx.now)}</span></button>
  {/each}
</div>

<style>
  .v { font-size: 11px; }
  .l { display: flex; flex-direction: column; overflow: hidden; }
  .r { display: grid; grid-template-columns: 64px 1fr auto; gap: 8px; font-size: 12.5px; padding: 2px 0; text-align: left; }
  .k { font-size: 10.5px; color: var(--sig); }
  .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mono.dim { font-size: 11px; }
</style>
