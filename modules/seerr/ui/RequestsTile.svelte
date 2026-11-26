<script>
  // Wall tile (admin): pending first (approve/decline), then the latest requests from everyone.
  import RequestRow from './RequestRow.svelte';
  let { data, ctx } = $props();
  const list = $derived([...(data.pending || []), ...(data.all || []).filter((r) => r.status !== 'pending')]);
</script>

<span class="mono dim s">{data.counts?.pending ?? 0} pending · {data.counts?.processing ?? 0} processing · {data.counts?.total ?? 0} total</span>
<div class="l">
  {#each list.slice(0, 6) as r (r.id)}<RequestRow {r} {ctx} by manage />{:else}<span class="mono dim s">no requests</span>{/each}
</div>

<style>
  .l { display: flex; flex-direction: column; overflow: hidden; }
  .s { font-size: 10.5px; }
</style>
