<script>
  // Interactive search: what the indexers offer for one episode / season / movie (it reads the indexers, it grabs
  // nothing), and a grab button per release. Rejected releases are listed too; grabbing one asks twice.
  import { lazy, clip, bytes } from '../sdk.js';
  import Lazy from '../Lazy.svelte';
  import Table from '../Table.svelte';
  import ActionButton from '../ActionButton.svelte';
  import { A, releaseRows } from './logic.js';
  let { ctx, query, onclose } = $props();
  // follow: false — a grab (or any other write) must not run the slow indexer search again
  const rel = lazy(() => ctx, () => `${A}/release`, { query: () => query, pick: releaseRows, follow: false });
  const columns = [
    { key: 'title', label: 'release', get: (r) => r.title, sort: false, render: title },
    { key: 'indexer', label: 'indexer', dim: true, phone: false },
    { key: 'quality', label: 'quality', dim: true },
    { key: 'size', label: 'size', align: 'right', desc: true, format: (v) => bytes(v) },
    { key: 'age', label: 'age', align: 'right', phone: false, format: (v) => (v == null ? '–' : v < 2 ? `${Math.round(v * 24)}h` : `${Math.round(v)}d`) },
    { key: 'seeders', label: 'seeds', align: 'right', desc: true, phone: false, format: (v) => v ?? '–' },
    { key: 'score', label: 'score', align: 'right', desc: true, phone: false },
    { key: 'grab', label: '', sort: false, render: grab },
  ];
</script>

{#snippet title(r)}<span title="{r.title}{r.why ? ` — ${r.why}` : ''}">{clip(r.title, 70)}{#if r.rejected}<span class="dim"> · {clip(r.why, 50)}</span>{/if}</span>{/snippet}
{#snippet grab(r)}
  <ActionButton {ctx} path="{A}/release" body={{ guid: r.guid, indexerId: r.indexerId }} label="grab {clip(r.title, 40)}" icon="download" small
    confirm={r.rejected ? `grab despite: ${clip(r.why, 60)}?` : false} title={r.rejected ? `rejected: ${r.why}` : `send to the download client`}>grab</ActionButton>
{/snippet}

<div class="rl">
  <Lazy of={rel} empty="no releases found">
    {#snippet children(list)}
      <Table rows={list} key="guid" {columns} status={(r) => (r.rejected ? 'warn' : 'ok')} label="releases" minWidth={520} />
    {/snippet}
  </Lazy>
  <div class="bar"><button class="btn sm" onclick={() => onclose?.()}>close search</button><span class="mono dim s">searching asks every indexer: up to a minute or more (the gateway waits 95 s)</span></div>
</div>

<style>
  .rl { display: flex; flex-direction: column; gap: 6px; padding: 6px 0; }
  .bar { display: flex; gap: 10px; align-items: center; }
  .s { font-size: 10.5px; }
  .btn.sm { padding: 3px 8px; font-size: 11px; }
</style>
