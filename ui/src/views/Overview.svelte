<script>
  import { lab } from '$lab/lab.svelte.js';
  import Glyph from '$lab/Glyph.svelte';
  import Spark from '$lab/Spark.svelte';
  import Bar from '$lab/Bar.svelte';
  import { statusVar, ago, clock, memLevel } from '$lab/fmt.js';

  let closed = $state({});
  let q = $state('');
  let only = $state('all');
  const all = $derived([...lab.objects.values()].filter((o) => o.type === 'machine'));
  const match = (o) => (!q || `${o.name} ${o.kind} ${o.parent || ''} ${o.meta || ''}`.toLowerCase().includes(q.toLowerCase()))
    && (only === 'all' || (only === 'problems' ? ['warn', 'bad'].includes(o.status) || o.alerts : only === 'off' ? o.status === 'off' : only === 'updates' ? o.upd : true));
  const filtering = $derived(!!q || only !== 'all');
  const machines = $derived(filtering ? all.filter((o) => match(o) || all.some((k) => k.parent === o.id && match(k))) : all);
  const groups = $derived.by(() => {
    const tops = machines.filter((o) => !o.parent || !lab.objects.has(o.parent));
    return tops.map((t) => ({ top: t, kids: machines.filter((o) => o.parent === t.id && (!filtering || match(o))).sort((a, b) => (b.mem ?? -1) - (a.mem ?? -1)) }))
      .sort((a, b) => b.kids.length - a.kids.length || a.top.name.localeCompare(b.top.name));
  });
  const memC = (v) => (v == null ? 'var(--faint)' : memLevel(v) === 'ok' ? 'var(--ink)' : statusVar(memLevel(v)));
  // every KPI jumps somewhere: its object, its view, else its module's first page; one that can't looks like plain text
  const kpiGo = (k) => {
    if (k.open && lab.objects.has(k.open)) return { run: () => lab.open(k.open), to: lab.objects.get(k.open).name };
    const v = k.view && lab.nav.resolve(k.view);
    if (v && lab.views.includes(v)) return { run: () => lab.go(v), to: lab.nav.byId.get(v)?.label };
    const first = lab.nav.entries.find((e) => e.module === k.module);
    return first ? { run: () => lab.go(first.id), to: first.label } : null;
  };
  const overviewParts = $derived(lab.active.filter((m) => m.ui.overview && lab.data[m.id] != null && lab.on(m, '_overview')));
</script>

