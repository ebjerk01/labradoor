<script>
  // ~/proxy — proxy hosts, certificates, access lists, redirections + 404 hosts.
  // admin: create / edit / enable / disable / renew. owner: delete, raw nginx config (it can expose files) + auth gate.
  import Table from '$lab/Table.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import { ago, act } from '$lab/sdk.js';
  import { days, dayTxt, certLevel, probeLevel, ipMap } from './net.js';
  import HostForm from './HostForm.svelte';
  let { data, ctx } = $props();

  let tab = $state('hosts');
  let q = $state('');
  let creating = $state(false);
  let editing = $state(null); // host id
  let adv = $state(null); // {id, text, auth, full}
  let sort = $state(null);

  const ips = $derived(ipMap(ctx.peer('unifi'), ctx.peer('drift')));
  const certs = $derived(Object.fromEntries((data?.certs || []).map((c) => [c.id, c])));
  const acls = $derived(Object.fromEntries((data?.accessLists || []).map((a) => [a.id, a])));
  const hosts = $derived((data?.hosts || []).filter((h) => !q || `${h.domains.join(' ')} ${h.host}:${h.port} ${ips[h.host]?.name || ''}`.toLowerCase().includes(q.toLowerCase())));
  const other = $derived([...(data?.redirections || []), ...(data?.deadHosts || []), ...(data?.streams || []).map((s) => ({ ...s, kind: 'stream' }))]);
  const st = (h) => (!h.enabled ? 'off' : h.online === false ? 'bad' : 'ok');
  const dirOf = (x) => (x.kind === '404' ? 'dead-hosts' : 'redirections');

  async function openAdv(h) {
    if (adv?.id === h.id) { adv = null; return; }
    if (ctx.can('GET', `/api/hosts/${h.id}/advanced`) === 'yes') {
      try {
        const r = await ctx.api.get(`/api/hosts/${h.id}/advanced`);
        adv = { id: h.id, text: r.advanced, auth: r.authRequest || 'none', full: true };
        return;
      } catch (e) { ctx.notify(e.message, 'bad'); }
    }
    adv = { id: h.id, text: h.advanced, auth: h.authRequest, full: false };
  }
  async function saveAdv(h) {
    if (adv.text.includes('[redacted by lab')) return ctx.notify('the text still has redacted lines: only the owner can edit it in full', 'bad');
    if (await act(ctx, { method: 'PUT', path: `/api/hosts/${h.id}/advanced`, body: { advanced: adv.text, authRequest: adv.auth }, label: `edit nginx config of ${h.domains[0]}` })) adv = null;
  }

  const hostCols = [
    { key: 'id', label: '#', dim: true, align: 'right' },
    { key: 'domains', label: 'domains', get: (h) => h.domains.join(' '), render: domainsCell },
    { key: 'host', label: 'target', render: targetCell, sort: (h) => `${h.host}:${h.port}` },
    { key: 'backend', label: 'backend', render: backendCell, sort: (h) => h.backend?.state || '' },
    { key: 'cert', label: 'cert', render: certCell, sort: (h) => days(certs[h.certId]?.expires) ?? 1e9 },
    { key: 'gate', label: 'gate', sort: false, phone: false, render: gateCell },
    { key: 'opts', label: 'options', dim: true, sort: false, phone: false, get: (h) => [h.sslForced && 'ssl', h.http2 && 'h2', h.websockets && 'ws', h.hsts && 'hsts', h.blockExploits && 'exp', h.caching && 'cache', h.advanced && 'cfg'].filter(Boolean).join(' ') },
    { key: 'act', label: '', sort: false, align: 'right', render: hostActs },
  ];
  const certCols = [
    { key: 'id', label: '#', dim: true, align: 'right' },
    { key: 'name', label: 'certificate' },
    { key: 'provider', label: 'provider', dim: true, phone: false, get: (c) => `${c.provider}${c.dnsChallenge ? ' · dns-01' : ''}` },
    { key: 'left', label: 'left', get: (c) => days(c.expires), render: leftCell },
    { key: 'expires', label: 'expires', dim: true, phone: false, format: (v) => (v ? new Date(v * 1000).toISOString().slice(0, 16).replace('T', ' ') : '–') },
    { key: 'hosts', label: 'hosts', align: 'right', get: (c) => data.hosts.filter((h) => h.certId === c.id).length },
    { key: 'act', label: '', sort: false, align: 'right', render: certActs },
  ];
  const otherCols = [
    { key: 'kind', label: 'kind', dim: true },
    { key: 'id', label: '#', dim: true, align: 'right' },
    { key: 'domains', label: 'domains', get: (x) => (x.kind === 'stream' ? `:${x.port}` : x.domains.join(' ')) },
    { key: 'to', label: '→', dim: true, sort: false, get: (x) => (x.kind === 'stream' ? `${x.host}:${x.fport}` : x.kind === '404' ? '404' : `${x.code} ${x.scheme}://${x.target}`) },
    { key: 'act', label: '', sort: false, align: 'right', render: otherActs },
  ];
</script>

