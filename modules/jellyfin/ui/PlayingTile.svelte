<script>
  // Wall tile (admin): who is watching what right now. Live only — lab keeps no viewing history.
  import Sessions from './Sessions.svelte';
  let { data, ctx } = $props();
  const playing = $derived(data.sessions.filter((s) => s.playing));
</script>

<button class="lnk body" onclick={() => ctx.open('jellyfin')}>
  {#if playing.length}<Sessions sessions={playing} idle={false} />
  {:else}<span class="mono dim s">nobody is watching · {data.counts.MovieCount ?? '–'} movies · {data.counts.SeriesCount ?? '–'} series</span>{/if}
</button>

<style>
  .body { display: flex; flex-direction: column; overflow: hidden; flex: 1; text-align: left; }
  .s { font-size: 11.5px; margin-top: auto; }
</style>
