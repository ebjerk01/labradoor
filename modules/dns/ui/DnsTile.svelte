<script>
  let { data } = $props();
  const s = $derived(data.stats || {});
  const pct = $derived(s.totalQueries ? (100 * s.totalBlocked) / s.totalQueries : 0);
</script>

<div class="t">
  <span class="mono big">{s.totalQueries ?? '–'}</span>
  <span class="cap">queries · <span class="sig">{s.totalBlocked ?? 0} blocked</span> ({pct.toFixed(0)}%) · {s.totalClients ?? 0} clients</span>
</div>

<style>
  .t { display: flex; flex-direction: column; margin-top: auto; gap: 2px; }
  .big { font-size: 30px; font-weight: 500; letter-spacing: -.02em; }
</style>