{#snippet domainsCell(h)}<span class="dm">{#each h.domains as d}<button class="lnk mono" onclick={(e) => { e.stopPropagation(); ctx.open(d); }}>{d}</button>{/each}</span>{/snippet}
{#snippet targetCell(h)}
  {@const m = ips[h.host]}
  {h.scheme}://{h.host}:{h.port}{#if m}<button class="lnk mm" onclick={() => m.machine && ctx.open(m.machine)}>{m.machine || m.name}</button>{/if}{#each h.extra as x}<span class="dim"> +{x.port}</span>{/each}
{/snippet}
{#snippet backendCell(h)}
  <span title={h.backend ? `${h.backend.state}${h.backend.ms != null ? ' · ' + h.backend.ms + 'ms' : ''}` : 'not probed yet'}><Glyph status={probeLevel(h.backend)} /></span>
  <span class="dim">{h.backend?.state === 'up' ? `${Math.round(h.backend.ms)}ms` : h.backend?.state || ''}</span>
{/snippet}
{#snippet certCell(h)}
  {@const c = certs[h.certId]}
  {@const cd = c ? days(c.expires) : null}
  <span class:warn={certLevel(cd) === 'warn'} class:bad={certLevel(cd) === 'bad'} class:dim={!c}>{c ? dayTxt(cd) : 'none'}</span>
{/snippet}
{#snippet gateCell(h)}
  <span class="gs">
    {#if h.originLock}<span class="chip sig" title="Authenticated Origin Pulls: only Cloudflare may connect">cf-only</span>{/if}
    {#each h.accessLists as a}<span class="chip" title="NPM access list">{acls[a]?.name || `acl ${a}`}</span>{/each}
    {#if h.authRequest !== 'none'}<span class="chip warn" title="forward-auth gate">{h.authRequest}</span>{/if}
  </span>
{/snippet}
{#snippet hostActs(h)}
  <span class="acts">
    {#if ctx.can('PUT', `/api/hosts/${h.id}`) !== 'no'}<button class="btn sm" onclick={() => (editing = editing === h.id ? null : h.id)}>edit</button>{/if}
    <button class="btn sm" onclick={() => openAdv(h)} title="raw nginx config">nginx config</button>
    <ActionButton {ctx} path={`/api/hosts/${h.id}/${h.enabled ? 'disable' : 'enable'}`} label={`${h.enabled ? 'disable' : 'enable'} ${h.domains[0]}`}
      confirm={h.enabled ? `disable #${h.id}?` : false} title={h.enabled ? 'It stops answering at once' : ''} small>{h.enabled ? 'disable' : 'enable'}</ActionButton>
    <ActionButton {ctx} method="DELETE" path={`/api/hosts/${h.id}`} label={`delete host #${h.id} ${h.domains[0]}`} confirm={`delete #${h.id}?`} small>delete</ActionButton>
  </span>
{/snippet}
{#snippet leftCell(c)}{@const d = days(c.expires)}<span class:warn={certLevel(d) === 'warn'} class:bad={certLevel(d) === 'bad'}>{dayTxt(d)}</span>{/snippet}
{#snippet certActs(c)}
  {#if c.provider === 'letsencrypt'}<ActionButton {ctx} path={`/api/certificates/${c.id}/renew`} label={`renew ${c.name}`} icon="restart" small>renew</ActionButton>{/if}
{/snippet}
{#snippet otherActs(x)}
  {#if x.kind !== 'stream'}
    <span class="acts">
      <ActionButton {ctx} path={`/api/${dirOf(x)}/${x.id}/${x.enabled ? 'disable' : 'enable'}`} label={`${x.enabled ? 'disable' : 'enable'} ${x.domains[0]}`} small>{x.enabled ? 'disable' : 'enable'}</ActionButton>
      <ActionButton {ctx} method="DELETE" path={`/api/${dirOf(x)}/${x.id}`} label={`delete ${x.kind} #${x.id} ${x.domains[0]}`} confirm={`delete #${x.id}?`} small>delete</ActionButton>
    </span>
  {/if}
{/snippet}

{#if !data}<p class="mono dim pad spin">loading proxy</p>{:else}
<div class="pv fade">
  <div class="bar">
    <div class="seg" role="group" aria-label="Section">
      {#each [['hosts', data.hosts.length], ['certs', data.certs.length], ['access', data.accessLists.length], ['other', other.length]] as [t, n]}
        <button aria-pressed={tab === t} onclick={() => (tab = t)}>{t} <span class="faint">{n}</span></button>
      {/each}
    </div>
    {#if tab === 'hosts'}<input class="field mono s" placeholder="$ grep …" bind:value={q} aria-label="Search hosts" />{/if}
    <span class="note mono dim">probed {data.probedAt ? ago(data.probedAt, ctx.now) + ' ago' : '…'} · timeout = lab can't reach it (not proof it is down)</span>
    {#if tab === 'hosts' && ctx.can('POST', '/api/hosts') !== 'no'}<button class="btn primary" onclick={() => (creating = !creating)}>new host</button>{/if}
  </div>

  {#if tab === 'hosts'}
    {#if creating}<HostForm {data} {ctx} done={() => (creating = false)} />{/if}
    <Table rows={hosts} columns={hostCols} key="id" bind:sort status={st} muted={(h) => !h.enabled} label="proxy hosts" empty="no hosts match" />
    {#if editing != null}
      {@const h = data.hosts.find((x) => x.id === editing)}
      {#if h}<div class="panel"><div class="cap pl">edit #{h.id} {h.domains[0]}</div><HostForm {data} {ctx} host={h} done={() => (editing = null)} /></div>{/if}
    {/if}
    {#if adv}
      {@const h = data.hosts.find((x) => x.id === adv.id)}
      {#if h}
        <div class="panel adv">
          <div class="cap">nginx config of #{h.id} {h.domains[0]}</div>
          <textarea class="field mono ta" bind:value={adv.text} rows={Math.min(18, adv.text.split('\n').length + 2)} aria-label="Advanced nginx config"
            readonly={ctx.can('PUT', `/api/hosts/${h.id}/advanced`) === 'no'}></textarea>
          <div class="row2">
            <label class="mono dim">auth gate <select class="field mono sel" bind:value={adv.auth} aria-label="Auth gate">{#each ['none', 'authentik', 'tinyauth'] as a}<option>{a}</option>{/each}</select></label>
            {#if ctx.can('PUT', `/api/hosts/${h.id}/advanced`) !== 'no'}
              <button class="btn primary" onclick={() => saveAdv(h)}>{ctx.can('PUT', `/api/hosts/${h.id}/advanced`) === 'ask' ? 'ask owner to save' : 'save config'}</button>
            {/if}
            <button class="btn" onclick={() => (adv = null)}>close</button>
            <span class="mono dim">{adv.full ? 'full text' : 'lines that may hold credentials are redacted'} · owner-only: nginx config can expose files and turn off the origin lock</span>
          </div>
        </div>
      {/if}
    {/if}

  {:else if tab === 'certs'}
    <Table rows={data.certs} columns={certCols} key="id" bind:sort status={(c) => certLevel(days(c.expires)) || 'unknown'} label="certificates" />
    <p class="mono dim foot">Let's Encrypt short-lived profile (~6.7 days): 3–5 days left is normal; &lt; 1.5 d means renewal is failing.</p>

  {:else if tab === 'access'}
    {#each data.accessLists as a (a.id)}
      <div class="acl">
        <div class="ah"><span class="mono">#{a.id} {a.name}</span><span class="mono dim">{a.hosts} hosts · {a.satisfyAny ? 'any' : 'all'} · {a.authUsers} basic-auth users</span></div>
        <div class="gs">{#each a.clients as c}<span class="chip" class:ok={c.directive === 'allow'} class:bad={c.directive === 'deny'}>{c.directive} {c.address}</span>{/each}</div>
        <div class="gs">{#each data.hosts.filter((h) => h.accessLists.includes(a.id)) as h}<button class="lnk mono hs" onclick={() => ctx.open(h.domains[0])}>{h.domains[0]}</button>{/each}</div>
      </div>
    {:else}<p class="mono dim pad">no access lists</p>{/each}

  {:else}
    <Table rows={other} columns={otherCols} key={(x) => x.kind + x.id} bind:sort status={(x) => (!x.enabled ? 'off' : x.online === false ? 'bad' : 'ok')}
      label="redirections, 404 hosts and streams" empty="no redirections, 404 hosts or streams" />
  {/if}
</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .s { max-width: 200px; padding: 6px 10px; font-size: 12px; }
  .note { flex: 1 1 200px; font-size: 11px; min-width: 0; }
  .dm { display: inline-flex; flex-direction: column; gap: 1px; font-size: 12px; align-items: flex-start; }
  .mm { margin-left: 8px; color: var(--sig); font-size: 11px; }
  .gs { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { font-size: 10.5px; padding: 1px 6px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .chip.sig { color: var(--sig); border-color: var(--sig); }
  .chip.warn { color: var(--warn); } .chip.ok { color: var(--ok); } .chip.bad { color: var(--bad); }
  .acts { display: inline-flex; gap: 4px; }
  .sm { padding: 3px 8px; font-size: 11px; }
  .panel { border-top: 1px solid var(--line); background: var(--panel); }
  .pl { padding: 10px 20px 0; }
  .adv { padding: 10px 20px; display: flex; flex-direction: column; gap: 8px; }
  .ta { width: 100%; font-size: 11.5px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 8px; }
  .row2 { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 11.5px; }
  .sel { width: auto; padding: 4px 6px; font-size: 11.5px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; }
  .foot { padding: 10px 20px; font-size: 11px; }
  .acl { padding: 10px 20px; border-bottom: 1px solid var(--q); display: flex; flex-direction: column; gap: 6px; }
  .ah { display: flex; gap: 12px; align-items: baseline; font-size: 12.5px; flex-wrap: wrap; }
  .hs { font-size: 11.5px; margin-right: 8px; }
</style>
