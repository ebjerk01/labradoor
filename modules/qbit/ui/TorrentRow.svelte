<script>
  // One torrent: glyph, name, category, progress bar, speeds, eta, seeds. Click the name to list its files.
  import Glyph from '$lab/Glyph.svelte';
  import Bar from '$lab/Bar.svelte';
  import { bytes, rate } from '$lab/fmt.js';
  import { statusOf, eta } from './qb.js';
  let { t, ctx, selected = $bindable(), select = false } = $props();
  let files = $state(null);
  let open = $state(false);

  async function toggle() {
    open = !open;
    if (open && !files) {
      try { files = (await ctx.api.get(`/api/torrents/${t.hash}/files`)).files; } catch (e) { files = []; ctx.notify(e.message, 'bad'); }
    }
  }
  const risky = (n) => /\.(exe|scr|lnk|bat|cmd|vbs|js|ps1|msi|hta|jar|dll|apk|pif)$/i.test(n);
  const pct = $derived(Math.floor((t.progress || 0) * 100));
</script>

<div class="r row" class:withsel={select} class:sel={!!selected}>
  {#if select}<input type="checkbox" bind:checked={selected} aria-label="select {t.name}" />{/if}
  <Glyph status={statusOf(t)} size={10} />
  <button class="lnk nm" title="{t.name} · {t.state} · click for files" onclick={toggle}>{t.name}</button>
  <span class="mono dim c">{t.category || '—'}</span>
  <span class="pb"><Bar value={pct} color={statusOf(t) === 'bad' ? 'var(--bad)' : pct >= 100 ? 'var(--ok)' : 'var(--sig)'} label="{pct}%" /></span>
  <span class="mono n">{pct}%</span>
  <span class="mono n dim sz">{t.size > 0 ? bytes(t.size) : '–'}</span>
  <span class="mono n">{t.dlspeed ? '↓' + rate(t.dlspeed) : ''}{t.upspeed ? ' ↑' + rate(t.upspeed) : ''}</span>
  <span class="mono n dim et">{pct < 100 ? eta(t.eta) : `r ${(t.ratio || 0).toFixed(1)}`}</span>
  <span class="mono n dim pe" title="seeds/peers connected (seeds in swarm)">{t.num_seeds}/{t.num_leechs} ({t.num_complete})</span>
</div>
{#if open}
  <div class="files mono">
    {#if !files}<span class="spin dim">files</span>{/if}
    {#each files || [] as f (f.name)}
      <div class="f" class:bad={risky(f.name)}><span class="fn" title={f.name}>{risky(f.name) ? '■ ' : ''}{f.name}</span><span class="dim">{bytes(f.size)} · {Math.floor(f.progress * 100)}%{f.priority === 0 ? ' · skipped' : ''}</span></div>
    {/each}
  </div>
{/if}

<style>
  .r { display: grid; grid-template-columns: 12px minmax(0, 1fr) 76px 70px 36px 52px 104px 44px 70px; gap: 8px; align-items: center;
    padding: 3px 4px; border-bottom: 1px solid var(--q); font-size: 12px; }
  .r.withsel { grid-template-columns: 16px 12px minmax(0, 1fr) 76px 70px 36px 52px 104px 44px 70px; }
  .sel { background: var(--raise); }
  .nm, .c { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .nm { font-size: 12px; }
  .pb { display: flex; }
  .c, .n { font-size: 10.5px; }
  .n { text-align: right; white-space: nowrap; }
  .files { padding: 4px 8px 8px 28px; font-size: 10.5px; border-bottom: 1px solid var(--q); }
  .f { display: flex; justify-content: space-between; gap: 10px; }
  .fn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  @media (max-width: 900px) {
    .r { grid-template-columns: 12px minmax(0, 1fr) 36px 104px; }
    .r.withsel { grid-template-columns: 16px 12px minmax(0, 1fr) 36px 104px; }
    .c, .pb, .sz, .et, .pe { display: none; }
  }
</style>
