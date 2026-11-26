<script>
  // Machine objects: a Proxmox guest gets the guest facet, a node the node facet, anything else nothing.
  import GuestFacet from './GuestFacet.svelte';
  import NodeFacet from './NodeFacet.svelte';
  import { guestOf, nodeOf } from './pve.svelte.js';
  let { object, data, ctx } = $props();
  const g = $derived(guestOf(data, object));
  const n = $derived(g ? null : nodeOf(data, object));
</script>

{#if g}
  {#key g.vmid}<GuestFacet {g} {data} {ctx} />{/key}
{:else if n}
  {#key n.node}<NodeFacet {n} {data} {ctx} />{/key}
{/if}
