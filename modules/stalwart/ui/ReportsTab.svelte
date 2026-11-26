<script>
  // Reports: DMARC / TLS-RPT / ARF received from other servers, and the ones Stalwart will send ("out").
  import Table from '$lab/Table.svelte';
  import Lazy from '$lab/Lazy.svelte';
  import { lazy, rel, when, clip } from '$lab/sdk.js';
  import { KINDS, reportCount, reportStatus, secs } from './sw.js';
  let { data, ctx } = $props();
  let kind = $state('dmarc');
  let open = $state(null);
  const list = lazy(() => ctx, () => '/api/reports', { query: () => ({ kind }), keep: true });
  const one = lazy(() => ctx, () => (open ? `/api/reports/${kind}/${open}` : null));
  const pick = (k) => { kind = k; open = null; };
  const records = $derived(one.data?.report?.records ? Object.values(one.data.report.records) : []);
  const policies = $derived(one.data?.report?.policies ? Object.values(one.data.report.policies) : []);
</script>

<div class="seg" role="group" aria-label="Report kind">
  {#each KINDS as k (k.id)}<button aria-pressed={kind === k.id} onclick={() => pick(k.id)}>{k.label} <span class="faint">{reportCount(data, k.id)}</span></button>{/each}
</div>
<Lazy of={list} empty="no reports">
  {#snippet children(r)}
    <Table rows={r.reports} key="id" label="reports" status={reportStatus} onrow={(x) => (open = open === x.id ? null : x.id)}
      empty={kind.endsWith('-out') ? 'nothing waiting to be sent' : 'no reports received'}
      columns={kind.startsWith('arf') ? [
        { key: 'from', label: 'from' }, { key: 'feedbackType', label: 'type' }, { key: 'sourceIp', label: 'source IP', dim: true },
        { key: 'reported', label: 'domains', get: (x) => (x.reported || []).join(', '), phone: false },
        { key: 'received', label: 'received', desc: true, get: (x) => secs(x.received) || 0, format: (v) => rel(v, ctx.now) },
      ] : [
        { key: 'org', label: 'reporter', get: (x) => x.org || x.from || '' },
        { key: 'domain', label: 'about', get: (x) => x.policyDomain || x.domain || '', dim: true },
        { key: 'range', label: 'period', get: (x) => secs(x.begin) || 0, format: (v, x) => `${when(v)} → ${when(secs(x.end))}`, phone: false },
        kind.startsWith('dmarc') ? { key: 'messages', label: 'msgs', align: 'right', desc: true } : { key: 'ok', label: 'ok sessions', align: 'right', desc: true },
        { key: 'failed', label: 'failed', align: 'right', desc: true },
        kind.endsWith('-out') ? { key: 'deliver', label: 'sent', get: (x) => secs(x.deliver) || 0, format: (v) => rel(v, ctx.now) }
          : { key: 'received', label: 'received', desc: true, get: (x) => secs(x.received) || 0, format: (v) => rel(v, ctx.now) },
      ]} />
  {/snippet}
</Lazy>
{#if open}
  <div class="detail">
    <Lazy of={one}>
      {#snippet children(d)}
        <div class="mono head">{d.summary.subject || d.summary.org || d.summary.domain} · {d.summary.from || ''}{d.rua?.length ? ` → ${d.rua.join(', ')}` : ''}</div>
        {#if records.length}
          <Table rows={records} key={(x) => `${x.sourceIp}-${x.headerFrom}-${x.count}`} label="records" status={(x) => (x.evaluatedDkim === 'pass' || x.evaluatedSpf === 'pass' ? 'ok' : 'warn')}
            columns={[
              { key: 'sourceIp', label: 'source IP' }, { key: 'count', label: 'msgs', align: 'right', desc: true },
              { key: 'headerFrom', label: 'header from', dim: true }, { key: 'evaluatedDkim', label: 'dkim' },
              { key: 'evaluatedSpf', label: 'spf' }, { key: 'evaluatedDisposition', label: 'disposition', phone: false },
            ]} />
        {:else if policies.length}
          <Table rows={policies} key={(x) => `${x.policyType}-${x.policyDomain}`} label="policies" status={(x) => (x.totalFailedSessions ? 'warn' : 'ok')}
            columns={[
              { key: 'policyDomain', label: 'domain' }, { key: 'policyType', label: 'policy' },
              { key: 'totalSuccessfulSessions', label: 'ok', align: 'right' }, { key: 'totalFailedSessions', label: 'failed', align: 'right' },
              { key: 'mx', label: 'mx', get: (x) => Object.keys(x.mxHosts || {}).join(', '), dim: true, phone: false },
            ]} />
        {:else}
          <pre class="mono raw">{clip(JSON.stringify(d.report, null, 1), 4000)}</pre>
        {/if}
      {/snippet}
    </Lazy>
  </div>
{/if}

<style>
  .seg button { padding: 5px 9px; font-size: 11px; }
  .detail { border: 1px solid var(--line); border-radius: 4px; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
  .head { font-size: 11.5px; }
  .raw { font-size: 10.5px; white-space: pre-wrap; max-height: 360px; overflow: auto; margin: 0; }
</style>
