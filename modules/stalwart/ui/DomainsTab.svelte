<script>
  // Domains: DKIM keys and their rotation, DNS/certificate management mode, the DNS records Stalwart wants published.
  import { untrack } from 'svelte';
  import Table from '$lab/Table.svelte';
  import Lazy from '$lab/Lazy.svelte';
  import { lazy, rel, when } from '$lab/sdk.js';
  import { secs } from './sw.js';
  let { data, ctx } = $props();
  let open = $state(untrack(() => (data.domains.length === 1 ? data.domains[0].id : null)));
  const dns = lazy(() => ctx, () => (open ? `/api/domains/${open}/dns` : null));
  let rtype = $state('');
  const types = $derived(dns.data ? [...new Set(dns.data.records.map((r) => r.type))].sort() : []);
</script>

<Table rows={data.domains} key="id" label="domains" status={(x) => (x.enabled ? 'ok' : 'off')} onrow={(x) => (open = x.id)}
  columns={[
    { key: 'name', label: 'domain' },
    { key: 'accounts', label: 'accounts', align: 'right' },
    { key: 'dkim', label: 'dkim', get: (x) => x.dkim.map((k) => `${k.selector} (${k.stage})`).join(', '), sort: false },
    { key: 'dkimMode', label: 'dkim keys', dim: true, phone: false },
    { key: 'dns', label: 'dns', dim: true, phone: false },
    { key: 'cert', label: 'certificate', dim: true, phone: false },
  ]} />

{#if data.certificates.length || data.tasks.length}
  <div class="mono dim s">
    {#each data.certificates as c (c.id)}<div>certificate {(c.names || []).join(', ')} · {when(secs(c.notBefore))} → {when(secs(c.notAfter))} · {c.issuer}</div>{/each}
    {#each data.tasks as t (t.id)}<div>task {t.type}{t.domain ? ` (${t.domain})` : ''} · {t.status} · due {rel(secs(t.due), ctx.now)}</div>{/each}
    {#each data.domains.flatMap((x) => x.dkim.map((k) => ({ ...k, d: x.name }))) as k (k.d + k.selector)}
      <div>dkim {k.d} {k.selector} · {k.algorithm || ''} {k.stage} · next step {rel(secs(k.next), ctx.now)}</div>
    {/each}
  </div>
{/if}

{#if open}
  <div class="detail">
    <div class="row">
      <span class="cap">DNS records {dns.data?.domain || ''}</span>
      <select class="field s" bind:value={rtype} aria-label="Record type">
        <option value="">all types</option>
        {#each types as t (t)}<option value={t}>{t}</option>{/each}
      </select>
      <span class="mono dim s">what Stalwart wants published{data.domains.find((x) => x.id === open)?.dns === 'Automatic' ? ' (it publishes them itself: DNS management Automatic)' : ''}</span>
    </div>
    <Lazy of={dns} empty="no records">
      {#snippet children(z)}
        <Table rows={z.records.filter((r) => !rtype || r.type === rtype)} key={(r) => `${r.type} ${r.name} ${r.value}`} label="dns records"
          columns={[
            { key: 'type', label: 'type' }, { key: 'name', label: 'name' },
            { key: 'value', label: 'value', render: valCell, sort: false },
          ]} />
      {/snippet}
    </Lazy>
  </div>
{/if}
{#snippet valCell(r)}<span class="mono val">{r.value}</span>{/snippet}

<style>
  .s { font-size: 11px; }
  .detail { border: 1px solid var(--line); border-radius: 4px; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 4px 6px; }
  .val { word-break: break-all; font-size: 10.5px; }
</style>
