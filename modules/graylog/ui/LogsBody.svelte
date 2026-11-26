<script>
  // ~/logs — Graylog search (Lucene syntax), time range, source + stream filter, live tail; pins, saved searches,
  // streams, security searches and events on the side. Lines are data: shown as text, never acted on.
  import { untrack } from 'svelte';
  import Spark from '$lab/Spark.svelte';
  import Icon from '$lab/Icon.svelte';
  import Lines from '$lab/Lines.svelte';
  import { ago, act, poll } from '$lab/sdk.js';
  import { messages, series, bucket, anyOf, webUrl, msgUrl, lvl, hms, one, short, ts, RANGES, SECURITY, DEFAULT_STREAM } from './gl.js';
  import { logq, searchLogs } from './state.svelte.js';
  let { data, ctx } = $props();
  const cfg = $derived(data.cfg);
  const search = (o) => searchLogs(ctx, o);

  const LIMIT = 100;
  let input = $state(logq.q);
  let rows = $state([]);
  let total = $state(null);
  let hist = $state([]);
  let busy = $state(false);
  let err = $state('');
  let open = $state(null);
  let fresh = $state(new Set());
  let took = $state(null);
  let srcFilter = $state('');

  const full = $derived.by(() => {
    const base = (logq.q || '').trim() || '*';
    if (!logq.sources.length) return base;
    const s = anyOf('source', logq.sources);
    return base === '*' ? s : `(${base}) AND ${s}`;
  });

  let seq = 0;
  async function run({ quiet = false, more = false } = {}) {
    const my = ++seq, q = full, range = logq.range, stream = logq.stream, t0 = performance.now();
    if (!quiet) busy = true;
    try {
      const [m, h] = await Promise.all([
        messages(ctx, q, { range, limit: LIMIT, stream, fields: '', offset: more ? rows.length : 0 }),
        more ? Promise.resolve(hist) : series(ctx, q, range, bucket(range), stream),
      ]);
      if (my !== seq) return;
      const before = new Set(rows.map((r) => r._id));
      fresh = quiet && rows.length ? new Set(m.list.filter((r) => !before.has(r._id)).map((r) => r._id)) : new Set();
      rows = more ? [...rows, ...m.list] : m.list;
      total = m.total; hist = h; err = ''; took = Math.round(performance.now() - t0);
    } catch (e) {
      if (my === seq) err = e.body?.message || e.message;
    } finally { if (my === seq) busy = false; }
  }

  // a new search (from here, a facet, a tile): logq.run bumps
  $effect(() => {
    logq.run;
    untrack(() => { input = logq.q; open = null; run(); });
  });
  // live tail: re-run every 5 s while on, new lines flash
  $effect(() => {
    if (!logq.live) return;
    const p = poll(() => { if (!busy) run({ quiet: true }); }, 5000, { immediate: false });
    return () => p.stop();
  });

  // the 10 minutes around one line (absolute range)
  const around = (t) => { const x = ts(t) * 1000; return { from: new Date(x - 300000).toISOString(), to: new Date(x + 300000).toISOString() }; };

  function submit(e) { e.preventDefault(); logq.q = input.trim() || '*'; logq.run++; }
  function setRange(r) { logq.range = r; logq.run++; }
  function toggleSrc(src) {
    logq.sources = logq.sources.includes(src) ? logq.sources.filter((x) => x !== src) : [...logq.sources, src];
    logq.run++;
  }

  // pins: per user, in lab prefs
  const pins = $derived(ctx.prefs.get('pins', []));
  function pin() {
    const name = prompt('name for this search', logq.q.slice(0, 40));
    if (!name) return;
    ctx.prefs.set('pins', [...pins.filter((p) => p.name !== name), { name, q: logq.q, range: logq.range, sources: logq.sources, stream: logq.stream }]);
  }
  const unpin = (p) => ctx.prefs.set('pins', pins.filter((x) => x !== p));

  // Graylog saved searches: the query lives in the search behind the view
  const saved = $derived(data.views.filter((v) => v.type === 'SEARCH'));
  const dashboards = $derived(data.views.filter((v) => v.type === 'DASHBOARD'));
  async function loadSaved(v) {
    try {
      const s = await ctx.api.get(`/api/views/search/${encodeURIComponent(v.search_id)}`);
      const qq = s.queries?.[0];
      search({ q: qq?.query?.query_string || '*', range: qq?.timerange?.range || 3600, stream: qq?.filter?.filters?.[0]?.id || '' });
    } catch (e) { ctx.notify(`saved search: ${e.body?.message || e.message}`, 'bad'); }
  }

  // streams: list + create (admin). New streams go to the default index set, start right away.
  let ns = $state(null);
  const canNew = $derived(ctx.can('POST', '/api/streams') !== 'no');
  const ruleText = (s) => (s.rules || []).map((r) => `${r.inverted ? '!' : ''}${r.field}${r.type === 1 ? '=' : '~'}${r.value}`).join(s.matching_type === 'OR' ? ' | ' : ' & ');
  async function createStream(e) {
    e.preventDefault();
    const idx = data.streams.find((s) => s.id === DEFAULT_STREAM)?.index_set_id;
    if (!idx) return ctx.notify('no default index set found', 'bad');
    const title = ns.title.trim();
    const made = await act(ctx, { path: '/api/streams', label: 'create log stream', quiet: true, body: {
      title, description: `made in lab by ${ctx.me?.username || '?'}`,
      matching_type: 'AND', remove_matches_from_default_stream: false, index_set_id: idx,
      rules: [{ field: ns.field.trim(), type: ns.exact ? 1 : 2, value: ns.value.trim(), inverted: false, description: '' }] } });
    if (!made?.stream_id) return;
    const started = await act(ctx, { path: `/api/streams/${encodeURIComponent(made.stream_id)}/resume`, body: {}, label: 'start log stream', ok: `stream ${title} created` });
    if (started) ns = null;
  }

  // security: counts + who for ssh/sudo (24 h, from up to 200 lines). Failed-login NUMBERS are drift's.
  let sec = $state({});
  async function loadSec() {
    const out = {};
    await Promise.all(SECURITY.filter((s) => !s.drift).map(async (s) => {
      try {
        const m = await messages(ctx, s.q, { range: 86400, limit: s.who ? 200 : 1, fields: 'message,source' });
        const who = {};
        if (s.who) for (const r of m.list) { const x = String(r.message).match(s.who); if (x) { const k = `${x[1]}→${r.source}`; who[k] = (who[k] || 0) + 1; } }
        out[s.id] = { n: m.total, who: Object.entries(who).sort((a, b) => b[1] - a[1]).slice(0, 4) };
      } catch { out[s.id] = { n: null, who: [] }; }
    }));
    sec = out;
  }
  poll(loadSec, 120000);

  const defsById = $derived(Object.fromEntries(data.defs.map((x) => [x.id, x])));
  const srcList = $derived(data.sources.filter((s) => !srcFilter || s.src.includes(srcFilter.toLowerCase()) || s.id.includes(srcFilter.toLowerCase())));
  const shown = (r) => Object.entries(r).filter(([k]) => !k.startsWith('gl2_') && !['_id', 'index', 'streams'].includes(k)).sort(([a], [b]) => a.localeCompare(b));
