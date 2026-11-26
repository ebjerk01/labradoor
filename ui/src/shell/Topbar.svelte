<script>
  // Desktop: ~/path · view switch · (map lenses) · live · approvals · $ jump.
  // Phone: ONE row — brand · view switch (icons) · live dot · approvals · search · ☰ (the rail opens as a drawer).
  import { lab } from '$lab/lab.svelte.js';
  import Icon from '$lab/Icon.svelte';
  import { ago } from '$lab/fmt.js';
  const sel = $derived(lab.panelOpen && lab.sel ? lab.objects.get(lab.sel) : null);
  const LENSES = ['status', 'ram', 'updates', 'backup'];
  const pending = $derived(lab.registry?.approvalsPending || 0);
  const entry = $derived(lab.nav.byId.get(lab.view));
  const switchable = $derived(lab.nav.top.filter((e) => ['overview', 'wall', 'map'].includes(e.id)));
  const liveTxt = $derived(Number(lab.prefs.refresh) === 0 ? `paused · ${ago(lab.lastRefresh, lab.now)}`
    : `live ${Number(lab.prefs.refresh) || 15}s · ${ago(lab.lastRefresh, lab.now)}`);
  function bell() {
    lab.drawer = lab.drawer === 'approvals' ? null : 'approvals';
    lab.loadApprovals();
  }
</script>

<header class="top">
  <span class="brand mono" aria-hidden="true"><span class="word">{lab.brand}</span><span class="sig word">/</span></span>
  <nav class="mono path" aria-label="Path">
    <span class="dim">~</span><span class="faint">/</span>{#if entry?.module}<span class="dim">{entry.module}</span><span class="faint">/</span>{/if}<span class="sig">{(entry?.home ? 'home' : entry?.short || lab.view).toLowerCase()}</span>
    {#if sel}<span class="faint">/</span><span class="obj">{sel.name}</span>{/if}
  </nav>
  {#if switchable.length > 1}
    <div class="seg views" role="group" aria-label="View">
      {#each switchable as e (e.id)}
        <button aria-pressed={lab.view === e.id} aria-label={e.label} title={e.label} onclick={() => lab.go(e.id)}><Icon name={e.icon} size={13} /><span class="vl">{e.id}</span></button>
      {/each}
    </div>
  {/if}
  {#if lab.view === 'map'}
    <div class="seg lens" role="group" aria-label="Colour by">
      {#each LENSES as l}<button aria-pressed={lab.lens === l} onclick={() => (lab.lens = l)}>{l}</button>{/each}
    </div>
  {/if}
  <div class="space"></div>
  <span class="mono live" title={liveTxt}>
    <span class="dot pulse"></span>
    {#if lab.loading}<span class="spin lt">sync</span>{:else}<span class="lt">{liveTxt}</span>{/if}
  </span>
  {#if lab.role !== 'guest'}
    <!-- owner: requests to decide; admin: own requests (past ones too) -->
    <button class="btn bell" class:primary={pending > 0} onclick={bell} aria-label="Approvals, {pending} pending" title="approvals · {pending} pending">
      <Icon name="bell" size={13} />{#if pending || lab.role === 'owner'}<span>{pending}</span>{/if}
    </button>
  {/if}
  <button class="jump" onclick={() => (lab.palette = true)} aria-label="Search and run (Ctrl K)">
    <Icon name="search" size={15} /><span class="ph">$ jump · restart · new…</span><kbd class="mono">Ctrl K</kbd>
  </button>
  <button class="btn burger" aria-label="Menu" aria-expanded={lab.drawer === 'menu'} onclick={() => (lab.drawer = lab.drawer === 'menu' ? null : 'menu')}>☰</button>
</header>

<style>
  .top { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 10px 20px; border-bottom: 1px solid var(--line); min-height: 53px; }
  .brand { display: none; }
  .word { font-size: 18px; font-weight: 600; letter-spacing: -.02em; }
  .path { font-size: 13px; display: flex; gap: 6px; align-items: center; min-width: 0; }
  .obj { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .space { flex: 1; }
  .live { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--dim); white-space: nowrap; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--sig); flex: none; }
  .spin { display: inline-flex; flex-direction: row-reverse; gap: 6px; }
  .bell { padding: 6px 9px; }
  .jump { display: flex; align-items: center; gap: 10px; padding: 7px 12px; background: var(--panel); border: 1px solid var(--line);
    border-radius: 4px; min-width: 230px; color: var(--dim); cursor: text; }
  .jump:hover { border-color: var(--faint); }
  .ph { flex: 1; text-align: left; font-size: 13px; }
  kbd { font-size: 11px; border: 1px solid var(--line); padding: 1px 6px; border-radius: 3px; }
  .burger { display: none; font-size: 15px; padding: 4px 10px; }
  @media (max-width: 1100px) { .vl { display: none; } }
  @media (max-width: 860px) {
    /* phone: one row, nothing wraps except the map's lens switch (its own row, map only) */
    .top { flex-wrap: wrap; gap: 6px; padding: 6px 8px; min-height: 0; position: sticky; top: 0; z-index: 20; background: var(--bg); }
    .brand { display: inline-flex; align-items: baseline; padding: 0 4px; }
    .path { display: none; }
    .lt { display: none; }
    .live { padding: 0 4px; }
    .views button { padding: 6px 9px; }
    .jump { min-width: 0; padding: 6px 9px; border: 1px solid var(--line); background: transparent; cursor: pointer; }
    .jump .ph, .jump kbd { display: none; }
    .burger { display: inline-flex; }
    .lens { order: 10; flex: 1 1 100%; overflow-x: auto; }
    .lens button { flex: 1; justify-content: center; }
  }
</style>
