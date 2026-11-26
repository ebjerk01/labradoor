<script>
  // AD: enabled accounts by time to password expiry (soonest first); never-expiring ones are counted, not listed.
  import { pwLeft, pwState, expiryDays } from './ad.js';
  import { statusVar } from '$lab/sdk.js';
  let { data, ctx } = $props();
  const days = $derived(expiryDays(ctx));
  const en = $derived(data.users.filter((u) => u.enabled));
  const key = (u) => (u.mustChange ? -1e12 : pwLeft(u));
  const rows = $derived(en.filter((u) => u.mustChange || pwLeft(u) != null).sort((a, b) => key(a) - key(b)));
  const soon = $derived(rows.filter((u) => pwState(u, days).s).length);
  const never = $derived(en.length - rows.length);
</script>

<div class="v"><span class="mono big" class:warn={soon}>{soon}</span><span class="mono dim">expire &lt; {days}d or must change · {never} never expire</span></div>
<div class="l">
  {#each rows.slice(0, 6) as u (u.dn)}
    {@const p = pwState(u, days)}
    <button class="r lnk" onclick={() => ctx.open(`aduser:${u.sam}`)}>
      <span class="mono" style:color={statusVar(p.s || 'ok')}>{p.s === 'bad' ? '■' : p.s ? '▲' : '●'}</span><span>{u.sam}</span><span class="mono dim">{p.t}</span>
    </button>
  {:else}<span class="mono dim">no expiring passwords</span>{/each}
</div>

<style>
  .v { display: flex; align-items: baseline; gap: 8px; }
  .big { font-size: 26px; font-weight: 500; }
  .warn { color: var(--warn); }
  .mono.dim { font-size: 11px; }
  .l { display: flex; flex-direction: column; overflow: hidden; }
  .r { display: grid; grid-template-columns: 12px 1fr auto; gap: 8px; font-size: 12.5px; padding: 2px 0; text-align: left; }
</style>
