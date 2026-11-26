<script>
  // overview section: today's morning summary (only when there is one)
  import SummaryTile from './SummaryTile.svelte';
  let { data, ctx } = $props();
</script>

<SummaryTile {data} {ctx} section={true} />
