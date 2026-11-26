<script>
  // ~/<module>/home — the page the shell generates for a module without views of its own: what it is, its kpis,
  // its open alerts, its tiles and every object it knows (click → object panel).
  import { lab } from '$lab/lab.svelte.js';
  import Icon from '$lab/Icon.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import { ago, statusVar, RANK } from '$lab/fmt.js';

  let { module: mid } = $props();
  const m = $derived(lab.active.find((x) => x.id === mid));
  const health = $derived(lab.registry?.health?.[mid]);
  const kpis = $derived(lab.kpis.filter((k) => k.module === mid));
  const alerts = $derived(lab.alerts.filter((a) => a.module === mid));
  const tiles = $derived(lab.tiles.filter((t) => t.module === mid));
  let q = $state('');
  const objects = $derived([...lab.objects.values()].filter((o) => (o.sources || []).includes(mid))
    .sort((a, b) => RANK[b.status] - RANK[a.status] || String(a.name).localeCompare(String(b.name))));
  const shown = $derived(q ? objects.filter((o) => `${o.name} ${o.kind || ''} ${o.type || ''} ${o.parent || ''} ${o.meta || ''}`.toLowerCase().includes(q.toLowerCase())) : objects);
  const mstate = $derived(health?.up === false ? 'bad' : lab.errors[mid] ? 'warn' : lab.denied[mid] ? 'off' : lab.data[mid] != null ? 'ok' : 'unknown');
  const stateTxt = $derived(health?.up === false ? `backend down${health.error ? ' · ' + health.error : ''}` : lab.errors[mid] ? lab.errors[mid]
    : lab.denied[mid] ? 'no account for you in this app' : lab.data[mid] != null ? 'up' : 'loading');
</script>

{#if m}
  <div class="mh fade">
    <header class="hd">
      <Icon name={m.icon || 'node'} size={22} />
      <div class="t">
        <h1>{m.name}</h1>
        <span class="mono dim meta">~/{m.category || 'other'} · {m.id}{m.kind ? ` · ${m.kind}` : ''}{m.version ? ` · v${m.version}` : ''}</span>
      </div>
      <span class="mono st"><Glyph status={mstate} /> {stateTxt}</span>
    </header>
    {#if m.description}<p class="desc">{m.description}</p>{/if}

    {#if kpis.length}
      <section class="kpis" aria-label="Summary">
        {#each kpis as k}
          <div class="kpi"><span class="cap">{k.label}</span>
            <span><span class="mono v" style:color={k.status ? statusVar(k.status) : 'var(--ink)'}>{k.value}</span> <span class="mono dim s">{k.sub || ''}</span></span></div>
        {/each}
      </section>
    {/if}

    {#if alerts.length}
      <section>
        <div class="sh"><span class="cap">~/alerts · {alerts.length}</span></div>
        {#each alerts as a (a.key)}
          <div class="al row">
            <Glyph status={a.status} />
            <button class="lnk" onclick={() => a.object && lab.open(a.object)} disabled={!a.object}>{a.title}</button>
            <span class="mono dim d">{a.detail || ''}</span>
            <span class="mono dim">{ago(a.since, lab.now)} ago</span>
          </div>
        {/each}
      </section>
    {/if}

    {#if tiles.length && lab.data[mid] != null}
      <section class="tiles">
        {#each tiles as t (t.key)}
          {@const C = t.component}
          <article class="tile" style:grid-column="span {Math.min(12, (t.w || 2) * 2)}" style:max-height="{(t.h || 1) * 146}px">
            <span class="cap"><span class="faint">~/</span>{t.label}</span>
            <div class="tb"><C data={lab.data[mid]} ctx={lab.ctx(mid)} {...(t.props || {})} /></div>
          </article>
        {/each}
      </section>
    {/if}

    <section>
      <div class="sh"><span class="cap">~/objects · {objects.length}</span>
        {#if objects.length > 8}<input class="field mono f" placeholder="$ grep objects…" bind:value={q} aria-label="Filter objects" />{/if}</div>
      {#if objects.length}
        <div class="scroll-x">
          <div class="tbl">
            <div class="cap grid thead"><span></span><span>name</span><span>type</span><span>kind</span><span>on</span><span>details</span></div>
            {#each shown.slice(0, 400) as o (o.id)}
              <button class="grid row orow" class:selrow={lab.panelOpen && lab.sel === o.id} onclick={() => lab.open(o.id)}>
                <Glyph status={o.status} size={10} />
                <span class="nm">{o.name}</span>
                <span class="mono dim">{o.type || ''}</span>
                <span class="mono dim">{o.kind || ''}</span>
                <span class="mono dim">{o.parent || ''}</span>
                <span class="mono dim det">{o.meta || ''}</span>
              </button>
            {/each}
            {#if shown.length > 400}<div class="mono dim pad">… {shown.length - 400} more — narrow with grep</div>{/if}
          </div>
        </div>
      {:else}
        <p class="mono dim pad">{lab.data[mid] == null ? (lab.denied[mid] ? 'nothing for you here' : 'loading …') : 'this module adds no objects — its facets show up on other objects'}</p>
      {/if}
    </section>
  </div>
{:else}
  <p class="mono dim pad">module “{mid}” is not available to you</p>
{/if}

<style>
  .hd { display: flex; align-items: center; gap: 14px; padding: 18px 20px 6px; flex-wrap: wrap; color: var(--sig); }
  .t { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; color: var(--ink); }
  h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -.02em; }
  .meta { font-size: 11.5px; }
  .st { font-size: 12px; color: var(--dim); }
  .desc { margin: 0; padding: 0 20px 12px; color: var(--dim); font-size: 13px; max-width: 760px; }
  section { border-top: 1px solid var(--line); }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
  .kpi { padding: 12px 20px; display: flex; flex-direction: column; gap: 4px; border-right: 1px solid var(--line); }
  .v { font-size: 22px; font-weight: 500; letter-spacing: -.03em; }
  .s { font-size: 12px; }
  .sh { display: flex; align-items: center; gap: 12px; padding: 12px 20px 8px; }
  .f { max-width: 240px; padding: 5px 9px; font-size: 12px; }
  .al { display: grid; grid-template-columns: 14px minmax(0, 1.2fr) minmax(0, 1fr) auto; gap: 10px; padding: 6px 20px; align-items: baseline; font-size: 13px; border-top: 1px solid var(--q); }
  .al .lnk { overflow-wrap: anywhere; }
  .al .lnk:disabled { cursor: default; color: var(--ink); }
  .d { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tiles { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 10px; padding: 14px 20px; align-items: start; }
  .tile { background: var(--panel); border: 1px solid var(--line); border-radius: 4px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; min-width: 0; overflow: hidden; }
  .tb { display: flex; flex-direction: column; min-height: 0; overflow: auto; }
  .tbl { min-width: 640px; }
  .grid { display: grid; grid-template-columns: 18px minmax(140px, 1.2fr) 80px 100px 110px minmax(0, 2fr); gap: 10px; align-items: center; padding: 5px 20px; }
  .thead { padding: 6px 20px; border-bottom: 1px solid var(--line); }
  .orow { width: 100%; border: none; border-bottom: 1px solid var(--q); background: transparent; text-align: left; color: var(--ink); }
  .selrow { background: var(--raise); box-shadow: inset 2px 0 0 var(--sig); }
  .nm { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .grid > .mono { font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pad { padding: 14px 20px; font-size: 12px; }
  @media (max-width: 900px) { .tile { grid-column: span 12 !important; } .al { grid-template-columns: 14px minmax(0, 1fr) auto; } .al .d { display: none; } }
</style>
