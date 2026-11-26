<script>
  // ~/network — clients, DHCP reservations, networks/VLANs, devices, port forwards.
  // admin: reservations, rename, block/unblock, restart an AP. owner: remove a reservation, add/remove port forwards.
  import Table from '$lab/Table.svelte';
  import Lazy from '$lab/Lazy.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { ago, act, lazy, sortRows } from '$lab/sdk.js';
  import { mismatch, freeIp, label } from './uf.js';
  let { data, ctx } = $props();

  let tab = $state('clients');
  let q = $state('');
  let net = $state('');
  let onlineOnly = $state(true);
  let edit = $state(null); // {mac, ip, name}
  let nr = $state(null); // new reservation {mac, name, networkId, ip}
  let pf = $state(null); // new port forward
  let sort = $state(null);

  const nets = $derived(Object.fromEntries((data?.networks || []).map((n) => [n.id, n])));
  const lans = $derived((data?.networks || []).filter((n) => n.purpose === 'corporate' || n.purpose === 'guest'));
  const match = (c) => !q || `${c.name} ${c.hostname} ${c.ip} ${c.fixedIp} ${c.mac} ${c.vendor}`.toLowerCase().includes(q.toLowerCase());
  const clients = $derived((data?.clients || []).filter((c) => (!onlineOnly || c.online || c.blocked) && (!net || c.networkId === net) && match(c)));
  const ipKey = (ip) => (ip || '').split('.').map((x) => x.padStart(3, '0')).join('.');
  const reserved = $derived((data?.clients || []).filter((c) => c.reserved && (!net || c.networkId === net) && match(c))
    .sort((a, b) => ipKey(a.fixedIp).localeCompare(ipKey(b.fixedIp))));
  const online = (c) => c.online ? `up ${ago(ctx.now - (c.uptime || 0), ctx.now)}` : ago(c.lastSeen, ctx.now);
  const glyph = (c) => (c.blocked ? 'bad' : mismatch(c) ? 'warn' : c.online ? 'ok' : 'off');

  // port forwards load when their tab opens (not on every shell refresh); only for users who may read them
  const pfs = lazy(() => ctx, () => (tab === 'forwards' ? '/api/portforwards' : null), { keep: true });

  function startNew() {
    const n = lans.find((x) => x.name === 'Management') || lans[0];
    nr = nr ? null : { mac: '', name: '', networkId: n?.id || '', ip: freeIp(n, data.clients) };
  }
  const body = () => ({ mac: nr.mac.trim().toLowerCase(), name: nr.name.trim() || undefined, ip: nr.ip.trim(), networkId: nr.networkId });
  async function addRes(e) {
    e.preventDefault();
    if (await act(ctx, { path: '/api/reservations', body: body(), label: `reserve ${nr.ip} for ${nr.name || nr.mac}` })) nr = null;
  }
  async function saveRes(c) {
    const b = {};
    if (edit.ip !== c.fixedIp) b.ip = edit.ip.trim();
    if (edit.name !== (c.name || '')) b.name = edit.name.trim();
    if (!Object.keys(b).length) { edit = null; return; }
    if (await act(ctx, { method: 'PUT', path: `/api/reservations/${c.mac}`, body: b, label: `change reservation of ${label(c)}` })) edit = null;
  }
  async function rename(c) {
    const n = prompt(`Name for ${c.mac}`, c.name || c.hostname || '');
    if (n != null && n.trim() !== (c.name || '')) await act(ctx, { method: 'PUT', path: `/api/clients/${c.mac}/name`, body: { name: n.trim() }, label: `rename ${c.mac}` });
  }
  function startPf() {
    pf = pf ? null : { name: '', proto: 'tcp', dstPort: '', fwdPort: '', fwdIp: '' };
  }
  async function addPf(e) {
    e.preventDefault();
    const b = { name: pf.name.trim(), proto: pf.proto, dstPort: pf.dstPort.trim(), fwdPort: (pf.fwdPort || pf.dstPort).trim(), fwdIp: pf.fwdIp.trim() };
    if (await act(ctx, { path: '/api/portforwards', body: b, label: `forward ${b.proto} :${b.dstPort} to ${b.fwdIp}`,
      done: () => { pfs.reload(); } })) pf = null;
  }

  const clientCols = [
    { key: 'name', label: 'client', get: label, render: nameCell },
    { key: 'ip', label: 'ip', render: ipCell, sort: (c) => ipKey(c.ip) },
    { key: 'mac', label: 'mac', dim: true, phone: false },
    { key: 'network', label: 'network', dim: true, phone: false, format: (v, c) => `${v || '–'}${c.vlan ? ` · ${c.vlan}` : ''}` },
    { key: 'via', label: 'via', dim: true, phone: false, sort: false, get: (c) => (c.wired ? `${c.uplink || 'wired'}${c.swPort ? ' p' + c.swPort : ''}` : `${c.essid || 'wifi'}${c.signal ? ' ' + c.signal + 'dBm' : ''}`) },
    { key: 'lastSeen', label: 'seen', dim: true, desc: true, format: (v, c) => online(c) },
    { key: 'act', label: '', sort: false, align: 'right', render: clientActs },
  ];
  const resCols = [
    { key: 'fixedIp', label: 'ip', render: resIp, sort: (c) => ipKey(c.fixedIp) },
    { key: 'name', label: 'name', get: label, render: resName },
    { key: 'mac', label: 'mac', dim: true, phone: false },
    { key: 'networkId', label: 'network', dim: true, phone: false, get: (c) => nets[c.networkId]?.name || c.network || '–' },
    { key: 'now', label: 'now', dim: true, sort: false, get: (c) => (c.online ? (mismatch(c) ? `has ${c.ip}` : 'online') : `seen ${ago(c.lastSeen, ctx.now)}`) },
    { key: 'act', label: '', sort: false, align: 'right', render: resActs },
  ];
  const netCols = [
    { key: 'name', label: 'network' },
    { key: 'vlan', label: 'vlan', get: (n) => n.vlan ?? (n.purpose === 'corporate' ? 1 : null) },
    { key: 'subnet', label: 'subnet', dim: true, get: (n) => n.subnet || n.wanType || null },
    { key: 'dhcp', label: 'dhcp', dim: true, phone: false, sort: false, get: (n) => (n.dhcp ? `${n.dhcpStart?.split('.').pop()}–${n.dhcpStop?.split('.').pop()}` : n.purpose === 'corporate' ? 'off' : '') },
    { key: 'on', label: 'online', align: 'right', get: (n) => data.clients.filter((c) => c.online && c.networkId === n.id).length || '' },
    { key: 'res', label: 'reserved', align: 'right', get: (n) => data.clients.filter((c) => c.reserved && c.networkId === n.id).length || '' },
    { key: 'flags', label: 'flags', dim: true, phone: false, sort: false, get: (n) => [n.purpose, n.isolated && 'isolated', n.internet === false && 'no internet'].filter(Boolean).join(' · ') },
  ];
  const devCols = [
    { key: 'name', label: 'device' },
    { key: 'model', label: 'model', dim: true, phone: false, get: (d) => `${d.model} · ${d.type}` },
    { key: 'ip', label: 'ip', dim: true, phone: false, get: (d) => d.ip },
    { key: 'version', label: 'version', render: devVersion },
    { key: 'clients', label: 'clients', align: 'right' },
    { key: 'cpu', label: 'cpu · mem', dim: true, phone: false, sort: false, get: (d) => (d.cpu != null ? `${Math.round(d.cpu)}% · ${Math.round(d.mem)}%` : null) },
    { key: 'uptime', label: 'up', dim: true, format: (v, d) => (d.online ? ago(ctx.now - (d.uptime || 0), ctx.now) : `seen ${ago(d.lastSeen, ctx.now)}`) },
    { key: 'act', label: '', sort: false, align: 'right', render: devActs },
  ];
  const pfCols = [
    { key: 'name', label: 'name' },
    { key: 'proto', label: 'proto', dim: true },
    { key: 'dstPort', label: 'wan port' },
    { key: 'fwdIp', label: 'to', get: (p) => `${p.fwdIp}:${p.fwdPort}` },
    { key: 'enabled', label: 'state', dim: true, get: (p) => (p.enabled ? 'on' : 'off') },
    { key: 'act', label: '', sort: false, align: 'right', render: pfActs },
  ];
