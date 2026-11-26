<script>
  // ~/cloudflare — DNS records (+ proxied), Access apps and policies. DNS edits: admin; deletes + policy edits: owner.
  import Table from '$lab/Table.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { ago, act } from '$lab/sdk.js';
  import { refreshSlow, refreshRecords, staleA, check } from './cf.js';
  let { data, ctx } = $props();

  let tab = $state('dns');
  let q = $state('');
  let zone = $state('');
  let type = $state('');
  let adding = $state(false);
  let nr = $state({ zone: '', type: 'CNAME', name: '', content: '', proxied: true, comment: '' });
  let edit = $state(null); // {id, content, comment}
  let pol = $state(null); // {id, text}
  let sort = $state(null);

  const ADDR = ['A', 'AAAA', 'CNAME'];
  const zones = $derived(data?.zones || []);
  const stale = $derived(new Set(data ? staleA(data.records).map((r) => r.id) : []));
  const types = $derived([...new Set((data?.records || []).map((r) => r.type))].sort());
  const recs = $derived((data?.records || []).filter((r) => (!zone || r.zone === zone) && (!type || r.type === type)
    && (!q || `${r.name} ${r.content} ${r.comment}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => a.zone.localeCompare(b.zone) || ADDR.indexOf(b.type) - ADDR.indexOf(a.type) || a.name.localeCompare(b.name)));
  const P = (r) => `/zones/${r.zoneId}/dns_records/${r.id}`;
  // a write changes DNS: drop the browser-side cache so the next refresh shows it (the gateway clears its own)
  const after = () => { refreshRecords(); };
  const polPath = (p) => `/accounts/${data.accountId}/access/policies/${p.id}`;

  function startAdd() {
    const z = zones[0]?.name || '';
    nr = { zone: z, type: 'CNAME', name: '', content: z, proxied: true, comment: '' };
    adding = !adding;
  }
  async function add(e) {
    e.preventDefault();
    const z = zones.find((x) => x.name === nr.zone);
    if (!z) return;
    const label = nr.name.trim().replace(new RegExp(`\\.?${z.name.replace(/\./g, '\\.')}$`), '');
    const body = { type: nr.type, name: label ? `${label}.${z.name}` : z.name, content: nr.content.trim(), ttl: 1,
      proxied: ADDR.includes(nr.type) ? nr.proxied : undefined, comment: nr.comment.trim() || undefined };
    if (await act(ctx, { path: `/zones/${z.id}/dns_records`, body, label: `add ${body.type} ${body.name}`, check, done: after })) adding = false;
  }
  async function save(r) {
    const body = {};
    if (edit.content !== r.content) body.content = edit.content.trim();
    if (edit.comment !== r.comment) body.comment = edit.comment.trim();
    if (!Object.keys(body).length) { edit = null; return; }
    if (await act(ctx, { method: 'PATCH', path: P(r), body, label: `edit ${r.type} ${r.name}`, check, done: after })) edit = null;
  }
  async function savePolicy(p) {
    let body;
    try { body = JSON.parse(pol.text); } catch (e) { return ctx.notify(`not JSON: ${e.message}`, 'bad'); }
    if (await act(ctx, { method: 'PUT', path: polPath(p), body, label: `edit Access policy ${p.name}`, check, done: () => { refreshSlow(); } })) pol = null;
  }
  const rule = (r) => {
    const [k, v] = Object.entries(r)[0] || ['?', {}];
    if (k === 'email') return `email ${v.email}`;
    if (k === 'oidc') return `${v.claim_name}=${v.claim_value}`;
    if (k === 'everyone') return 'everyone';
    if (k === 'ip') return `ip ${v.ip}`;
    return k;
  };

  const dnsCols = [
    { key: 'proxied', label: 'edge', render: proxyCell, sort: (r) => (r.proxied ? 1 : 0) },
    { key: 'name', label: 'name', render: nameCell },
    { key: 'type', label: 'type', dim: true },
    { key: 'content', label: 'content', render: contentCell, sort: (r) => r.content },
    { key: 'ttl', label: 'ttl', dim: true, phone: false, format: (v) => (v === 1 ? 'auto' : v) },
    { key: 'comment', label: 'comment', dim: true, phone: false, render: commentCell },
    { key: 'modified', label: 'changed', dim: true, phone: false, desc: true, format: (v) => ago(v, ctx.now) },
    { key: 'act', label: '', sort: false, align: 'right', render: recActs },
  ];
  const accessCols = [
    { key: 'name', label: 'app' },
    { key: 'domain', label: 'domain', render: appDomain },
    { key: 'policies', label: 'policies', sort: false, render: appPolicies },
    { key: 'session', label: 'session', dim: true, phone: false },
  ];
  const zoneCols = [
    { key: 'name', label: 'zone' },
    { key: 'plan', label: 'plan', dim: true, phone: false },
    { key: 'records', label: 'records', align: 'right', get: (z) => data.records.filter((r) => r.zone === z.name).length },
    { key: 'proxied', label: 'proxied', align: 'right', get: (z) => data.records.filter((r) => r.zone === z.name && r.proxied).length },
    { key: 'ns', label: 'name servers', dim: true, phone: false, sort: false, get: (z) => (z.ns || []).join(' ') },
  ];
</script>

{#snippet proxyCell(r)}
  {#if ADDR.includes(r.type)}
    <ActionButton {ctx} method="PATCH" path={P(r)} body={{ proxied: !r.proxied }} label={`${r.proxied ? 'stop proxying' : 'proxy'} ${r.name}`}
      confirm={r.proxied ? `stop proxying ${r.name}?` : false} disabled={!r.proxiable} small
      title={r.proxied ? 'Proxied. Hosts with the origin lock answer 400 without Cloudflare, and Access stops applying.' : 'DNS only'}
      check={check} done={after}>{r.proxied ? '● proxied' : '○ dns only'}</ActionButton>
  {/if}
{/snippet}
{#snippet nameCell(r)}
  <button class="lnk mono" onclick={(e) => { e.stopPropagation(); ctx.open(r.name); }}>{r.name}</button>{#if stale.has(r.id)} <span class="warn mono" title="differs from the apex: not kept current by your dynamic DNS?">▲ stale?</span>{/if}
{/snippet}
{#snippet contentCell(r)}
  {#if edit?.id === r.id}<input class="field mono e" bind:value={edit.content} aria-label="Content" />{:else}<span class="ct">{r.priority != null ? `${r.priority} ` : ''}{r.content}</span>{/if}
{/snippet}
{#snippet commentCell(r)}
  {#if edit?.id === r.id}<input class="field e" bind:value={edit.comment} aria-label="Comment" />{:else}<span class="cm">{r.comment}</span>{/if}
{/snippet}
{#snippet recActs(r)}
  <span class="acts">
    {#if edit?.id === r.id}
      <button class="btn sm" onclick={() => save(r)}>save</button><button class="btn sm" onclick={() => (edit = null)}>cancel</button>
    {:else}
      {#if ctx.can('PATCH', P(r)) !== 'no'}<button class="btn sm" onclick={() => (edit = { id: r.id, content: r.content, comment: r.comment })}>edit</button>{/if}
      <ActionButton {ctx} method="DELETE" path={P(r)} label={`delete ${r.type} ${r.name}`} confirm={`delete ${r.type} ${r.name}?`} check={check} done={after} small>delete</ActionButton>
    {/if}
  </span>
{/snippet}
{#snippet appDomain(a)}<button class="lnk mono" onclick={() => ctx.open(a.domain.split('/')[0])}>{a.domain}</button>{/snippet}
{#snippet appPolicies(a)}<span class="gs">{#each a.policies as p}<span class="chip mono" class:sig={p.decision === 'allow'}>{p.decision === 'bypass' ? '↷ ' : ''}{p.name}</span>{/each}</span>{/snippet}

{#if !data}<p class="mono dim pad spin">loading cloudflare</p>{:else}
<div class="ev fade">
  <div class="bar">
    <div class="seg" role="group" aria-label="Section">
      {#each [['dns', data.records.length], ['access', data.apps.length], ['zones', zones.length]] as [t, n]}
        <button aria-pressed={tab === t} onclick={() => (tab = t)}>{t} <span class="faint">{n}</span></button>
      {/each}
    </div>
    {#if tab === 'dns'}
      <input class="field mono s" placeholder="$ grep …" bind:value={q} aria-label="Search records" />
      <select class="field mono sel" bind:value={zone} aria-label="Zone"><option value="">all zones</option>{#each zones as z}<option>{z.name}</option>{/each}</select>
      <select class="field mono sel" bind:value={type} aria-label="Type"><option value="">all types</option>{#each types as t}<option>{t}</option>{/each}</select>
      <span class="note"></span>
      {#if ctx.can('POST', '/zones/x/dns_records') !== 'no'}<button class="btn primary" onclick={startAdd}>new record</button>{/if}
    {:else}<span class="note mono dim">{tab === 'access' ? 'read · policy edits are owner-only' : ''}</span>{/if}
  </div>

  {#if tab === 'dns'}
    {#if adding}
      <form class="new" onsubmit={add}>
        <select class="field mono sel" bind:value={nr.zone} aria-label="Zone" onchange={() => { if (nr.type === 'CNAME') nr.content = nr.zone; }}>{#each zones as z}<option>{z.name}</option>{/each}</select>
        <select class="field mono sel" bind:value={nr.type} aria-label="Record type">{#each ['CNAME', 'A', 'AAAA', 'TXT', 'MX'] as t}<option>{t}</option>{/each}</select>
        <input class="field mono" placeholder="name (label)" bind:value={nr.name} required aria-label="Name" />
        <span class="mono dim">.{nr.zone} →</span>
        <input class="field mono" placeholder="content" bind:value={nr.content} required aria-label="Content" />
        {#if ADDR.includes(nr.type)}<label class="mono ck"><input type="checkbox" bind:checked={nr.proxied} /> proxied</label>{/if}
        <input class="field" placeholder="comment" bind:value={nr.comment} aria-label="Comment" />
        <button class="btn primary">add record</button>
        <span class="mono dim hint">A proxied CNAME → {nr.zone} follows the apex, which a dynamic-DNS updater keeps current; a new explicit A record must be kept current by it too, or it goes stale. Second-level names (x.y.{nr.zone}) must stay DNS-only (no Universal SSL).</span>
      </form>
    {/if}
    <Table rows={recs} columns={dnsCols} key="id" bind:sort status={(r) => (ADDR.includes(r.type) ? (stale.has(r.id) ? 'warn' : r.proxied ? 'ok' : 'off') : 'unknown')}
      label="DNS records" empty="no records match" minWidth={640} />

  {:else if tab === 'access'}
    <Table rows={data.apps} columns={accessCols} key="id" bind:sort label="Access apps" empty="no Access apps" />
    <div class="cap sub">reusable policies</div>
    {#each data.policies as p (p.id)}
      <div class="pol">
        <div class="ph"><span class="mono">{p.name}</span><span class="chip mono">{p.decision}</span><span class="mono dim">{p.apps} apps · {p.session}</span>
          {#if ctx.can('PUT', polPath(p)) !== 'no'}
            <button class="btn sm" onclick={() => (pol = pol?.id === p.id ? null : { id: p.id, text: JSON.stringify({ name: p.name, decision: p.decision, include: p.include, exclude: p.exclude, require: p.require, session_duration: p.session }, null, 2) })}>edit policy{ctx.can('PUT', polPath(p)) === 'ask' ? ' (ask owner)' : ''}</button>
          {/if}
        </div>
        <div class="rules mono">
          <span class="ok">include</span> {(p.include || []).map(rule).join(' | ') || '–'}
          {#if p.require?.length}<span class="warn"> require</span> {p.require.map(rule).join(' & ')}{/if}
          {#if p.exclude?.length}<span class="bad"> exclude</span> {p.exclude.map(rule).join(' | ')}{/if}
        </div>
        {#if pol?.id === p.id}
          <textarea class="field mono ta" bind:value={pol.text} aria-label="Policy JSON" rows="12"></textarea>
          <div><button class="btn primary" onclick={() => savePolicy(p)}>{ctx.can('PUT', polPath(p)) === 'ask' ? 'ask owner to save' : 'save policy'}</button>
            <span class="mono dim hint">applies to all {p.apps} apps that use it</span></div>
        {/if}
      </div>
    {/each}

  {:else}
    <Table rows={zones} columns={zoneCols} key="id" bind:sort status={(z) => (z.status === 'active' && !z.paused ? 'ok' : 'warn')} label="zones" />
  {/if}
</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .s { max-width: 200px; padding: 6px 10px; font-size: 12px; }
  .sel { width: auto; padding: 6px 8px; font-size: 12px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; }
  .note { flex: 1; font-size: 11px; }
  .new { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 20px; border-bottom: 1px solid var(--line); align-items: center; }
  .new .field { max-width: 200px; padding: 6px 10px; font-size: 12.5px; }
  .ck { font-size: 12px; color: var(--dim); display: flex; gap: 4px; align-items: center; }
  .hint { font-size: 11px; width: 100%; }
  .ct { display: inline-block; max-width: 340px; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }
  .cm { display: inline-block; font-size: 11.5px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }
  .e { padding: 3px 6px; font-size: 11.5px; }
  .acts { display: inline-flex; gap: 4px; }
  .sm { padding: 3px 8px; font-size: 11px; }
  .gs { display: inline-flex; flex-wrap: wrap; gap: 4px; }
  .chip { font-size: 10.5px; padding: 1px 6px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .chip.sig { color: var(--sig); }
  .sub { padding: 14px 20px 4px; }
  .pol { padding: 8px 20px; border-bottom: 1px solid var(--q); display: flex; flex-direction: column; gap: 6px; }
  .ph { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 12.5px; }
  .ph .mono.dim { font-size: 11px; flex: 1; }
  .rules { font-size: 11.5px; color: var(--dim); }
  .ta { width: 100%; font-size: 11.5px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 8px; }
</style>
