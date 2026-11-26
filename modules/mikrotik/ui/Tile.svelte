<script>
  import { dur } from '$lab/sdk.js';
  let { data } = $props();
  const up = $derived((data?.ports ?? []).filter((p) => p.running).length);
</script>

{#if data}
<div class="t">
  <span class="mono big">{up}<span class="dim">/{data.ports.length}</span></span>
  <span class="cap">ports up · <span class="sig">{data.health.poeW != null ? `${data.health.poeW} W poe` : data.identity}</span>{data.health.temp != null ? ` · ${data.health.temp}°C` : ''} · up {dur(data.sys.uptime)}</span>
</div>
{/if}

<style>
  .t { display: flex; flex-direction: column; margin-top: auto; gap: 2px; }
  .big { font-size: 30px; font-weight: 500; letter-spacing: -.02em; }
</style>