<div class="ov fade">
  {#if lab.kpis.length}
    <section class="kpis" aria-label="Summary">
      {#each lab.kpis as k}
        {@const go = kpiGo(k)}
        {#snippet body()}
          <span class="cap kl">{k.label}{#if go}<span class="arr" aria-hidden="true">→</span>{/if}</span>
          <span class="vline"><span class="mono v" style:color={k.status ? statusVar(k.status) : k.color || 'var(--ink)'}>{k.value}</span><span class="mono dim sub">{k.sub || ''}</span></span>
          {#if k.spark}<Spark values={k.spark} color={k.status ? statusVar(k.status) : 'var(--faint)'} />{/if}
        {/snippet}
        {#if go}<button class="kpi go" onclick={go.run} title="open {go.to}">{@render body()}</button>
        {:else}<div class="kpi">{@render body()}</div>{/if}
      {/each}
    </section>
  {/if}

  <div class="cols">
    <div class="main">
      {#each overviewParts as m (m.id)}
        {@const C = m.ui.overview}
        <C data={lab.data[m.id]} ctx={lab.ctx(m.id)} />
      {/each}

      <div class="filt">
        <input class="field mono" placeholder="$ grep machines…" bind:value={q} aria-label="Filter machines" />
        <div class="seg" role="group" aria-label="Show">
          {#each ['all', 'problems', 'updates', 'off'] as f}<button aria-pressed={only === f} onclick={() => (only = f)}>{f}</button>{/each}
        </div>
        <span class="mono dim">{machines.length}/{all.length}</span>
      </div>
      <div class="scroll-x">
        <div class="tbl">
          <div class="cap thead grid">
            <span></span><span>~/machines</span><span>kind</span><span>cpu ~10m</span><span></span><span>mem</span><span>disk</span><span>updates</span><span>backup</span><span>alerts</span>
          </div>
          {#each groups as g (g.top.id)}
            {@const t = g.top}
            <button class="grid row grp" onclick={() => (g.kids.length ? (closed[t.id] = !closed[t.id]) : lab.open(t.id))}>
              <Glyph status={t.status} />
              <span class="nm"><span class="mono dim chev">{g.kids.length ? (closed[t.id] ? '▸' : '▾') : ' '}</span>{t.name}{#if g.kids.length}<span class="mono dim n">{g.kids.length}</span>{/if}</span>
              <span class="mono dim">{t.kind || ''}</span>
              <Spark values={lab.hist[t.id] || []} fixed100 color="var(--ink)" width="92" />
              <span class="mono">{t.cpu != null ? Math.round(t.cpu) : '–'}</span>
              <span class="bc"><Bar value={t.mem} color={memC(t.mem)} /><span class="mono pv">{t.mem != null ? Math.round(t.mem) : '–'}</span></span>
              <span class="bc"><Bar value={t.disk} color="var(--dim)" /><span class="mono pv">{t.disk != null ? Math.round(t.disk) : '–'}</span></span>
              <span class="mono" class:sig={t.upd}>{t.upd || '·'}</span>
              <span class="mono dim">{t.backup || '—'}</span>
              <span class="mono" class:warn={t.alerts}>{t.alerts || '·'}</span>
            </button>
            {#if !closed[t.id]}
              {#each g.kids as m (m.id)}
                <div class="grid row kid" class:selrow={lab.panelOpen && lab.sel === m.id}>
                  <span class="gl"><Glyph status={m.status} size={10} /></span>
                  <button class="lnk nm2" onclick={() => lab.open(m.id)}>{m.name}</button>
                  <span class="mono dim">{m.kind || ''}</span>
                  <Spark values={lab.hist[m.id] || []} fixed100 color={m.status === 'off' ? 'var(--faint)' : 'var(--dim)'} width="92" />
                  <span class="mono dim">{m.cpu != null ? Math.round(m.cpu) : '–'}</span>
                  <span class="bc"><Bar value={m.mem} height={3} color={memC(m.mem)} /><span class="mono pv dim">{m.mem != null ? Math.round(m.mem) : '–'}</span></span>
                  <span class="bc"><Bar value={m.disk} height={3} color="var(--faint)" /><span class="mono pv dim">{m.disk != null ? Math.round(m.disk) : '–'}</span></span>
                  <span class="mono" class:sig={m.upd} class:faint={!m.upd}>{m.upd || '·'}</span>
                  <span class="mono" class:warn={m.backupStale} class:dim={!m.backupStale}>{m.backup || '—'}</span>
                  <span class="mono" class:warn={m.alerts} class:faint={!m.alerts}>{m.alerts || '·'}</span>
                </div>
              {/each}
            {/if}
          {:else}
            <div class="mono dim pad">no machines yet{lab.loading ? ' …' : ''}</div>
            {#if !lab.loading && !filtering && lab.role === 'owner'}
              <div class="dim pad empty-hint">
                Modules fill this page once they have a connection. Open
                <button class="lnk" onclick={() => lab.go('settings')}>Settings</button> → <span class="mono">~/modules</span>,
                expand a module and fill in its <span class="mono">connection</span>; switch off the ones you don't use.
              </div>
            {/if}
          {/each}
        </div>
      </div>
    </div>

    <aside class="side" aria-label="Alerts">
      <div class="sh"><span class="cap">~/alerts</span>
        <span class="mono dim">{lab.alerts.filter((a) => a.status === 'bad').length} ■ {lab.alerts.filter((a) => a.status === 'warn').length} ▲</span></div>
      {#each lab.alerts.slice(0, 40) as a (a.module + a.key)}
        <div class="al row" class:snz={a.snoozed}>
          <Glyph status={a.status} />
          <div class="alt">
            <button class="lnk t" onclick={() => a.object && lab.open(a.object)}>{a.title}</button>
            <span class="mono dim d">{a.detail || ''}</span>
          </div>
          <div class="alr">
            <span class="mono dim" title="open since {ago(a.since, lab.now)}">{ago(a.since, lab.now)} ago</span>
            {#if a.snooze && lab.ctx(a.module).can('POST', a.snooze.path) === 'yes'}
              <button class="btn zz" title="hide this alert for one day" onclick={() => lab.run({ ...a.snooze, module: a.module, verdict: 'yes', label: 'snooze 1d' })}>snooze 1d</button>
            {/if}
            <span class="mono faint src">{a.module}</span>
          </div>
        </div>
      {:else}
        <div class="mono dim pad">all quiet ●</div>
      {/each}
      <div class="sh"><span class="cap">tail -f events</span></div>
      {#each lab.audit.slice(0, 12) as e (e.id)}
        <div class="ev"><span class="mono dim">{clock(e.ts)}</span><span class="mono sig">{e.module || 'lab'}</span><span class="m">{e.username} · {e.action} {e.target || ''}</span></div>
      {:else}
        <div class="mono dim pad">no events</div>
      {/each}
    </aside>
  </div>
</div>

<style>
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); border-bottom: 1px solid var(--line); }
  .kpi { min-width: 0; padding: 14px 20px; border: none; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); margin-bottom: -1px;
    background: transparent; display: flex; flex-direction: column; gap: 4px; text-align: left; color: var(--ink); }
  .kl { display: flex; gap: 6px; align-items: baseline; }
  .arr { margin-left: auto; color: var(--faint); transition: transform .15s, color .15s; }
  .kpi.go { cursor: pointer; }
  .kpi.go:hover, .kpi.go:focus-visible { background: var(--raise); }
  .kpi.go:hover .arr, .kpi.go:focus-visible .arr { color: var(--sig); transform: translateX(2px); }
  .vline { display: flex; align-items: baseline; gap: 2px 8px; flex-wrap: wrap; min-width: 0; }
  .v { font-size: 26px; font-weight: 500; letter-spacing: -.03em; white-space: nowrap; }
  .sub { font-size: 12px; }
  .cols { display: flex; flex-wrap: wrap; }
  .main { flex: 999 1 640px; min-width: 0; border-right: 1px solid var(--line); }
  .tbl { min-width: 800px; }
  .filt { display: flex; gap: 10px; align-items: center; padding: 10px 20px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
  .filt input { max-width: 260px; padding: 6px 10px; font-size: 12px; }
  .filt .mono { font-size: 11.5px; }
  .grid { display: grid; grid-template-columns: 22px minmax(150px, 1.3fr) 76px 92px 36px minmax(90px, 1fr) minmax(90px, 1fr) 54px 56px 42px; gap: 10px; align-items: center; padding: 6px 20px; }
  .thead { padding: 8px 20px; border-bottom: 1px solid var(--line); }
  .grp { width: 100%; border: none; border-bottom: 1px solid var(--line); background: var(--panel); text-align: left; padding: 9px 20px; }
  .nm { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13.5px; }
  .chev { width: 8px; font-size: 11px; }
  .n { font-weight: 400; font-size: 11px; }
  .kid { border-bottom: 1px solid var(--q); }
  .selrow { background: var(--raise); box-shadow: inset 2px 0 0 var(--sig); }
  .gl { padding-left: 4px; }
  .nm2 { font-size: 13px; padding-left: 16px; }
  .bc { display: flex; align-items: center; gap: 8px; }
  .pv { font-size: 11.5px; width: 26px; text-align: right; }
  .grid > .mono { font-size: 12px; }
  .side { flex: 1 1 300px; max-width: 400px; min-width: 0; }
  .sh { padding: 14px 18px 8px; display: flex; justify-content: space-between; align-items: baseline; }
  .sh .mono { font-size: 12px; }
  .al { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto; gap: 10px; padding: 8px 18px; border-bottom: 1px solid var(--q); align-items: start; }
  .al.snz { opacity: .5; }
  .alt { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .t { font-size: 13px; overflow-wrap: anywhere; text-align: left; }
  .d { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .alr { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; font-size: 11.5px; }
  .zz { padding: 1px 6px; font-size: 10.5px; white-space: nowrap; }
  .src { font-size: 10px; }
  .ev { display: grid; grid-template-columns: 40px 60px minmax(0, 1fr); gap: 8px; padding: 4px 18px; align-items: baseline; font-size: 12px; }
  .ev .mono { font-size: 11px; }
  /* long audit targets (graylog search URLs) pushed the page to 2200px wide */
  .ev .m { min-width: 0; overflow-wrap: anywhere; }
  .pad { padding: 14px 20px; font-size: 12px; }
  .empty-hint { padding-top: 0; line-height: 1.6; max-width: 60ch; }
  .empty-hint .lnk { color: var(--sig); text-decoration: underline; }
</style>
