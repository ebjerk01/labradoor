<script>
  import { ago } from '$lab/sdk.js';
  let { data, ctx } = $props();
</script>

<span class="mono big" class:ok={data.status?.ok} class:bad={!data.status?.ok}>{data.status?.ok ? 'up' : 'down'}</span>
<span class="mono dim s">{data.count} items · {ago(data.at, ctx.now)} ago</span>

<style>
  .big { font-size: 34px; font-weight: 500; margin-top: auto; }
  .s { font-size: 11px; }
</style>
