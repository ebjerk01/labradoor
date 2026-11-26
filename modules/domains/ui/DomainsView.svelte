<script>
  // ~/domains — every hostname end to end. Read-only: "dead?" is a cleanup LIST (for a proxy cleanup); lab deletes nothing.
  import Table from '$lab/Table.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import { rows } from './rows.js';
  import { dayTxt, certLevel, probeLevel } from './net.js';
  let { ctx } = $props();

  let filter = $state('all');
  let q = $state('');
  let sort = $state(null);
  const all = $derived(rows(ctx));
  const FILTERS = [['all', () => true], ['problems', (r) => r.status === 'bad' || r.status === 'warn'], ['cleanup', (r) => r.dead || r.dnsOnly],
    ['proxied', (r) => r.dns.proxied], ['no proxy host', (r) => !r.npm]];
  const shown = $derived(all.filter(FILTERS.find(([f]) => f === filter)[1]).filter((r) => !q || `${r.name} ${r.npm?.host || ''} ${r.machine?.name || ''} ${r.dns.content || ''}`.toLowerCase().includes(q.toLowerCase())));
  const missing = $derived(['npm', 'cloudflare', 'drift', 'unifi'].filter((m) => ctx.peer(m) == null));

  function copy() {
    const list = all.filter((r) => r.dead || r.dnsOnly).map((r) => `${r.name}\t${r.npm ? `npm #${r.npm.id} → ${r.npm.host}:${r.npm.port}` : `dns ${r.dns.type} ${r.dns.content}`}\t${r.reasons.join('; ')}`).join('\n');
    navigator.clipboard?.writeText(list).then(() => ctx.notify('cleanup list copied'), () => ctx.notify('clipboard blocked', 'bad'));
  }
  const dnsCell = (r) => (r.dns.kind === 'record' ? `${r.dns.type === 'CNAME' ? '→ ' + r.dns.content : r.dns.type + ' ' + r.dns.content}` : r.dns.kind === 'wildcard' ? `* ${r.dns.content}` : r.dns.kind);
  const columns = [
    { key: 'name', label: 'hostname', render: nameCell },
    { key: 'dns', label: 'dns', get: (r) => dnsCell(r), render: dnsCol },
    { key: 'npm', label: 'proxy', get: (r) => r.npm?.id ?? null, render: npmCol },
    { key: 'backend', label: '→ backend', phone: false, get: (r) => (r.npm ? `${r.npm.host}:${r.npm.port}` : null), render: backendCol },
    { key: 'checks', label: 'checks', get: (r) => (r.checks.total ? r.checks.passing / r.checks.total : -1), render: checksCol },
    { key: 'cert', label: 'cert', get: (r) => r.cert?.days ?? null, render: certCol },
    { key: 'notes', label: 'notes', phone: false, sort: false, render: notesCol },
  ];
</script>

{#snippet nameCell(r)}<button class="lnk mono" onclick={(e) => { e.stopPropagation(); ctx.open(r.name); }}>{r.name}</button>{/snippet}
{#snippet dnsCol(r)}
  <span title={r.dns.proxied ? 'proxied' : 'dns only'} class:sig={r.dns.proxied} class:dim={!r.dns.proxied}>{r.dns.proxied ? '●' : '○'}</span>
  <span class="dim">{dnsCell(r)}</span>
  {#if r.access.length}<span class="chip sig" title={r.access.map((a) => `${a.path || '/'}: ${a.policies.join(', ')}`).join('\n')}>access{r.access.length > 1 ? ` ×${r.access.length}` : ''}</span>{/if}
{/snippet}
{#snippet npmCol(r)}
  {#if r.npm}<span class:dim={!r.npm.enabled} class:bad={r.npm.online === false}>#{r.npm.id}</span>{#if r.npm.originLock}<span class="chip sig" title="origin lock: only the CDN may connect">cf-only</span>{/if}{#if r.npm.accessLists.length}<span class="chip">acl</span>{/if}{:else}<span class="faint">–</span>{/if}
{/snippet}
{#snippet backendCol(r)}
  {#if r.npm}
    <span title={r.npm.backend ? r.npm.backend.state : 'not probed yet'}><Glyph status={probeLevel(r.npm.backend)} /></span>
    <span class="dim">{r.npm.host}:{r.npm.port}</span>
    {#if r.machine}<button class="lnk mm" onclick={() => r.machine.machine && ctx.open(r.machine.machine)}>{r.machine.machine || r.machine.name}</button>{/if}
  {/if}
{/snippet}
{#snippet checksCol(r)}
  {#if r.checks.total}<span class:ok={r.checks.passing === r.checks.total} class:warn={r.checks.passing && r.checks.passing < r.checks.total} class:bad={!r.checks.passing}>{r.checks.passing}/{r.checks.total}</span>{:else}<span class="faint">none</span>{/if}
{/snippet}
{#snippet certCol(r)}<span class:warn={certLevel(r.cert?.days) === 'warn'} class:bad={certLevel(r.cert?.days) === 'bad'} class:faint={!r.cert}>{r.cert ? dayTxt(r.cert.days) : r.npm ? 'none' : ''}</span>{/snippet}
{#snippet notesCol(r)}
  <span class="rs">{#if r.dead || r.dnsOnly}<span class="chip warn">{r.dead ? 'dead?' : 'dns only'}</span>{/if}<span class="dim">{r.reasons.filter((x) => !x.startsWith('DEAD')).join(' · ')}</span>{#if r.refs.length}<span class="faint" title={r.refs.join('\n')}> · ref {r.refs.slice(0, 2).join(', ')}{r.refs.length > 2 ? ` +${r.refs.length - 2}` : ''}</span>{/if}</span>
{/snippet}

<div class="dv fade">
  <div class="bar">
    <div class="seg" role="group" aria-label="Filter">
      {#each FILTERS as [f, fn]}<button aria-pressed={filter === f} onclick={() => (filter = f)}>{f} <span class="faint">{all.filter(fn).length}</span></button>{/each}
    </div>
    <input class="field mono s" placeholder="$ grep …" bind:value={q} aria-label="Search hostnames" />
    <span class="note mono dim">{missing.length ? `waiting for ${missing.join(', ')} · ` : ''}cleanup = backend silent + no passing check + nothing references it · read-only</span>
    <button class="btn" onclick={copy}>copy cleanup list</button>
  </div>
  <Table rows={shown} {columns} key="name" bind:sort status={(r) => r.status} muted={(r) => r.dead || r.dnsOnly} label="hostnames"
    empty={all.length ? 'nothing matches' : 'waiting for npm + cloudflare data'} minWidth={720} />
</div>

<style>
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .s { max-width: 200px; padding: 6px 10px; font-size: 12px; }
  .note { flex: 1 1 260px; font-size: 11px; min-width: 0; }
  .mm { margin-left: 6px; color: var(--sig); font-size: 11px; }
  .chip { font-family: "Geist Mono Variable", monospace; font-size: 10px; padding: 0 5px; margin-left: 5px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .chip.sig { color: var(--sig); border-color: var(--sig); }
  .chip.warn { color: var(--warn); border-color: var(--warn); margin: 0 6px 0 0; }
  .rs { font-size: 11px; white-space: normal; display: inline-block; min-width: 220px; }
</style>
