<script>
  // ~/ai usage: month-to-date spend against the hard cap, per person and per kind, per day, and the last calls.
  import { untrack } from 'svelte';
  import { clock } from '$lab/sdk.js';
  let { data, ctx } = $props();
  let u = $state(null);
  async function load() { try { u = await untrack(() => ctx).api.get('/api/usage'); } catch (e) { u = { error: e.message }; } }
  $effect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); });
  const m = $derived(data?.month);
  const pct = (a, b) => (b ? Math.min(100, (100 * a) / b) : 0);
  const lvl = (p) => (p >= 100 ? 'bad' : p >= 80 ? 'warn' : 'ok');
  const day = (ts) => new Date(ts * 1000).toLocaleDateString('nb-NO', { day: '2-digit', month: '2-digit' });
  const maxDay = $derived(Math.max(0.0001, ...((u?.days || []).map((d) => d.c))));
  const k = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : `${n}`);
</script>

{#if !m}<p class="mono dim pad spin">loading</p>{:else}
<div class="uv fade">
  <div class="bar mono"><span><span class="sig">~/ai</span> usage</span><span class="dim">claude-opus-5-5 · $4 in / $20 out per MTok · cache read $0.20 · since {day(m.start)}, resets {day(m.reset)}</span></div>
  <section class="sec">
    <div class="big mono"><span class={lvl(pct(m.spent, m.cap))}>${m.spent.toFixed(2)}</span><span class="dim"> of ${m.cap} cap</span></div>
    <div class="track"><div class="fill grow {lvl(pct(m.spent, m.cap))}" style:width="{pct(m.spent, m.cap)}%"></div></div>
    <div class="rows mono">
      {#each Object.entries(m.byUser).sort((a, b) => b[1] - a[1]) as [who, c]}
        <div class="r"><span class="w">{who}</span><span>${c.toFixed(2)}</span>
          {#if !who.startsWith('(')}<span class="faint">{who === ctx.me?.username ? `of $${m.myCap.toFixed(0)}` : ''}</span>{/if}</div>
      {/each}
      {#each Object.entries(m.byKind) as [kind, c]}<div class="r dim"><span class="w">{kind}</span><span>${c.toFixed(2)}</span></div>{/each}
    </div>
  </section>
  {#if u?.days?.length}
    <section class="sec">
      <div class="cap">~/per day</div>
      <div class="days">
        {#each u.days as d}<div class="d" title="{d.day}: ${d.c.toFixed(3)} · {d.n} calls"><div class="col" style:height="{Math.max(2, (60 * d.c) / maxDay)}px"></div><span class="mono faint">{d.day.slice(8)}</span></div>{/each}
      </div>
    </section>
  {/if}
  {#if u?.recent?.length}
    <section class="sec">
      <div class="cap">~/last calls</div>
      <div class="scroll-x"><table class="mono">
        <thead><tr class="cap"><th>time</th><th>who</th><th>kind</th><th>in</th><th>out</th><th>cache r/w</th><th>$</th></tr></thead>
        <tbody>{#each u.recent as r}<tr><td class="dim">{clock(r.ts)}</td><td>{r.user}</td><td class="dim">{r.kind}</td><td>{k(r.input)}</td><td>{k(r.output)}</td>
          <td class="dim">{k(r.cache_read)}/{k(r.cache_write_5m + r.cache_write_1h)}</td><td>{r.cost.toFixed(4)}</td></tr>{/each}</tbody>
      </table></div>
    </section>
  {/if}
</div>
{/if}

<style>
  .pad { padding: 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 10px 16px; border-bottom: 1px solid var(--line); font-size: 12px; }
  .sec { padding: 12px 16px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; max-width: 760px; }
  .big { font-size: 28px; }
  .track { height: 6px; background: var(--track); border-radius: 3px; overflow: hidden; }
  .fill { height: 100%; background: var(--ok); }
  .fill.warn { background: var(--warn); } .fill.bad { background: var(--bad); }
  .rows { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
  .r { display: flex; gap: 12px; }
  .w { width: 120px; }
  .days { display: flex; align-items: flex-end; gap: 3px; height: 80px; overflow-x: auto; }
  .d { display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 9px; }
  .col { width: 12px; background: var(--sig); border-radius: 2px 2px 0 0; }
  table { border-collapse: collapse; font-size: 11.5px; }
  th { text-align: left; font-weight: normal; padding: 4px 8px; border-bottom: 1px solid var(--line); }
  td { padding: 3px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
</style>