</script>

{#snippet nameCell(c)}
  <button class="lnk" onclick={(e) => { e.stopPropagation(); ctx.open(`client:${c.mac}`); }}>{label(c)}</button>{#if c.hostname && c.name && c.hostname !== c.name}<span class="mono dim hn">{c.hostname}</span>{/if}{#if c.blocked} <span class="bad">blocked</span>{/if}
{/snippet}
{#snippet ipCell(c)}{c.ip || '–'}{#if c.reserved}<span class="sig" title="reserved {c.fixedIp}"> ◆{c.fixedIp !== c.ip ? ' ' + c.fixedIp : ''}</span>{/if}{/snippet}
{#snippet clientActs(c)}
  <span class="acts">
    {#if ctx.can('PUT', '/api/clients/x/name') !== 'no'}<button class="btn sm" onclick={() => rename(c)} title="rename {label(c)}">rename</button>{/if}
    {#if !c.reserved && c.ip && c.online}<ActionButton {ctx} path="/api/reservations" body={{ mac: c.mac, ip: c.ip }} label={`reserve ${c.ip}`} small>reserve ip</ActionButton>{/if}
    {#if c.blocked}
      <ActionButton {ctx} path={`/api/clients/${c.mac}/unblock`} label={`unblock ${label(c)}`} small>unblock</ActionButton>
    {:else}
      <ActionButton {ctx} path={`/api/clients/${c.mac}/block`} label={`block ${label(c)}`} confirm={`block ${label(c)}?`} small>block</ActionButton>
    {/if}
  </span>
{/snippet}
{#snippet resIp(c)}{#if edit?.mac === c.mac}<input class="field mono e" bind:value={edit.ip} aria-label="IP" onclick={(e) => e.stopPropagation()} />{:else}{c.fixedIp}{/if}{/snippet}
{#snippet resName(c)}{#if edit?.mac === c.mac}<input class="field e" bind:value={edit.name} aria-label="Name" />{:else}<button class="lnk" onclick={() => ctx.open(`client:${c.mac}`)}>{label(c)}</button>{/if}{/snippet}
{#snippet resActs(c)}
  <span class="acts">
    {#if edit?.mac === c.mac}
      <button class="btn sm" onclick={() => saveRes(c)}>save</button><button class="btn sm" onclick={() => (edit = null)}>cancel</button>
    {:else}
      {#if ctx.can('PUT', '/api/reservations/x') !== 'no'}<button class="btn sm" onclick={() => (edit = { mac: c.mac, ip: c.fixedIp, name: c.name || '' })}>edit</button>{/if}
      <ActionButton {ctx} method="DELETE" path={`/api/reservations/${c.mac}`} label={`remove reservation ${label(c)} ${c.fixedIp}`}
        confirm={`remove ${c.fixedIp}?`} title={`${c.name || c.mac} gets a pool address at its next lease; port forwards and DNS that use ${c.fixedIp} break`} small>remove</ActionButton>
    {/if}
  </span>
{/snippet}
{#snippet devVersion(d)}<span class:warn={d.upgradable}>{d.version}{d.upgradable ? ' ↑' : ''}</span>{/snippet}
{#snippet devActs(d)}
  {#if d.type === 'uap'}<ActionButton {ctx} path={`/api/devices/${d.mac}/restart`} label={`restart ${d.name}`} confirm={`restart ${d.name}?`}
    title="Its Wi-Fi clients drop for about a minute" icon="restart" small>restart</ActionButton>{/if}
{/snippet}
{#snippet pfActs(p)}
  <ActionButton {ctx} method="DELETE" path={`/api/portforwards/${p.id}`} label={`remove port forward ${p.name}`} confirm={`remove ${p.name}?`}
    done={() => { pfs.reload(); }} small>remove</ActionButton>
{/snippet}

{#if !data}<p class="mono dim pad spin">loading unifi</p>{:else}
<div class="nv fade">
  <div class="bar">
    <div class="seg" role="group" aria-label="Section">
      {#each [['clients', data.clients.filter((c) => c.online).length], ['reservations', data.clients.filter((c) => c.reserved).length], ['networks', lans.length], ['devices', data.devices.length], ['forwards', null]] as [t, n]}
        <button aria-pressed={tab === t} onclick={() => (tab = t)}>{t === 'forwards' ? 'port forwards' : t}{#if n != null} <span class="faint">{n}</span>{/if}</button>
      {/each}
    </div>
    {#if tab === 'clients' || tab === 'reservations'}
      <input class="field mono s" placeholder="$ grep …" bind:value={q} aria-label="Search clients" />
      <select class="field mono sel" bind:value={net} aria-label="Network"><option value="">all networks</option>{#each lans as n}<option value={n.id}>{n.name}{n.vlan ? ` · ${n.vlan}` : ''}</option>{/each}</select>
      {#if tab === 'clients'}<label class="mono ck"><input type="checkbox" bind:checked={onlineOnly} /> online only</label>{/if}
    {/if}
    <span class="note mono dim">wan {data.health.wan?.status || '?'} · {data.health.wan?.isp || ''} · {data.health.wan?.latency ?? '–'}ms</span>
    {#if tab === 'reservations' && ctx.can('POST', '/api/reservations') !== 'no'}<button class="btn primary" onclick={startNew}>new reservation</button>{/if}
    {#if tab === 'forwards' && ctx.can('POST', '/api/portforwards') !== 'no'}<button class="btn primary" onclick={startPf}>{ctx.can('POST', '/api/portforwards') === 'ask' ? 'new port forward (ask owner)' : 'new port forward'}</button>{/if}
  </div>

  {#if tab === 'clients'}
    <Table rows={clients} columns={clientCols} key="mac" bind:sort status={glyph} label="UniFi clients" empty="no clients match" />

  {:else if tab === 'reservations'}
    {#if nr}
      <form class="new" onsubmit={addRes}>
        <input class="field mono" placeholder="aa:bb:cc:dd:ee:ff" bind:value={nr.mac} required aria-label="MAC" />
        <input class="field" placeholder="name" bind:value={nr.name} aria-label="Name" />
        <select class="field mono sel" bind:value={nr.networkId} aria-label="Network" onchange={() => (nr.ip = freeIp(nets[nr.networkId], data.clients))}>{#each lans as n}<option value={n.id}>{n.name}</option>{/each}</select>
        <input class="field mono" placeholder="ip" bind:value={nr.ip} required aria-label="IP" />
        <button type="button" class="btn" onclick={() => (nr.ip = freeIp(nets[nr.networkId], data.clients))}>suggest a free ip</button>
        <button class="btn primary">reserve</button>
        <span class="mono dim hint">checked on save against other reservations, active clients and leases of the last 24 h (a ping is not enough).</span>
      </form>
    {/if}
    <Table rows={reserved} columns={resCols} key="mac" bind:sort status={glyph} label="DHCP reservations" empty="no reservations" />

  {:else if tab === 'networks'}
    <Table rows={data.networks} columns={netCols} key="id" bind:sort status={(n) => (n.enabled === false ? 'off' : 'ok')} label="UniFi networks" />
    <p class="mono dim foot">read-only here.</p>

  {:else if tab === 'devices'}
    <Table rows={data.devices} columns={devCols} key="mac" bind:sort status={(d) => (d.online ? 'ok' : 'bad')} label="UniFi devices" />

  {:else}
    {#if pf}
      <form class="new" onsubmit={addPf}>
        <input class="field" placeholder="name" bind:value={pf.name} required aria-label="Name" />
        <select class="field mono sel" bind:value={pf.proto} aria-label="Protocol">{#each ['tcp', 'udp', 'tcp_udp'] as p}<option>{p}</option>{/each}</select>
        <input class="field mono" placeholder="wan port (8443 or 8000-8010)" bind:value={pf.dstPort} required aria-label="WAN port" />
        <input class="field mono" placeholder="lan port (same)" bind:value={pf.fwdPort} aria-label="LAN port" />
        <input class="field mono" placeholder="lan ip" bind:value={pf.fwdIp} required aria-label="LAN IP" />
        <button class="btn primary">{ctx.can('POST', '/api/portforwards') === 'ask' ? 'ask owner' : 'add forward'}</button>
        <span class="mono dim hint">owner-only. The target must be inside one of our LAN networks and the WAN port free; the connector checks both.</span>
      </form>
    {/if}
    <Lazy of={pfs} empty="no port forwards">
      {#snippet children(list)}
        <Table rows={list} columns={pfCols} key="id" bind:sort status={(p) => (p.enabled ? 'ok' : 'off')} label="port forwards" />
      {/snippet}
    </Lazy>
  {/if}
</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .s { max-width: 200px; padding: 6px 10px; font-size: 12px; }
  .sel { width: auto; padding: 6px 8px; font-size: 12px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; }
  .ck { font-size: 12px; color: var(--dim); display: flex; gap: 4px; align-items: center; }
  .note { flex: 1; font-size: 11px; text-align: right; min-width: 0; }
  .new { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 20px; border-bottom: 1px solid var(--line); align-items: center; }
  .new .field { max-width: 190px; padding: 6px 10px; font-size: 12.5px; }
  .hint { font-size: 11px; width: 100%; }
  .foot { padding: 10px 20px; font-size: 11px; }
  .hn { margin-left: 6px; font-size: 11px; }
  .e { padding: 3px 6px; font-size: 11.5px; max-width: 180px; }
  .acts { display: inline-flex; gap: 4px; }
  .sm { padding: 3px 8px; font-size: 11px; }
</style>
