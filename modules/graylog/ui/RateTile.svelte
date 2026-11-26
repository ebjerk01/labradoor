<script>
  import Spark from '$lab/Spark.svelte';
  import { short } from './gl.js';
  let { data } = $props();
</script>
<div class="v"><span class="mono big">{short(data.perMin)}</span><span class="mono dim">/min · {short(data.perHour)} 1h</span></div>
<Spark values={data.rate} color="var(--sig)" height={26} area />
<style>
  .v { display: flex; align-items: baseline; gap: 8px; }
  .big { font-size: 26px; font-weight: 500; letter-spacing: -.03em; }
  .mono.dim { font-size: 11px; }
</style>
