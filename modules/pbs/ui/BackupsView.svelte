<script>
  // ~/backups — every backup group in the datastore, stalest first: which guest, how many kept, how fresh.
  // Groups whose guest no longer exists (or lives elsewhere) show as "orphan". Click → the guest's object.
  import Table from '$lab/Table.svelte';
  import { ago, bytes } from '$lab/sdk.js';
  import { STALE_S, groupObject, hostOf } from './pbs.svelte.js';
  let { data, ctx } = $props();

  let q = $state('');
  let sort = $state(null);
  const h = $derived(hostOf(data));
  const RANK = { warn: 0, ok: 1, off: 2 };
  const rows = $derived((data.groups || []).map((g) => {
    const obj = groupObject(g['backup-type'], g['backup-id'], ctx);
    const age = data.at - g['last-backup'];
    return { g, obj, age, group: `${g['backup-type']}/${g['backup-id']}`, name: obj || g.comment || 'orphan',
      st: !obj ? 'off' : age > STALE_S ? 'warn' : 'ok' };
  }).filter((r) => !q || `${r.obj || ''} ${r.group} ${r.g.comment || ''}`.toLowerCase().includes(q.toLowerCase())));
  const ordered = $derived([...rows].sort((a, b) => (RANK[a.st] - RANK[b.st]) || b.age - a.age));
  const stale = $derived(rows.filter((r) => r.st === 'warn').length);
  const columns = [
    { key: 'name', label: 'guest', get: (r) => r.name },
    { key: 'group', label: 'group', dim: true },
    { key: 'last', label: 'last', get: (r) => -r.age, format: (_, r) => `${ago(r.g['last-backup'], data.at)} ago`, desc: true },
    { key: 'kept', label: 'kept', get: (r) => r.g['backup-count'], align: 'right' },
    { key: 'owner', label: 'owner', get: (r) => r.g.owner, dim: true, phone: false },
  ];
</script>

{#if data}
<div class="bar">
  <input class="field s" placeholder="$ grep guest" aria-label="Filter backups" bind:value={q} />
  <span class="mono dim note">{rows.length} groups · {stale ? `${stale} older than 36 h · ` : ''}{h ? `${data.store} ${Math.round((100 * h.used) / h.total)}% · ${bytes(h.avail, 0)} free` : ''}</span>
</div>
<Table rows={ordered} key="group" {ctx} object={(r) => r.obj} status={(r) => r.st} bind:sort label="backup groups" {columns} empty="no backups" />
{:else}
  <div class="pad mono dim"><span class="spin"></span> pbs</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .s { max-width: 220px; padding: 6px 10px; font-size: 12px; }
  .note { flex: 1; font-size: 11px; }
  @media (max-width: 860px) { .bar { padding: 12px 16px; } }
</style>
