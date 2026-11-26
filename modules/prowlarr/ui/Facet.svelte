<script>
  // Facet on the prowlarr service: one row per indexer (priority only for the owner — it comes from the config).
  import Section from '$lab/Section.svelte';
  import Lines from '$lab/Lines.svelte';
  import Table from '$lab/Table.svelte';
  import { rel, when } from '$lab/sdk.js';
  let { object, data, ctx } = $props();
  const d = $derived(data);
  let sort = $state(null);
  const columns = $derived([
    { key: 'name', label: 'indexer', render: nameCell },
    ...(d?.full ? [{ key: 'priority', label: 'priority', align: 'right', dim: true, format: (v) => v ?? '–' }] : []),
    { key: 'queries', label: 'queries', align: 'right', desc: true, format: (v) => v ?? '–' },
    { key: 'grabs', label: 'grabs', align: 'right', desc: true, format: (v) => v ?? '–' },
    { key: 'failPct', label: 'failed', align: 'right', desc: true, format: (v) => (v != null ? `${Math.round(v)}%` : '–') },
    { key: 'ms', label: 'ms', align: 'right', dim: true, phone: false, format: (v) => v ?? '–' },
  ]);
</script>

{#snippet nameCell(x)}
  <span title={x.disabledTill ? `backed off until ${when(x.disabledTill)}, failing since ${rel(x.failingSince, ctx.now)}` : x.name}>
    {x.name}{#if x.disabledTill && x.disabledTill > ctx.now}<span class="bad"> · off {rel(x.disabledTill, ctx.now)}</span>{/if}
  </span>
{/snippet}

{#if object.id === 'prowlarr' && d}
  <Section title="indexers · 7d" src="prowlarr {d.version ? 'v' + d.version : ''}">
    <Table rows={d.indexers} key="id" {columns} bind:sort status={(x) => x.status} muted={(x) => x.status === 'off'} label="indexers" empty="no indexers" />
    {#if !d.full && ctx.role !== 'owner'}<span class="mono dim s">priorities + enabled flags come from the indexer config: owner only</span>{/if}
    {#if d.apps.length}<span class="mono dim s">{d.apps.map((a) => `${a.userAgent} ${a.numberOfQueries}q/${a.numberOfGrabs}g`).join(' · ')}</span>{/if}
  </Section>
  <Section title="health" src="prowlarr">
    <Lines items={d.health.map((h) => ({ p: h.type === 'error' ? '■' : '▲', s: h.type === 'error' ? 'bad' : 'warn', t: h.message }))} empty="● all checks pass" />
  </Section>
{/if}

<style>
  .s { font-size: 10.5px; }
</style>
