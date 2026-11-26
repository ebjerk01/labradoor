<script>
  import Lines from '$lab/Lines.svelte';
  import { ago } from '$lab/sdk.js';
  let { data, ctx } = $props();
  const ev = $derived(data.events.filter((e) => e.action === 'login' || e.action === 'login_failed').slice(0, 7));
  const fails = $derived(data.events.filter((e) => e.action === 'login_failed').length);
</script>
<div class="v"><span class="mono big" class:warn={fails}>{fails}</span><span class="mono dim">failed in the last {data.events.length} events</span></div>
<Lines items={ev.map((e) => ({ p: e.action === 'login' ? '●' : '▲', s: e.action === 'login' ? 'ok' : 'warn',
  t: `${e.user?.username || e.context?.username || '?'} · ${ago(Date.parse(e.created) / 1000, ctx.now)} · ${e.client_ip || ''}` }))} />
<style>
  .v { display: flex; align-items: baseline; gap: 8px; }
  .big { font-size: 26px; font-weight: 500; }
  .mono.dim { font-size: 11px; }
</style>
