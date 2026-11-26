<script>
  // Dashboard tile: headline $ saved + tokens/calls below.
  let { data } = $props();
</script>

<span class="mono big" class:ok={data.status?.ok} class:dim={!data.status?.ok}>{data.disp?.cost ?? '$0.00'}</span>
<span class="mono dim s">{data.disp?.tokens ?? '0'} tok · {data.disp?.calls ?? '0'} calls saved</span>

<style>
  .big { font-size: 32px; font-weight: 500; margin-top: auto; }
  .s { font-size: 11px; }
</style>
