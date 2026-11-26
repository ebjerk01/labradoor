<script>
  import { sparkPoints } from './fmt.js';
  let { values = [], color = 'var(--dim)', fixed100 = false, height = 18, width = '100%', area = false } = $props();
  const pts = $derived(sparkPoints(values, { fixed100 }));
</script>

<svg {width} {height} viewBox="0 0 80 18" preserveAspectRatio="none" aria-hidden="true" class="spark">
  {#if area && pts}<path d="M0,18 L{pts.split(' ').join(' L')} L80,18 Z" class="area"></path>{/if}
  <polyline points={pts} style:stroke={color}></polyline>
</svg>

<style>
  .spark { display: block; }
  polyline { fill: none; stroke-width: 1.2; vector-effect: non-scaling-stroke; }
  .area { fill: var(--sig2); fill-opacity: .18; stroke: none; }
</style>
