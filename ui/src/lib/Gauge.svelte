<script>
  let { value = 0, color = 'var(--ink)', size = 78 } = $props();
  const C = 2 * Math.PI * 36;
  const dash = $derived(`${(Math.max(0, Math.min(100, value || 0)) / 100) * C} ${C}`);
</script>

<svg width={size} height={size} viewBox="0 0 88 88" aria-hidden="true">
  <circle cx="44" cy="44" r="36" class="track"></circle>
  <circle cx="44" cy="44" r="36" transform="rotate(-90 44 44)" class="val" style:stroke={color} style:stroke-dasharray={dash}></circle>
</svg>

<style>
  circle { fill: none; stroke-width: 8; }
  .track { stroke: var(--track); }
  .val { transition: stroke-dasharray .8s cubic-bezier(.2, .8, .2, 1); }
</style>
