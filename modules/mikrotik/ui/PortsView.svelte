<script>
  // ~/mikrotik: system numbers, the port table (click a row for its detail + actions) and the VLAN table.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Table from '$lab/Table.svelte';
  import Lazy from '$lab/Lazy.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { lazy, level, dur, rate, bytes } from '$lab/sdk.js';
  import { untrack } from 'svelte';
  import { speedText, poeOn, poeBad, vlanTable } from './mikrotik.js';
  let { data, ctx } = $props();

  let sort = $state(untrack(() => ctx.prefs.get('sort', { key: 'name', dir: 1 })));
  let picked = $state(null);
  const port = $derived(data?.ports.find((p) => p.name === picked) || null);
  const up = $derived((data?.ports ?? []).filter((p) => p.running).length);
  const vlans = lazy(() => ctx, () => '/interface/bridge/vlan', { query: () => ({ '.proplist': 'bridge,vlan-ids,tagged,untagged,current-tagged,current-untagged,disabled' }) });
  const bports = lazy(() => ctx, () => '/interface/bridge/port', { query: () => ({ '.proplist': 'bridge,interface,pvid' }) });
  const vlanRows = $derived(vlans.data ? vlanTable(vlans.data, bports.data || []) : null);

  const status = (p) => (p.disabled ? 'off' : !p.running ? 'off' : (p.poe && poeBad(p.poe.status)) || (p.speed && p.speed < 1000 && !p.name.startsWith('sfp')) ? 'warn' : 'ok');
  const columns = [
    { key: 'name', label: 'port' },
    { key: 'comment', label: 'comment', dim: true, phone: false },
    { key: 'speed', label: 'link', align: 'right', desc: true, format: (v, p) => (p.disabled ? 'disabled' : p.running ? speedText(v) : 'down') },
    { key: 'rxRate', label: 'in', align: 'right', desc: true, format: (v, p) => (p.running ? rate(v) : '–') },
    { key: 'txRate', label: 'out', align: 'right', desc: true, phone: false, format: (v, p) => (p.running ? rate(v) : '–') },
    { key: 'poe', label: 'poe', align: 'right', desc: true, phone: false, get: (p) => p.poe?.watts || 0,
      format: (v, p) => (!p.poe ? '–' : poeOn(p) ? `${v.toFixed(1)} W` : p.poe.mode === 'off' ? 'off' : '·') },
    { key: 'fcs', label: 'crc err', align: 'right', desc: true, phone: false, format: (v) => (v ? v.toLocaleString() : '0') },
    { key: 'linkDowns', label: 'downs', align: 'right', desc: true, phone: false },
  ];
  const vcols = [
    { key: 'vlan', label: 'vlan' },
    { key: 'bridge', label: 'bridge', dim: true, phone: false },
    { key: 'untagged', label: 'untagged', get: (r) => r.untagged.join(' ') },
    { key: 'tagged', label: 'tagged', get: (r) => r.tagged.join(' ') },
    { key: 'pvid', label: 'pvid on', dim: true, phone: false, get: (r) => r.pvid.join(' ') },
  ];
</script>

{#if !data}<p class="mono dim spin pad">loading switch</p>{:else}
<div class="view fade">
  <Section title="{data.identity} · {data.sys.board}" src="mikrotik · routeros {data.sys.version}">
    <Stats cols={6} items={[
      { n: 'ports up', v: `${up}/${data.ports.length}` },
      { n: 'poe out', v: data.health.poeW != null ? `${data.health.poeW} W` : '–' },
      { n: 'cpu', v: `${data.sys.cpu}%`, s: level(data.sys.cpu, 70, 90) },
      { n: 'temp', v: data.health.temp != null ? `${data.health.temp}°C` : '–', s: data.health.temp != null ? level(data.health.temp, ctx.settings.temp_warn ?? 70, (ctx.settings.temp_warn ?? 70) + 10) : null },
      { n: 'memory', v: `${data.sys.memPct}%`, s: level(data.sys.memPct, 85, 95) },
      { n: 'uptime', v: dur(data.sys.uptime) },
    ]} />
  </Section>

  <Section title="ports · {data.ports.length}" src="mikrotik">
    <Table rows={data.ports} key="name" {columns} bind:sort label="switch ports" {status} muted={(p) => p.disabled}
      onrow={(p) => { picked = picked === p.name ? null : p.name; ctx.prefs.set('sort', sort); }} minWidth={520} />
  </Section>

  {#if port}
    <Section title="{port.name}{port.comment ? ' · ' + port.comment : ''}" src="port">
      <Stats cols={4} items={[
        { n: 'link', v: port.disabled ? 'disabled' : port.running ? `${speedText(port.speed)} ${port.duplex}` : 'down', s: port.running ? (port.speed < 1000 && !port.name.startsWith('sfp') ? 'warn' : 'ok') : 'off' },
        { n: 'received', v: bytes(port.rx, 1) }, { n: 'sent', v: bytes(port.tx, 1) },
        { n: 'link downs', v: port.linkDowns, s: port.linkDowns > 50 ? 'warn' : null },
        { n: 'crc errors', v: port.fcs.toLocaleString(), s: port.fcsGrowth > 0 ? 'warn' : null },
        { n: 'rx errors', v: port.rxErr }, { n: 'tx drops', v: port.txDrop },
        { n: 'poe', v: port.poe ? (poeOn(port) ? `${port.poe.watts.toFixed(1)} W` : port.poe.status || port.poe.mode) : 'none', s: port.poe && poeBad(port.poe.status) ? 'warn' : null },
      ]} />
      <div class="row">
        <ActionButton {ctx} method="PATCH" path={`/interface/ethernet/${port.name}`} body={{ disabled: port.disabled ? 'false' : 'true' }}
          label={`${port.disabled ? 'enable' : 'disable'} ${port.name}`} icon={port.disabled ? 'play' : 'close'} small
          confirm={port.disabled ? false : `disable ${port.name}? Anything behind it loses its link.`}>{port.disabled ? 'enable port' : 'disable port'}</ActionButton>
        {#if port.poe && port.poe.mode !== 'off'}
          <ActionButton {ctx} path="/interface/ethernet/poe/power-cycle" body={{ numbers: port.name, duration: '5s' }}
            label={`power-cycle ${port.name}`} icon="restart" small confirm={`cut PoE power on ${port.name} for 5 s?`}>power-cycle poe</ActionButton>
        {/if}
      </div>
    </Section>
  {/if}

  <Section title="vlans · bridge table" src="mikrotik">
    <Lazy of={vlans} empty="no bridge VLANs">
      {#snippet children()}
        <Table rows={vlanRows || []} key={(r) => `${r.bridge}/${r.vlan}`} columns={vcols} label="bridge VLANs" minWidth={420} empty="no VLANs" />
      {/snippet}
    </Lazy>
  </Section>
</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
