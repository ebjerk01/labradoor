<script>
  // Calendar lines: [{at, title, sub, hasFile, kind, app?}] — ● on disk, ○ not yet, grouped by day.
  import { day, hhmm } from '../sdk.js';
  let { items = [], limit = 12, ctx } = $props();
  const rows = $derived.by(() => {
    const out = [];
    let last = '';
    for (const it of items.slice(0, limit)) {
      const d = day(it.at);
      out.push({ ...it, head: d !== last ? d : '' });
      last = d;
    }
    return out;
  });
</script>

<div class="cal">
  {#each rows as it, i (i)}
    <div class="r" class:past={it.at < ctx.now}>
      <span class="mono dim d">{it.head}</span>
      <span class="mono g" class:ok={it.hasFile} class:dim={!it.hasFile} title={it.hasFile ? 'on disk' : 'not yet'}>{it.hasFile ? '●' : '○'}</span>
      <span class="t" title="{it.title} · {it.sub}">{it.title} <span class="dim">{it.sub}</span></span>
      <span class="mono dim h">{it.kind === 'tv' ? hhmm(it.at) : ''}</span>
    </div>
  {:else}
    <span class="mono dim s">nothing scheduled</span>
  {/each}
</div>

<style>
  .cal { display: flex; flex-direction: column; }
  .r { display: grid; grid-template-columns: 74px 12px minmax(0, 1fr) 38px; gap: 6px; align-items: baseline; padding: 2px 0; font-size: 12px; }
  .r.past { opacity: .6; }
  .g.ok { color: var(--ok); }
  .d, .h, .s { font-size: 10.5px; }
  .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .h { text-align: right; }
</style>