</script>

<div class="lv fade">
  <form class="bar" onsubmit={submit}>
    <span class="mono sig pr">$</span>
    <input class="field mono q" bind:value={input} placeholder='source:"web" AND level:<=4' aria-label="Graylog query" spellcheck="false" />
    <div class="seg" role="group" aria-label="Time range">
      {#each RANGES as [r, l]}<button type="button" aria-pressed={logq.range === r} onclick={() => setRange(r)}>{l}</button>{/each}
    </div>
    <select class="field mono sel" bind:value={logq.stream} onchange={() => logq.run++} aria-label="Stream">
      <option value="">all streams</option>
      {#each data.streams as s}<option value={s.id}>{s.title}</option>{/each}
    </select>
    <button type="button" class="btn" class:primary={logq.live} aria-pressed={logq.live} onclick={() => (logq.live = !logq.live)}>
      <Icon name="play" size={12} />{logq.live ? 'live 5s' : 'tail'}
    </button>
    <button class="btn primary"><Icon name="search" size={12} />search</button>
  </form>

  <div class="grid">
    <main>
      <div class="sum mono">
        {#if busy}<span class="spin dim">searching</span>{:else if err}<span class="bad">■ {err}</span>{:else}
          <span>{short(total)} lines</span><span class="dim">· {took}ms</span>{/if}
        {#each logq.sources as s}<button class="chip on" onclick={() => toggleSrc(s)} title="remove filter">{s} ×</button>{/each}
        <span class="sp"></span>
        <button class="lnk dim" onclick={pin} title="pin this search">pin</button>
        {#if webUrl(cfg, full, logq.range)}<a class="dim" href={webUrl(cfg, full, logq.range)} target="_blank" rel="noopener">open in graylog ↗</a>{/if}
      </div>
      <Spark values={hist} color="var(--sig)" height={34} area />

      <div class="log mono" role="list">
        {#each rows as r (r._id)}
          {@const l = lvl(r.level)}
          <div role="listitem" class="row" class:new={fresh.has(r._id)} class:sel={open === r._id}>
            <button class="ln" onclick={() => (open = open === r._id ? null : r._id)} aria-expanded={open === r._id}>
              <span style:color={l.c} title={l.n}>{l.g}</span>
              <span class="t">{hms(r.timestamp)}</span>
              <span class="s">{r.source}</span>
              <span class="a">{r.application_name || ''}</span>
              <span class="m">{one(r.message, 600)}</span>
            </button>
            {#if open === r._id}
              <div class="kv">
                {#each shown(r) as [k, v]}<span class="k">{k}</span><span class="v">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>{/each}
                <span class="k"></span><span class="v acts">
                  <button class="lnk sig" onclick={() => toggleSrc(r.source)}>filter {r.source}</button>
                  {#if r.application_name}<button class="lnk sig" onclick={() => search({ q: anyOf('application_name', [r.application_name]), range: logq.range, sources: logq.sources })}>only {r.application_name}</button>{/if}
                  <button class="lnk sig" onclick={() => search({ q: '*', range: around(r.timestamp), sources: [r.source] })}>±5m on {r.source}</button>
                  {#if msgUrl(cfg, r)}<a href={msgUrl(cfg, r)} target="_blank" rel="noopener">open in graylog ↗</a>{/if}
                </span>
              </div>
            {/if}
          </div>
        {:else}
          {#if !busy}<div class="dim empty">{err ? 'search failed' : 'no lines'}</div>{/if}
        {/each}
        {#if rows.length && total > rows.length && !logq.live}
          <button class="btn more" onclick={() => run({ more: true })}>{busy ? 'loading' : `more · ${short(total - rows.length)} left`}</button>
        {/if}
      </div>
    </main>

    <aside>
      <section>
        <div class="h"><span class="cap">~/sources 1h</span><input class="field mono f" bind:value={srcFilter} placeholder="filter" aria-label="Filter sources" /></div>
        <div class="srcs">
          {#each srcList as s (s.src)}
            <div class="src" class:on={logq.sources.includes(s.src)}>
              <button class="lnk mono" onclick={() => toggleSrc(s.src)} title="filter on {s.src}">{s.src}</button>
              {#if s.known}<button class="lnk faint o" onclick={() => ctx.open(s.id)} title="open {s.id}" aria-label="open {s.id}">→</button>{:else}<span class="faint o" title="no lab object">?</span>{/if}
              <span class="mono dim n">{short(s.n1h)}</span>
            </div>
          {/each}
        </div>
      </section>

      <section>
        <div class="h"><span class="cap">~/pinned</span></div>
        {#each pins as p}
          <div class="it"><button class="lnk mono" onclick={() => search(p)}>{p.name}</button><button class="lnk faint" onclick={() => unpin(p)} aria-label="unpin {p.name}">×</button></div>
        {:else}<span class="mono faint small">pin a search to keep it here (yours only)</span>{/each}
        {#each saved as v}
          <div class="it"><button class="lnk mono" onclick={() => loadSaved(v)}>{v.title}</button>{#if cfg.web}<a class="faint" href="{cfg.web}/search/{v.id}" target="_blank" rel="noopener">↗</a>{/if}</div>
        {/each}
        {#each dashboards as v}
          {#if cfg.web}<div class="it"><a class="mono" href="{cfg.web}/dashboards/{v.id}" target="_blank" rel="noopener">▦ {v.title}</a></div>{/if}
        {/each}
      </section>

      <section>
        <div class="h"><span class="cap">~/streams</span>{#if canNew}<button class="lnk sig small" onclick={() => (ns = ns ? null : { title: '', field: 'source', value: '', exact: true })}>{ns ? 'cancel' : '+ new'}</button>{/if}</div>
        {#if ns}
          <form class="ns" onsubmit={createStream}>
            <input class="field mono" bind:value={ns.title} placeholder="title" required aria-label="Stream title" />
            <div class="r2">
              <input class="field mono" bind:value={ns.field} placeholder="field" required aria-label="Rule field" />
              <input class="field mono" bind:value={ns.value} placeholder={ns.exact ? 'equals' : 'contains'} required aria-label="Rule value" />
            </div>
            <label class="mono small dim"><input type="checkbox" bind:checked={ns.exact} /> exact match (else contains)</label>
            <button class="btn primary">create + start</button>
          </form>
        {/if}
        {#each data.streams as s}
          <div class="it">
            <span style:color={s.disabled ? 'var(--faint)' : 'var(--ok)'}>{s.disabled ? '○' : '●'}</span>
            <button class="lnk mono" onclick={() => search({ q: '*', range: logq.range, stream: s.id })}>{s.title}</button>
            <span class="mono faint small r">{ruleText(s) || (s.is_default ? 'default' : '')}</span>
          </div>
        {/each}
      </section>

      <section>
        <div class="h"><span class="cap">~/security 24h</span></div>
        {#each SECURITY as s}
          <div class="it">
            <button class="lnk mono" onclick={() => search({ q: s.q, range: 86400 })}>{s.label}</button>
            {#if s.drift}
              {#if cfg.security && ctx.object(cfg.security)}<button class="lnk sig small r" onclick={() => ctx.open(cfg.security)}>see numbers</button>{/if}
            {:else}<span class="mono small r">{sec[s.id] ? short(sec[s.id].n) : ''}</span>{/if}
          </div>
          {#if sec[s.id]?.who.length}
            <div class="who mono faint">{sec[s.id].who.map(([k, n]) => `${k} ${n}`).join(' · ')}</div>
          {/if}
        {/each}
      </section>

      <section>
        <div class="h"><span class="cap">~/events 7d</span><span class="mono faint small">{data.defs.length} definitions · {data.defs.filter((x) => x.alert).length} alerting</span></div>
        <Lines items={data.events.slice(0, 8).map((e) => ({ p: e.alert ? '▲' : '●', s: e.alert ? 'warn' : null, c: 'var(--dim)',
          t: `${ago(ts(e.timestamp))} · ${one(defsById[e.event_definition_id]?.title || '', 30)} · ${one(e.message, 160)}` }))} empty="no events" />
      </section>
    </aside>
  </div>
</div>

<style>
  .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .pr { font-size: 14px; }
  .q { flex: 1 1 320px; min-width: 200px; padding: 7px 10px; font-size: 12.5px; }
  .sel { width: auto; padding: 6px 8px; font-size: 12px; }
  .grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; }
  main { padding: 10px 20px 20px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  aside { border-left: 1px solid var(--line); min-width: 0; }
  aside section { padding: 12px 16px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 4px; }
  .h { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px; }
  .sum { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 11.5px; }
  .sum .sp { flex: 1; }
  .sum a { text-decoration: none; }
  .chip { font: 10.5px "Geist Mono Variable", monospace; padding: 1px 6px; border: 1px solid var(--line); border-radius: 3px; background: none; color: var(--dim); }
  .chip.on { border-color: var(--sig); color: var(--sig); }
  .log { font-size: 11.5px; line-height: 1.6; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 4px 0; }
  .row.new { animation: flash 2.5s ease-out; }
  .row.sel { background: var(--q); }
  @keyframes flash { from { background: color-mix(in srgb, var(--sig) 22%, transparent); } to { background: transparent; } }
  .ln { display: grid; grid-template-columns: 12px 64px 120px 120px minmax(0, 1fr); gap: 8px; width: 100%; padding: 0 10px; border: none; background: none;
    text-align: left; color: var(--ink); font: inherit; }
  .ln:hover { background: var(--raise); }
  .ln > span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .t { color: var(--dim); } .s { color: var(--sig); } .a { color: var(--dim); }
  .kv { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 2px 10px; padding: 6px 10px 10px 32px; font-size: 11px; }
  .k { color: var(--dim); } .v { word-break: break-all; white-space: pre-wrap; }
  .acts { display: flex; gap: 12px; flex-wrap: wrap; }
  .empty { padding: 10px; }
  .more { margin: 6px 10px; }
  .f { max-width: 110px; padding: 3px 7px; font-size: 11px; }
  .srcs { max-height: 260px; overflow-y: auto; display: flex; flex-direction: column; }
  .src { display: grid; grid-template-columns: minmax(0, 1fr) 16px 44px; gap: 6px; font-size: 11.5px; align-items: center; }
  .src.on button:first-child { color: var(--sig); }
  .src .o { text-align: center; }
  .n { text-align: right; font-size: 11px; }
  .it { display: flex; gap: 8px; align-items: baseline; font-size: 12px; }
  .it .r { margin-left: auto; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 55%; }
  .it a { text-decoration: none; }
  .small { font-size: 10.5px; }
  .who { font-size: 10.5px; padding-left: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ns { display: flex; flex-direction: column; gap: 6px; margin-bottom: 6px; }
  .ns .field { padding: 5px 8px; font-size: 12px; }
  .r2 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  @media (max-width: 900px) {
    .grid { grid-template-columns: minmax(0, 1fr); }
    aside { border-left: none; border-top: 1px solid var(--line); }
    .ln { grid-template-columns: 12px 60px 90px minmax(0, 1fr); }
    .ln .a { display: none; }
    .bar, main { padding-left: 16px; padding-right: 16px; }
  }
</style>
