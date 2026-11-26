<script>
  // The left pane: core views, then every module grouped by category (infrastructure, network, … — routes.js buildNav),
  // each module's views under it; a `$ grep` box; arrow keys move, ←/→ fold. On a phone it is the ☰ drawer.
  import { lab } from '$lab/lab.svelte.js';
  import Icon from '$lab/Icon.svelte';
  import { filterNav } from '$lab/routes.js';
  import { worst } from '$lab/fmt.js';

  let q = $state('');
  let navEl = $state();
  // open/closed per group, remembered per user: {"cat:media": false, "mod:manage": true}
  const st = $derived(lab.prefs['rail.state'] || {});
  const filtering = $derived(!!q.trim());
  const groups = $derived(filterNav(lab.nav.groups, q));
  const menu = $derived(lab.drawer === 'menu');
  const up = $derived(Object.values(lab.registry?.health || {}));
  const upCount = $derived(up.filter((h) => h.up).length);
  // per module: worst alert + count, and backend health → one small mark next to its name
  const marks = $derived.by(() => {
    const out = {};
    for (const a of lab.alerts) {
      const m = (out[a.module] ||= { n: 0, s: 'unknown' });
      m.n++; m.s = worst(m.s, a.status);
    }
    for (const m of lab.active) {
      if (lab.registry?.health?.[m.id]?.up === false) out[m.id] = { ...(out[m.id] || { n: 0 }), s: 'bad', down: true };
      else if (lab.errors[m.id]) out[m.id] = { ...(out[m.id] || { n: 0 }), s: worst(out[m.id]?.s, 'warn'), err: lab.errors[m.id] };
    }
    return out;
  });
  const GL = { bad: '■', warn: '▲' };
  const isOpen = (key, dflt, active = false) => filtering || active || (st[key] ?? dflt);
  const toggle = (key, cur) => lab.savePref('rail.state', { ...st, [key]: !cur });

  function pick(id) {
    lab.go(id);
    if (menu) lab.drawer = null;
  }
  // ↑/↓ walk every visible row (headers included), ←/→ fold a header, Home/End jump; from the grep box ↓ enters the list
  function keys(e) {
    const items = [...(navEl?.querySelectorAll('[data-nav]') || [])];
    const i = items.indexOf(document.activeElement);
    const go = (n) => { e.preventDefault(); items[Math.max(0, Math.min(items.length - 1, n))]?.focus(); };
    if (e.key === 'ArrowDown') go(i + 1);
    else if (e.key === 'ArrowUp') { if (i <= 0) { e.preventDefault(); navEl.querySelector('.grep input')?.focus(); } else go(i - 1); }
    else if (e.key === 'Home' && i >= 0) go(0);
    else if (e.key === 'End' && i >= 0) go(items.length - 1);
    else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && i >= 0 && items[i].hasAttribute('aria-expanded')) {
      const open = items[i].getAttribute('aria-expanded') === 'true';
      if (open === (e.key === 'ArrowLeft')) { e.preventDefault(); items[i].click(); }
    }
  }
  function grepKey(e) {
    if (e.key === 'Escape' && q) { e.stopPropagation(); q = ''; }
    else if (e.key === 'Enter') { const first = groups[0]?.modules[0]?.entries[0]; if (first) { pick(first.id); q = ''; } }
  }
</script>

