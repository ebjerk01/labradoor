<script>
  // The lab as a map. Zones/hubs/links come from /etc/lab/topology.json (the external + network part), machines from
  // the modules' objects (listed under the hub they run on). Positions are computed, never hand-placed: see
  // $lab/maplayout.js (external band → internet bus → home tree; orthogonal lines that never cross).
  import { lab } from '$lab/lab.svelte.js';
  import Icon from '$lab/Icon.svelte';
  import { statusVar } from '$lab/fmt.js';
  import { layoutMap, roundedPath } from '$lab/maplayout.js';

  const topo = $derived(lab.topology || { zones: [], nodes: [], links: [] });
  const RADIUS = { ok: '50%', warn: '2px', bad: '0', off: '50%', unknown: '50%' };
  const topoIds = $derived(new Set((topo.nodes || []).map((n) => n.id)));

  // machines under each topology node (parent, or listed in the node's children), alphabetical like `tree`
  const guests = $derived.by(() => {
    const out = {};
    const machines = [...lab.objects.values()].filter((o) => o.type === 'machine' && !topoIds.has(o.id));
    for (const n of topo.nodes || []) {
      const kids = machines.filter((o) => o.parent === n.id || (n.children || []).includes(o.id) || (n.children || []).includes(o.name))
        .sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id), 'en', { sensitivity: 'base', numeric: true }));
      if (kids.length) out[n.id] = kids.map((o) => ({ id: o.id, name: o.name || o.id }));
    }
    return out;
  });
  const placed = $derived(new Set([...topoIds, ...Object.values(guests).flat().map((g) => g.id)]));
  const unplaced = $derived([...lab.objects.values()].filter((o) => o.type === 'machine' && !placed.has(o.id) && !(o.parent && placed.has(o.parent))));

  let avail = $state(1200);
  const metaOf = (id) => lab.objects.get(id)?.meta || '';
  const L = $derived(layoutMap(topo, guests, { width: Math.max(320, Math.floor(avail)), metaOf }));
  const nodeOf = $derived(Object.fromEntries((topo.nodes || []).map((n) => [n.id, n])));

  const COLOR = { flow: 'var(--sig2)', sig: 'var(--sig)', bad: 'var(--bad)', dashed: 'var(--dim)', bus: 'var(--sig2)', tree: 'var(--faint)' };
  const lines = $derived(L.edges.map((e) => ({ ...e, d: roundedPath(e.pts), c: COLOR[e.kind] || 'var(--line)',
    w: e.kind === 'bus' ? 2 : e.cls ? 1.4 : 1 })));

  function lensColor(o) {
    if (!o) return 'var(--faint)';
    if (lab.lens === 'status' || o.status === 'off') return statusVar(o.status);
    if (lab.lens === 'ram') return o.mem == null ? 'var(--faint)' : o.mem >= 85 ? 'var(--bad)' : o.mem >= 70 ? 'var(--warn)' : o.mem >= 40 ? 'var(--sig2)' : 'var(--sig)';
    if (lab.lens === 'updates') return o.upd ? 'var(--sig)' : 'var(--faint)';
    if (lab.lens === 'backup') return o.backupStale ? 'var(--warn)' : o.backup ? 'var(--ok)' : 'var(--faint)';
    return 'var(--ink)';
  }
  const dotSize = (o) => Math.round(9 + (o?.mem ?? 10) / 100 * 11);

  // on a narrow screen the canvas scrolls sideways: start with the gateway in view, once
  let wrap = $state(), centred = false;
  $effect(() => {
    const sc = wrap?.parentElement, gw = L.badge?.x ?? L.W / 2;
    if (centred || !sc || !L.hubs.length) return;
    centred = true;
    if (sc.scrollWidth > sc.clientWidth) sc.scrollLeft = Math.max(0, gw - sc.clientWidth / 2);
  });
</script>

