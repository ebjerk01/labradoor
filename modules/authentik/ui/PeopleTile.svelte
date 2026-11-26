<script>
  import { ago } from '$lab/sdk.js';
  import { humans } from './ak.js';
  let { data, ctx } = $props();
  const ps = $derived(humans(data.users).slice().sort((a, b) => (Date.parse(b.last_login || 0) || 0) - (Date.parse(a.last_login || 0) || 0)));
</script>
<div class="v"><span class="mono big">{ps.filter((u) => u.is_active).length}</span><span class="mono dim">people · {data.groups.length} groups</span></div>
<div class="l">
  {#each ps.slice(0, 6) as u}
    <button class="r lnk" onclick={() => ctx.open(`user:${u.username}`)}><span class={u.is_active ? 'ok' : 'off'}>●</span><span>{u.name || u.username}</span><span class="mono dim">{u.last_login ? ago(Date.parse(u.last_login) / 1000, ctx.now) : '–'}</span></button>
  {/each}
</div>
<style>
  .v { display: flex; align-items: baseline; gap: 8px; }
  .big { font-size: 26px; font-weight: 500; }
  .l { display: flex; flex-direction: column; overflow: hidden; }
  .r { display: grid; grid-template-columns: 12px 1fr auto; gap: 8px; font-size: 12.5px; padding: 2px 0; }
  .r .ok, .r .off { font-size: 9px; line-height: 18px; }
  .mono.dim { font-size: 11px; }
</style>