{#if menu}<div class="shade" role="presentation" onclick={() => (lab.drawer = null)}></div>{/if}
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<nav class="rail" class:open={menu} aria-label="Main" bind:this={navEl} onkeydown={keys}>
  <div class="brand">
    <div class="bl"><span class="mono word">{lab.brand}</span><span class="mono word sig">/</span><span class="cursor"></span>
      <button class="btn x" aria-label="Close menu" onclick={() => (lab.drawer = null)}><Icon name="close" size={12} /></button></div>
    <span class="mono who">{lab.me.username}@{lab.brand}:~$</span>
    <span class="mono badge">{lab.role}</span>
  </div>

  <label class="grep"><span class="mono sig">$</span>
    <input class="mono" placeholder="grep menu…" bind:value={q} onkeydown={grepKey} aria-label="Filter the menu" spellcheck="false" />
    {#if q}<button class="clr" aria-label="Clear filter" onclick={() => (q = '')}>×</button>{/if}
  </label>

  {#if !filtering}
    {#each lab.nav.top as e (e.id)}
      <button data-nav class="item" aria-current={lab.view === e.id ? 'page' : undefined} onclick={() => pick(e.id)}>
        <Icon name={e.icon} /><span class="lbl">{e.label}</span>
        {#if e.id === 'overview' && lab.alerts.length}<span class="mono cnt {worst(...lab.alerts.map((a) => a.status))}" title="{lab.alerts.length} open alerts">{lab.alerts.length}</span>{/if}
      </button>
    {/each}
  {/if}

  {#each groups as g (g.key)}
    {@const gk = `cat:${g.key}`}
    {@const gOpen = isOpen(gk, true)}
    {@const gMark = worst(...g.modules.map((m) => marks[m.id]?.s))}
    <button data-nav class="cat" aria-expanded={gOpen} onclick={() => !filtering && toggle(gk, gOpen)}>
      <span class="mono chev">{gOpen ? '▾' : '▸'}</span><span class="mono">~/{g.label}</span>
      {#if !gOpen}
        <span class="mono faint n">{g.modules.length}</span>
        {#if GL[gMark]}<span class="mk {gMark}">{GL[gMark]}</span>{/if}
      {/if}
    </button>
    {#if gOpen}
      {#each g.modules as m (m.id)}
        {@const mk = marks[m.id]}
        {@const tip = mk?.down ? `${m.name}: backend down` : mk?.err ? `${m.name}: ${mk.err}` : mk?.n ? `${m.name}: ${mk.n} alerts` : m.name}
        {#if m.single}
          {@const e = m.entries[0]}
          <button data-nav class="item mod" aria-current={lab.view === e.id ? 'page' : undefined} onclick={() => pick(e.id)} title={tip}>
            <Icon name={e.icon} size={15} /><span class="lbl">{e.label}{#if e.hint}<span class="mono faint hint">{e.hint}</span>{/if}</span>
            {#if GL[mk?.s]}<span class="mono mk {mk.s}">{mk.n || ''}{GL[mk.s]}</span>{/if}
          </button>
        {:else}
          {@const active = m.entries.some((e) => e.id === lab.view)}
          {@const mOpen = isOpen(`mod:${m.id}`, false, active)}
          <button data-nav class="item mod" class:hasact={active && !mOpen} aria-expanded={mOpen} onclick={() => toggle(`mod:${m.id}`, mOpen)} title={tip}>
            <Icon name={m.icon} size={15} /><span class="lbl">{m.name}</span>
            {#if GL[mk?.s]}<span class="mono mk {mk.s}">{mk.n || ''}{GL[mk.s]}</span>{/if}
            <span class="mono faint chev2">{mOpen ? '▾' : `${m.entries.length}▸`}</span>
          </button>
          {#if mOpen}
            {#each m.entries as e (e.id)}
              <button data-nav class="item sub" aria-current={lab.view === e.id ? 'page' : undefined} onclick={() => pick(e.id)}>
                <span class="lbl">{e.label}</span>
              </button>
            {/each}
          {/if}
        {/if}
      {/each}
    {/if}
  {:else}
    {#if filtering}<p class="mono dim none">no match for “{q}”</p>{/if}
  {/each}

  {#if !filtering}
    <div class="sep"></div>
    {#each lab.nav.bottom as e (e.id)}
      <button data-nav class="item" aria-current={lab.view === e.id ? 'page' : undefined} onclick={() => pick(e.id)}>
        <Icon name={e.icon} /><span class="lbl">{e.label}</span>
      </button>
    {/each}
  {/if}

  <div class="grow-space"></div>
  <div class="mono foot">
    {#if up.length}backends {upCount}/{up.length} up<br>{/if}
    {lab.objects.size} objects · {lab.active.length} modules
  </div>
  <div class="tools">
    <div class="seg" role="group" aria-label="Theme">
      {#each [['auto', 'auto'], ['dark', 'moon'], ['light', 'sun']] as [t, ic]}
        <button aria-pressed={lab.theme === t} aria-label="{t} theme" onclick={() => lab.setTheme(t)}><Icon name={ic} size={13} /></button>
      {/each}
    </div>
    <button class="btn" aria-label="Log out" title="log out" onclick={() => lab.logout()}><Icon name="logout" size={13} /></button>
  </div>
</nav>

<style>
  .rail { flex: 0 0 220px; width: 220px; border-right: 1px solid var(--line); background: var(--panel); display: flex; flex-direction: column;
    padding: 14px 8px 12px; gap: 1px; height: 100vh; position: sticky; top: 0; overflow-y: auto; overscroll-behavior: contain; }
  .brand { display: flex; flex-direction: column; gap: 4px; padding: 2px 10px 12px; }
  .bl { display: flex; align-items: center; }
  .bl .x { display: none; margin-left: auto; padding: 5px; }
  .word { font-size: 22px; font-weight: 600; letter-spacing: -.02em; }
  .who { font-size: 11px; color: var(--dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .badge { align-self: flex-start; font-size: 10px; letter-spacing: .06em; text-transform: uppercase; padding: 1px 6px; border-radius: 3px;
    border: 1px solid var(--sig); color: var(--sig); white-space: nowrap; }
  .grep { display: flex; align-items: center; gap: 6px; margin: 0 4px 8px; padding: 4px 8px; border: 1px solid var(--line); border-radius: 4px;
    background: var(--bg); font-size: 12px; }
  .grep:focus-within { border-color: var(--sig); }
  .grep input { flex: 1; min-width: 0; border: none; background: transparent; outline: none; font-size: 12px; padding: 1px 0; }
  .clr { border: none; background: none; color: var(--dim); padding: 0 2px; }
  .item { display: flex; align-items: center; gap: 9px; padding: 5px 10px; border-radius: 4px; border: none; background: transparent;
    color: var(--dim); font-size: 13.5px; text-align: left; min-height: 28px; }
  .item:hover, .item:focus-visible { background: var(--raise); color: var(--ink); }
  .item[aria-current] { background: var(--raise); color: var(--ink); box-shadow: inset 2px 0 0 var(--sig); }
  .item.hasact { color: var(--ink); box-shadow: inset 2px 0 0 var(--faint); }
  .lbl { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hint { font-size: 10.5px; margin-left: 6px; }
  .mod { font-size: 13px; padding-left: 14px; }
  .sub { font-size: 12.5px; padding: 4px 10px 4px 38px; min-height: 25px; }
  .cnt { font-size: 11.5px; }
  .cat { display: flex; align-items: center; gap: 7px; padding: 10px 10px 3px; border: none; background: transparent; color: var(--dim);
    font-size: 11px; letter-spacing: .02em; text-align: left; }
  .cat:hover, .cat:focus-visible { color: var(--ink); }
  .chev { width: 8px; font-size: 9.5px; }
  .chev2 { font-size: 9.5px; }
  .n { margin-left: auto; font-size: 10.5px; }
  .mk { font-size: 10px; white-space: nowrap; }
  .mk.ok, .mk.unknown { display: none; }
  .sep { height: 1px; background: var(--line); margin: 10px 6px 6px; flex: none; }
  .none { font-size: 11.5px; padding: 6px 10px; }
  .grow-space { flex: 1; min-height: 8px; }
  .foot { padding: 10px 10px 0; font-size: 10.5px; color: var(--dim); line-height: 1.6; }
  .tools { display: flex; gap: 6px; padding: 10px 6px 0; border-top: 1px solid var(--line); margin-top: 10px; justify-content: space-between; }
  .shade { display: none; }
  @media (max-width: 860px) {
    /* phone: the rail is the ☰ drawer (the burger lives in the top bar) */
    .rail { display: none; }
    .rail.open { display: flex; position: fixed; z-index: 46; left: 0; top: 0; bottom: 0; height: auto; width: min(320px, 88vw);
      box-shadow: 20px 0 50px rgba(0, 0, 0, .3); }
    .bl .x { display: inline-flex; }
    .shade { display: block; position: fixed; inset: 0; background: var(--shade); z-index: 45; }
    .item { min-height: 36px; }
    .sub { min-height: 32px; }
  }
</style>
