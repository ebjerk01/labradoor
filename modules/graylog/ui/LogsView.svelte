<script>
  // ~/logs — the search page; waits for the module's first load (a direct link can land here before it).
  import LogsBody from './LogsBody.svelte';
  let { data, ctx } = $props();
</script>

{#if data}
  <LogsBody {data} {ctx} />
{:else}
  <div class="pad mono dim"><span class="spin"></span> graylog</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
</style>
