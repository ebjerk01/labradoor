<script>
  // Jellyfin's log files (newest first); one opens as its last lines, filterable, warnings/errors marked.
  import { ago, bytes } from '$lab/fmt.js';
  import { lazy, errText } from '$lab/sdk.js';
  import { textGet } from './store.svelte.js';
  let { ctx } = $props();

  const files = lazy(() => ctx, () => '/System/Logs');
  let name = $state(null);
  let text = $state('');
  let err = $state('');
  let busy = $state(false);
  let q = $state('');
  let level = $state('all');
  let tail = $state(400);
  async function show(n) {
    name = n;
    busy = true;
    err = '';
    try { text = await textGet(ctx, '/System/Logs/Log', { name: n }); } catch (e) { err = errText(e); text = ''; }
    busy = false;
  }
  $effect(() => { const f = files.data; if (f?.length && !name) show(f.slice().sort((a, b) => Date.parse(b.DateModified) - Date.parse(a.DateModified))[0].Name); });
  // a log entry starts with "[time] [LVL]"; continuation lines (stack traces) stay with their entry
  const entries = $derived.by(() => {
    const out = [];
    for (const l of text.split('\n')) {
      if (/^\[\d/.test(l) || !out.length) out.push(l);
      else out[out.length - 1] += '\n' + l;
    }
    return out;
  });
  const lvl = (e) => (/^\[[^\]]+\] \[(ERR|FTL)\]/.test(e) ? 'bad' : /^\[[^\]]+\] \[WRN\]/.test(e) ? 'warn' : '');
  const shown = $derived(entries.filter((e) => (level === 'all' || (level === 'warn' ? lvl(e) : lvl(e) === 'bad')) && (!q || e.toLowerCase().includes(q.toLowerCase()))).slice(-tail));
  const sorted = $derived((files.data || []).slice().sort((a, b) => Date.parse(b.DateModified) - Date.parse(a.DateModified)));
</script>

<div class="bar">
  <select class="field" value={name} onchange={(e) => show(e.currentTarget.value)} aria-label="Log file">
    {#each sorted as f (f.Name)}<option value={f.Name}>{f.Name} · {bytes(f.Size)} · {ago(Date.parse(f.DateModified) / 1000, ctx.now)}</option>{/each}
  </select>
  <select class="field" bind:value={level} aria-label="Level"><option value="all">all</option><option value="warn">warnings + errors</option><option value="bad">errors</option></select>
  <input class="field q" placeholder="filter" bind:value={q} aria-label="Filter log" />
  <select class="field" bind:value={tail} aria-label="Lines"><option value={200}>last 200</option><option value={400}>last 400</option><option value={2000}>last 2000</option></select>
  <button class="btn x" onclick={() => name && show(name)}>reload</button>
  {#if busy || files.loading}<span class="mono dim spin"></span>{/if}
</div>
{#if files.error || err}<p class="mono bad s">{files.error || err}</p>{/if}
<pre class="log mono">{#each shown as e, i (i)}<span class:bad={lvl(e) === 'bad'} class:warn={lvl(e) === 'warn'}>{e}
</span>{:else}<span class="dim">{busy ? 'loading' : 'nothing matches'}</span>{/each}</pre>
<span class="mono dim s">{shown.length} of {entries.length} entries</span>

<style>
  .bar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 6px; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font-size: 12px; color: var(--ink); min-width: 0; max-width: 100%; }
  .q { flex: 1 1 120px; }
  .x { padding: 4px 8px; }
  .log { font-size: 11px; line-height: 1.5; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 8px 10px; margin: 0;
    max-height: 65vh; overflow: auto; white-space: pre-wrap; word-break: break-word; color: var(--dim); }
  .bad { color: var(--bad); }
  .warn { color: var(--warn); }
  .s { font-size: 10.5px; }
</style>
