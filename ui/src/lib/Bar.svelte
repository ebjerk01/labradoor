<script>
  let { value = 0, color = 'var(--ink)', height = 4, label = '' } = $props();
  const w = $derived(Math.max(0, Math.min(100, Number(value) || 0)));
</script>

<span class="bar" style:height="{height}px" title={label}><span class="fill grow" style:width="{w}%" style:background={color}></span></span>

<style>
  .bar { display: block; flex: 1; background: var(--track); min-width: 30px; }
  .fill { display: block; height: 100%; }
</style>
