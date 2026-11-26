<script>
  import { ICONS } from './icons.js';
  let { name, size = 16, label = '' } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 24 24" role={label ? 'img' : undefined} aria-label={label || undefined}
  aria-hidden={label ? undefined : 'true'} class="icon"><path d={ICONS[name] || ICONS.node}></path></svg>

<style>
  .icon { fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; flex: none; }
</style>