<div class="wrap" bind:this={wrap} bind:clientWidth={avail}>
<section class="map fade" aria-label="Topology" style:width="{L.W}px" style:height="{L.H}px">
  {#each L.zones as z (z.id)}
    <div class="zone" class:home={z.home} style:left="{z.x}px" style:top="{z.y}px" style:width="{z.w}px" style:height="{z.h}px" style:border-color={z.tone || 'var(--faint)'}>
      <span class="mono zl" style:left="{z.lx}px" style:color={z.home ? 'var(--dim)' : z.tone || 'var(--dim)'}>{z.label}</span>
    </div>
  {/each}

  <svg width={L.W} height={L.H} viewBox="0 0 {L.W} {L.H}" aria-hidden="true" class="lines">
    {#each lines as l (l.id)}<path d={l.d} class={l.cls} class:dash={l.kind === 'dashed'} style:stroke={l.c} style:stroke-width={l.w}></path>{/each}
  </svg>
  {#each lines.filter((l) => l.label) as l (l.id)}
    <span class="mono elab" style:left="{l.lx}px" style:top="{l.ly}px" style:color={l.kind === 'dashed' ? 'var(--dim)' : l.c}>{l.label}</span>
  {/each}

  {#if L.badge}
    {@const b = L.badge}{@const o = lab.objects.get(b.id)}{@const n = nodeOf[b.id] || {}}
    <button class="badge" style:left="{b.x - b.s / 2}px" style:top="{b.y - b.s / 2}px" onclick={() => lab.open(b.id)} aria-label={n.label || b.id}>
      <span class="dot hub" style:width="{b.s}px" style:height="{b.s}px" style:border-radius="50%" style:border-color={statusVar(o?.status)} style:color={statusVar(o?.status)}>
        <Icon name={n.icon || 'globe'} size={15} />
        {#if lab.sel === b.id && lab.panelOpen}<span class="ring"></span>{/if}
      </span>
      <span class="btxt {b.side}">
        <span class="mono hl" class:sig={lab.sel === b.id}>{n.label || b.id}</span>
        {#if o?.meta || n.meta}<span class="mono hm">{o?.meta || n.meta}</span>{/if}
      </span>
    </button>
  {/if}

  {#each L.hubs as h (h.id)}
    {@const o = lab.objects.get(h.id)}{@const n = nodeOf[h.id] || {}}
    <button class="obj" style:left="{h.x}px" style:top="{h.y - h.s / 2}px" onclick={() => lab.open(h.id)} aria-label={n.label || h.id}>
      <span class="dot hub" style:width="{h.s}px" style:height="{h.s}px" style:border-radius={n.round ? '50%' : '8px'}
        style:border-color={statusVar(o?.status)} style:color={statusVar(o?.status)}>
        <Icon name={n.icon || 'node'} />
        {#if lab.sel === h.id && lab.panelOpen}<span class="ring"></span>{/if}
      </span>
      <span class="mono hl" class:sig={lab.sel === h.id}>{n.label || h.id}</span>
      {#if o?.meta || n.meta}<span class="mono hm">{o?.meta || n.meta}</span>{/if}
    </button>
  {/each}

  {#each L.guests as g (g.id)}
    {@const o = lab.objects.get(g.id)}
    <button class="gst" style:left="{g.x - 10}px" style:top="{g.y}px" onclick={() => lab.open(g.id)} aria-label={o?.name || g.id}>
      <span class="dbox"><span class="dot" style:width="{dotSize(o)}px" style:height="{dotSize(o)}px"
        style:border-radius={RADIUS[o?.status] || '50%'} style:background={lensColor(o)}>
        {#if lab.sel === g.id && lab.panelOpen}<span class="ring"></span>{/if}
      </span></span>
      <span class="mono gl" class:sig={lab.sel === g.id}>{o?.name || g.id}</span>
    </button>
  {/each}

  <div class="legend mono" style:left="{L.legend.x}px" style:top="{L.legend.y}px">
    <span><span class="ok">●</span> ok</span><span><span class="warn">▲</span> warn</span><span><span class="bad">■</span> fault</span>
    <span><span class="dim">○</span> off</span><span>size = ram</span><span class="sig">┄ live traffic</span><span class="sig2">━ internet</span>
  </div>
</section>
</div>
{#if unplaced.length}
  <div class="unplaced mono" aria-label="Machines not on the map" style:width="{avail}px">
    <span class="cap">~/unplaced</span>
    {#each unplaced as o (o.id)}
      <button class="lnk up" onclick={() => lab.open(o.id)}><span style:color={lensColor(o)}>●</span> {o.name}</button>
    {/each}
  </div>
{/if}

<style>
  .wrap { width: 100%; }
  .map { position: relative; margin: 0;
    background-image: radial-gradient(var(--line) 1px, transparent 1px); background-size: 22px 22px; }
  .zone { position: absolute; border: 1px dashed; border-radius: 6px; pointer-events: none; }
  .zone.home { border-style: dotted; }
  .zl { position: absolute; top: -9px; font-size: 11px; line-height: 18px; background: var(--bg); padding: 0 6px; white-space: nowrap; }
  .lines { position: absolute; left: 0; top: 0; overflow: visible; }
  .lines path { fill: none; stroke-linecap: round; }
  .lines path.dash { stroke-dasharray: 4 4; }
  .elab { position: absolute; transform: translate(-50%, -50%); font-size: 9.5px; line-height: 14px; background: var(--bg); padding: 0 4px;
    pointer-events: none; white-space: nowrap; }
  .obj { position: absolute; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; gap: 4px;
    border: none; background: none; padding: 0; }
  .obj:hover .dot, .gst:hover .dot, .badge:hover .dot { outline: 2px solid var(--sig); outline-offset: 2px; }
  .dot { position: relative; display: block; }
  .hub { display: flex; align-items: center; justify-content: center; background: var(--panel); border: 2px solid; }
  .hl { font-size: 11.5px; line-height: 16px; background: var(--bg); padding: 0 4px; white-space: nowrap; }
  .hm { font-size: 10px; line-height: 14px; color: var(--dim); margin-top: -4px; background: var(--bg); padding: 0 4px; white-space: nowrap;
    max-width: 28ch; overflow: hidden; text-overflow: ellipsis; }
  .badge { position: absolute; border: none; background: none; padding: 0; }
  .btxt { position: absolute; left: calc(100% + 6px); top: calc(50% + 4px); display: flex; flex-direction: column; align-items: flex-start; gap: 4px; text-align: left; }
  .btxt.above { top: auto; bottom: calc(50% + 4px); }
  .btxt.left { left: auto; right: calc(100% + 6px); align-items: flex-end; text-align: right; }
  .btxt .hl, .btxt .hm { padding: 0 2px; }
  .gst { position: absolute; transform: translateY(-50%); display: flex; align-items: center; gap: 4px; border: none; background: none;
    padding: 0; height: 20px; }
  .dbox { width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; flex: none; }
  .gl { font-size: 9.5px; line-height: 14px; color: var(--dim); white-space: nowrap; max-width: 18ch; overflow: hidden; text-overflow: ellipsis; }
  .gst:hover .gl { color: var(--ink); }
  .gl.sig { color: var(--sig); }
  .sig2 { color: var(--sig2); }
  .unplaced { position: sticky; left: 0; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 11px; align-items: center; padding: 10px 16px; border-top: 1px solid var(--line); }
  .up { font-size: 11px; }
  .legend { position: absolute; display: flex; flex-wrap: wrap; gap: 14px; font-size: 11px; color: var(--dim);
    background: var(--bg); padding: 4px 8px; border: 1px solid var(--line); border-radius: 4px; white-space: nowrap; }
</style>
