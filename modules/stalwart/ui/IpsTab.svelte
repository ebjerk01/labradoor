<script>
  // Blocked IPs (Stalwart's auto-ban: port scanning, auth failures …) with unblock (owner), and the allowed list,
  // read-only: the reverse proxy's address lives there, and removing it lets auto-ban lock out every web host behind it.
  import Table from '$lab/Table.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { rel, when } from '$lab/sdk.js';
  import { secs } from './sw.js';
  let { data, ctx } = $props();
  let q = $state('');
  let reason = $state('');
  const reasons = $derived([...new Set(data.blocked.map((b) => b.reason))].sort());
  const rows = $derived(data.blocked.filter((b) => (!q || b.address.includes(q.trim())) && (!reason || b.reason === reason)));
</script>

<div class="tools">
  <input class="field mono" placeholder="filter address" bind:value={q} aria-label="Filter address" />
  <select class="field" bind:value={reason} aria-label="Reason">
    <option value="">all reasons</option>
    {#each reasons as r (r)}<option value={r}>{r} ({data.blocked.filter((b) => b.reason === r).length})</option>{/each}
  </select>
  <span class="mono dim s">{rows.length} of {data.blocked.length} blocked · bans are permanent unless they expire</span>
</div>
<Table rows={rows} key="id" label="blocked IPs" status={() => 'bad'} empty="nothing blocked"
  columns={[
    { key: 'address', label: 'address' },
    { key: 'reason', label: 'reason', dim: true },
    { key: 'created', label: 'blocked', desc: true, get: (b) => secs(b.created) || 0, format: (v) => rel(v, ctx.now) },
    { key: 'expires', label: 'expires', get: (b) => secs(b.expires) || 0, format: (v) => (v ? rel(v, ctx.now) : 'never'), dim: true, phone: false },
    { key: 'act', label: '', sort: false, render: unblock },
  ]} />
{#snippet unblock(b)}<ActionButton {ctx} method="DELETE" path={`/api/blocked/${b.id}`} label={`unblock ${b.address}`} confirm="unblock? click again" small>unblock</ActionButton>{/snippet}

<div class="cap">allowed (never banned)</div>
<Table rows={data.allowed} key="id" label="allowed IPs" status={() => 'ok'} empty="no allowed IPs"
  columns={[
    { key: 'address', label: 'address' },
    { key: 'reason', label: 'why' },
    { key: 'created', label: 'since', get: (b) => secs(b.created) || 0, format: (v) => when(v), dim: true },
  ]} />
<span class="mono dim s">read-only here: change the allowed list in Stalwart itself (removing the reverse proxy's address lets auto-ban cut off every web host behind it)</span>

<style>
  .tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 12px; }
  .s { font-size: 11px; }
</style>
