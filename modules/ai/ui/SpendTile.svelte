<script>
  // wall tile: this month's AI spend against the cap
  let { data } = $props();
  const m = $derived(data?.month);
  const p = $derived(m ? Math.min(100, (100 * m.spent) / m.cap) : 0);
  const lvl = $derived(p >= 100 ? 'bad' : p >= 80 ? 'warn' : 'ok');
</script>

{#if m}
  <div class="t">
    <span class="mono big {lvl}">${m.spent.toFixed(2)}</span>
    <span class="mono dim">of ${m.cap} · you ${m.mine.toFixed(2)}</span>
    <div class="track"><div class="fill grow {lvl}" style:width="{p}%"></div></div>
  </div>
{/if}

<style>
  .t { display: flex; flex-direction: column; gap: 4px; margin-top: auto; }
  .big { font-size: 30px; font-weight: 500; }
  .dim { font-size: 11px; }
  .track { height: 4px; background: var(--track); border-radius: 2px; overflow: hidden; }
  .fill { height: 100%; background: var(--ok); }
  .fill.warn { background: var(--warn); } .fill.bad { background: var(--bad); }
</style>
