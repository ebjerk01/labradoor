<script>
  import { mismatch } from './uf.js';
  let { data } = $props();
  const online = $derived(data.clients.filter((c) => c.online));
  const bad = $derived(data.clients.filter(mismatch).length);
</script>

<div class="t">
  <span class="mono big">{online.length}<span class="dim"> online</span></span>
  <span class="cap">{online.filter((c) => !c.wired).length} wifi · {data.clients.filter((c) => c.reserved).length} reserved{#if bad} · <span class="warn">▲ {bad} off-reservation</span>{/if}</span>
</div>

<style>
  .t { display: flex; flex-direction: column; margin-top: auto; gap: 2px; }
  .big { font-size: 30px; font-weight: 500; letter-spacing: -.02em; }
  .big .dim { font-size: 14px; }
</style>
