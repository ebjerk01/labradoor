<script>
  // Cluster at a glance: quorum, then one row per node (cpu, ram, guests). Click a node to open it.
  import Glyph from '$lab/Glyph.svelte';
  import Bar from '$lab/Bar.svelte';
  import { memLevel, statusVar } from '$lab/fmt.js';
  import { nodeId, isGuest } from './pve.svelte.js';
  let { data, ctx } = $props();
  const cl = $derived(data.cluster.find((x) => x.type === 'cluster'));
  const nodes = $derived(data.resources.filter((r) => r.type === 'node').sort((a, b) => nodeId(a.node).localeCompare(nodeId(b.node))));
  const guests = (n) => data.resources.filter((r) => isGuest(r) && r.node === n);
  const memC = (v) => (memLevel(v) === 'ok' ? 'var(--sig)' : statusVar(memLevel(v)));
</script>

<div class="h"><Glyph status={cl?.quorate ? 'ok' : 'bad'} /><span class="mono dim">{cl?.name} · {cl?.quorate ? 'quorate' : 'NO QUORUM'}</span></div>
<div class="rows">
  {#each nodes as n (n.node)}
    {@const gs = guests(n.node)}
    {@const mem = n.maxmem ? (100 * n.mem) / n.maxmem : 0}
    <button class="r" onclick={() => ctx.open(nodeId(n.node))} aria-label={nodeId(n.node)}>
      <Glyph status={n.status === 'online' ? 'ok' : 'bad'} />
      <span class="mono nm">{nodeId(n.node)}</span>
      <Bar value={(n.cpu || 0) * 100} color="var(--sig)" label="cpu {Math.round((n.cpu || 0) * 100)}%" />
      <Bar value={mem} color={memC(mem)} label="ram {Math.round(mem)}%" />
      <span class="mono dim g">{gs.filter((g) => g.status === 'running').length}/{gs.length}</span>
    </button>
  {/each}
</div>

<style>
  .h { display: flex; align-items: center; gap: 6px; font-size: 11px; }
  .rows { display: flex; flex-direction: column; gap: 2px; }
  .r { display: grid; grid-template-columns: 12px 62px 1fr 1fr 34px; gap: 8px; align-items: center; border: none; background: none; padding: 1px 0; font-size: 11px; text-align: left; }
  .r:hover { background: var(--raise); }
  .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .g { text-align: right; }
</style>
