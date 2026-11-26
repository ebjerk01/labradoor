<script>
  // Logs on any object: last 30 lines (level = shape + colour), 1h/24h rate, search / open in Graylog.
  import { untrack } from 'svelte';
  import { poll, bytes } from '$lab/sdk.js';
  import Section from '$lab/Section.svelte';
  import Lines from '$lab/Lines.svelte';
  import Metric from '$lab/Metric.svelte';
  import Stats from '$lab/Stats.svelte';
  import Icon from '$lab/Icon.svelte';
  import { queryFor, messages, series, webUrl, lvl, hms, one, short } from './gl.js';
  import { searchLogs } from './state.svelte.js';
  let { object, data, ctx } = $props();

  const qf = $derived(queryFor(object, data));
  const qs = $derived(qf?.q);   // a string: data refreshes every 15 s, the search only re-runs when the query changes
  const multi = $derived(qf && qf.label.includes(' '));
  let span = $state(3600);
  let lines = $state([]);
  let total = $state(null);
  let rate = $state([]);
  let busy = $state(false);
  let err = $state('');
  let inputs = $state(null);

  let seq = 0;
  async function fetchLogs(q, range) {
    const my = ++seq;
    busy = true;
    try {
      const [m, r] = await Promise.all([messages(ctx, q, { range, limit: 30 }), series(ctx, q, range, range > 3600 ? '30m' : '1m')]);
      if (my !== seq) return;   // another object / range was picked meanwhile
      lines = m.list; total = m.total; rate = r; err = '';
    } catch (e) { if (my === seq) err = e.message; } finally { if (my === seq) busy = false; }
  }

  $effect(() => {
    const q = qs, range = span;
    if (!q) return;
    untrack(() => { lines = []; total = null; rate = []; });
    const p = poll(() => fetchLogs(q, range), 15000);   // now, then every 15 s while this tab is visible
    return () => p.stop();
  });

  // the graylog CT itself: ingest health; owner also sees the inputs (owner-only route, may hold config)
  const self = $derived(!!data && object.id === data.cfg.self);
  $effect(() => {
    if (!self || untrack(() => ctx.can('GET', '/api/system/inputstates')) !== 'yes') return;
    untrack(() => ctx).api.get('/api/system/inputstates').then((r) => (inputs = r.states || [])).catch(() => (inputs = null));
  });
</script>

{#if self && data}
  <Section title="graylog" src="graylog · ingest">
    <Stats items={[
      { n: 'per min', v: short(data.perMin) },
      { n: 'errors 1h', v: short(data.errors.total), s: data.errors.total ? 'warn' : null },
      { n: 'journal', v: short(data.journal?.uncommitted ?? null), s: data.journal?.uncommitted > 100000 ? 'warn' : null },
      { n: 'index', v: data.indexer ? bytes(data.indexer.bytes) : '–', s: data.indexer?.health === 'green' ? 'ok' : data.indexer ? 'warn' : null },
    ]} />
    <Metric label="msg/min" values={data.rate} value={short(data.perMin)} color="var(--sig)" />
    {#if inputs}
      <Lines items={inputs.map((s) => ({ p: s.state === 'RUNNING' ? '●' : '■', s: s.state === 'RUNNING' ? 'ok' : 'bad',
        t: `${s.message_input?.title} · ${s.message_input?.attributes?.port ?? ''}` }))} />
    {/if}
  </Section>
{/if}

{#if qf}
  <Section title="logs" src="graylog · {qf.label}">
    <div class="bar">
      <div class="seg" role="group" aria-label="Range">
        <button aria-pressed={span === 3600} onclick={() => (span = 3600)}>1h</button>
        <button aria-pressed={span === 86400} onclick={() => (span = 86400)}>24h</button>
      </div>
      <span class="mono dim n">{#if busy && total == null}<span class="spin"></span>{:else}{short(total)} lines{/if}</span>
      <button class="btn" onclick={() => searchLogs(ctx, { q: qf.q, range: span })}><Icon name="search" size={12} />search</button>
      {#if webUrl(data.cfg, qf.q, span)}<a class="btn" href={webUrl(data.cfg, qf.q, span)} target="_blank" rel="noopener"><Icon name="ext" size={12} />open in graylog</a>{/if}
    </div>
    <Metric label={span === 3600 ? 'per min' : 'per 30m'} values={rate} value={short(rate.at(-1) ?? null)} color="var(--sig)" />
    {#if err}<span class="mono bad e">{err}</span>{/if}
    <Lines items={lines.map((m) => { const l = lvl(m.level); return {
      p: `${l.g} ${hms(m.timestamp)}`, c: l.c,
      t: one(`${multi ? m.source + ' ' : ''}${m.application_name ? m.application_name + ': ' : ''}${m.message}`, 300) }; })}
      empty={busy ? 'searching…' : `no lines in the last ${span === 3600 ? 'hour' : '24 h'}`} />
  </Section>
{:else if data && object.type === 'machine' && !self && data.sources.length}
  <Section title="logs" src="graylog">
    <span class="mono dim e">no lines from “{object.id}” in 24 h{data.cfg.syslog ? `: forwarding to ${data.cfg.syslog} not set up here?` : ''}</span>
  </Section>
{/if}

<style>
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .bar .seg button { padding: 4px 9px; font-size: 11px; }
  .bar .btn { padding: 4px 8px; font-size: 11px; text-decoration: none; }
  .n { flex: 1; font-size: 11px; }
  .e { font-size: 11px; }
</style>
