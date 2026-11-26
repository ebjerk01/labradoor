<script>
  // Scrolling events. An item with an object (`object` / `open`) opens it, one with `view` goes there; audit rows open
  // their target when it is a known object, else the log. Hover pauses the scroll so items can be clicked.
  import { lab } from '$lab/lab.svelte.js';
  const target = (x) => {
    const id = x.object || x.open;
    if (id && lab.objects.has(id)) return () => lab.open(id);
    if (x.view && lab.views.includes(lab.nav.resolve(x.view))) return () => lab.go(x.view);
    if (x.audit) return lab.views.includes('log') ? () => lab.go('log') : null;
    return null;
  };
  const base = $derived(lab.ticker.map((x) => ({ ...x, go: target(x) })));
  const items = $derived(base.length ? [...base, ...base] : []);
  const secs = $derived(Math.max(40, base.length * 7));
</script>

{#if items.length}
  <div class="ticker-box" aria-label="Events">
    <div class="track mono" style:animation-duration="{secs}s">
      {#each items as x, n}
        {#if x.go}
          <button class="it go" tabindex={n < base.length ? 0 : -1} onclick={x.go} title="open">
            <span style:color={x.c || 'var(--dim)'}>{x.g || '●'}</span> <span class="sig">{x.s || x.module}</span> {x.m}
          </button>
        {:else}
          <span class="it"><span style:color={x.c || 'var(--dim)'}>{x.g || '●'}</span> <span class="sig">{x.s || x.module}</span> {x.m}</span>
        {/if}
      {/each}
    </div>
  </div>
{/if}

<style>
  .ticker-box { border-bottom: 1px solid var(--line); overflow: hidden; white-space: nowrap; padding: 6px 0; background: var(--panel); }
  .track { display: flex; width: max-content; font-size: 11.5px; color: var(--dim); animation: tick linear infinite; }
  .track:hover, .track:focus-within { animation-play-state: paused; }
  .it { padding: 0 20px; }
  .go { border: none; background: none; font: inherit; color: inherit; cursor: pointer; }
  .go:hover { color: var(--ink); text-decoration: underline; text-decoration-color: var(--sig); text-underline-offset: 3px; }
  @media (prefers-reduced-motion: reduce) { .track { animation: none; } }
</style>
