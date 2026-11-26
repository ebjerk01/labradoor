<script>
  // Outgoing queue: every message with its recipients' state; retry now (admin), cancel delivery (owner),
  // pause / resume the whole queue (owner).
  import Table from '$lab/Table.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { bytes, rel, clip } from '$lab/sdk.js';
  import { QSTATUS, secs } from './sw.js';
  let { data, ctx } = $props();
  let open = $state(null);
  const msg = $derived(open ? data.queue.find((m) => m.id === open) : null);
</script>

<div class="tools">
  <span class="mono dim">{data.counts.queue} queued · {data.counts.failing} failing</span>
  <ActionButton {ctx} path="/api/queue/pause" label="pause queue" icon="close" confirm="pause all outgoing delivery? click again" small />
  <ActionButton {ctx} path="/api/queue/resume" label="resume queue" icon="play" small />
</div>
<Table rows={data.queue} key="id" label="queued messages" status={(m) => QSTATUS[m.status] || 'unknown'} onrow={(m) => (open = open === m.id ? null : m.id)}
  empty="the queue is empty: everything was delivered"
  columns={[
    { key: 'from', label: 'from', format: (v) => clip(v, 40) },
    { key: 'to', label: 'to', get: (m) => m.recipients.map((r) => r.to).join(', '), format: (v) => clip(v, 60) },
    { key: 'status', label: 'state', dim: true, phone: false },
    { key: 'retries', label: 'tries', align: 'right', desc: true },
    { key: 'size', label: 'size', align: 'right', desc: true, format: (v) => bytes(v), phone: false },
    { key: 'created', label: 'queued', desc: true, get: (m) => secs(m.created) || 0, format: (v) => rel(v, ctx.now) },
    { key: 'nextRetry', label: 'next try', get: (m) => secs(m.nextRetry) || 0, format: (v) => (v ? rel(v, ctx.now) : '–'), phone: false },
  ]} />
{#if msg}
  <div class="detail">
    <div class="head mono">
      <span>message {msg.id} · from {msg.from} · {bytes(msg.size)}{msg.fromIp ? ` · from ${msg.fromIp}:${msg.port}` : ''}</span>
      <span class="acts">
        <ActionButton {ctx} path={`/api/queue/${msg.id}/retry`} label="retry now" icon="restart" small />
        <ActionButton {ctx} method="DELETE" path={`/api/queue/${msg.id}`} label={`cancel delivery to ${msg.recipients.length} recipient(s)`} icon="close"
          confirm="cancel delivery? the message is deleted. click again" small done={() => { open = null; }} />
      </span>
    </div>
    {#each msg.recipients as r (r.to)}
      <div class="rc mono"><b>{r.to}</b> <span class="dim">{r.status} · {r.retries} tries · queue {r.queue || '–'}{r.retryDue ? ` · retry ${rel(secs(r.retryDue), ctx.now)}` : ''}</span>
        {#if r.detail}<div class="err">{r.detail}</div>{/if}</div>
    {/each}
  </div>
{/if}

<style>
  .tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 11px; }
  .detail { border: 1px solid var(--line); border-radius: 4px; padding: 10px; display: flex; flex-direction: column; gap: 6px; font-size: 11.5px; }
  .head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; }
  .acts { display: flex; gap: 6px; }
  .err { color: var(--warn); word-break: break-all; }
</style>
