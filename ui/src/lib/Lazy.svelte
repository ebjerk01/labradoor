<script>
  // The states of a lazy() GET in one place: spinner while the first answer is on its way, the error (or why this user
  // may not read it), `empty` for null / [] answers, else children(data). Reference: docs/sdk.md.
  //   <Lazy of={users}>{#snippet children(list)}<Table rows={list} … />{/snippet}</Lazy>
  let { of, empty = 'nothing here', children } = $props();
  const blank = $derived(of.data == null || (Array.isArray(of.data) && !of.data.length));
</script>

{#if of.error && of.data == null}
  <p class="mono s" class:bad={!of.denied} class:dim={!!of.denied}>{of.denied === 'ask' ? '○ owner only' : of.denied ? '○ not allowed' : of.error}</p>
{:else if of.loading && of.data == null}
  <p class="mono s dim"><span class="spin"></span> loading</p>
{:else if blank}
  <p class="mono s dim">{empty}</p>
{:else}
  {@render children?.(of.data)}
{/if}

<style>
  .s { font-size: 11.5px; margin: 0; }
</style>
