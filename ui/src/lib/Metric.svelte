<script>
  // One labelled sparkline row with the current value: used by facets.
  import Spark from './Spark.svelte';
  let { label, values = [], value = '', color = 'var(--ink)', fixed100 = false } = $props();
</script>

<div class="m">
  <span class="mono n">{label}</span>
  <Spark {values} {fixed100} color={color} height={26} area />
  <span class="mono v" style:color={color}>{value}</span>
</div>

<style>
  .m { display: grid; grid-template-columns: 48px 1fr 64px; gap: 10px; align-items: center; }
  .n { font-size: 11px; color: var(--dim); }
  .v { font-size: 13px; text-align: right; }
</style>
