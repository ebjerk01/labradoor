<script>
  // a machine whose UniFi client carries its name ("npmplus (CT 101, …)" / hostname) gets its network facet
  import ClientFacet from './ClientFacet.svelte';
  import { clientFor } from './uf.js';
  let { object, data, ctx } = $props();
  const c = $derived(clientFor(data, object.id));
</script>

{#if c}<ClientFacet {object} {data} {ctx} client={c} />{/if}
