<script>
  // Ctrl-K: views, objects (one row per thing, other sources as badges), module search/lookup rows (capped), commands,
  // and tasks — "restart <x>", "reboot", "console <x>", "snapshot <x>", "new record", "approve" (ranking: palette.js).
  import { lab } from '$lab/lab.svelte.js';
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { itemAction, rankPalette } from '$lab/palette.js';

  let q = $state('');
  let i = $state(0);
  let found = $state([]);
  let timer;
  // module lookups (async, e.g. a plate or a part number): debounced, only for 3+ characters
  $effect(() => {
    const s = q.trim();
    clearTimeout(timer);
    if (s.length < 3) { found = []; return; }
    timer = setTimeout(async () => {
      const res = await Promise.allSettled(lab.active.filter((m) => typeof m.ui.lookup === 'function')
        .map(async (m) => (await m.ui.lookup(s, lab.ctx(m.id)) || []).map((x) => ({ ...x, module: m.id }))));
      if (q.trim() === s) found = res.flatMap((r) => (r.status === 'fulfilled' ? r.value : []));
    }, 250);
  });
  let input = $state();
  $effect(() => { if (lab.palette) { q = ''; i = 0; queueMicrotask(() => input?.focus()); } });

  const catOf = (mid) => lab.active.find((m) => m.id === mid)?.category || '';
  // static rows from every module's search(): only rebuilt when data changes, not per keystroke
  const search = $derived(lab.active.flatMap((m) => {
    if (typeof m.ui.search !== 'function' || lab.data[m.id] == null) return [];
    try { return (m.ui.search(lab.data[m.id], lab.ctx(m.id)) || []).map((x) => ({ ...x, module: m.id })); } catch { return []; }
  }));
  const commands = $derived([
    { label: 'theme: toggle', keys: 'dark light', run: () => lab.setTheme(lab.theme === 'dark' ? 'light' : 'dark') },
    { label: 'refresh now', keys: 'reload sync', run: () => lab.refresh() },
    ...(lab.role !== 'guest' ? [{ label: 'approvals', sub: lab.role === 'owner' ? 'decide requests' : 'your requests',
      keys: 'approve approval deny request ask owner', run: () => { lab.drawer = 'approvals'; lab.loadApprovals(); } }] : []),
    { label: 'log out', keys: 'logout sign out', run: () => lab.logout() },
  ]);
  const views = $derived([...lab.nav.top, ...lab.nav.entries, ...lab.nav.bottom]);
  const items = $derived(lab.palette ? rankPalette({
    q, views, objects: [...lab.objects.values()], search, lookups: found, commands, catOf, actionsFor: (o) => lab.actions(o),
  }) : []);

  function pick(it) {
    lab.palette = false;
    const p = it.pick;
    if (p.view) lab.go(p.view);
    else if (p.object) lab.open(p.object);
    else if (p.action) lab.run(p.action);
    else if (p.item) itemAction(p.item, lab)();
    else if (p.cmd) p.cmd.run();
  }
  function key(e) {
    if (e.key === 'ArrowDown') { i = Math.min(i + 1, items.length - 1); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { i = Math.max(i - 1, 0); e.preventDefault(); }
    else if (e.key === 'Enter' && items[i]) pick(items[i]);
    else if (e.key === 'Escape') lab.palette = false;
  }
  let list = $state();
  $effect(() => { void i; list?.querySelector('.on')?.scrollIntoView({ block: 'nearest' }); });
  const KIND = { view: 'view', cmd: 'cmd', mod: '', obj: '', task: 'run' };
</script>

{#if lab.palette}
  <div class="shade" role="presentation" onclick={() => (lab.palette = false)}></div>
  <div class="pal" role="dialog" aria-label="Jump to or run">
    <div class="in"><span class="mono sig">$</span>
      <input bind:this={input} bind:value={q} onkeydown={key} oninput={() => (i = 0)} spellcheck="false"
        placeholder="name, view — or a task: restart …, console …, new record" aria-label="Search or run" />
    </div>
    <ul bind:this={list}>
      {#each items as it, n (it.key)}
        <li><button class:on={n === i} onmouseenter={() => (i = n)} onclick={() => pick(it)}>
          {#if it.kind === 'task'}<Icon name={it.verdict === 'ask' ? 'lock' : it.pick.action.icon || 'play'} size={13} />
          {:else if it.status}<Glyph status={it.status} />
          {:else}<span class="mono faint k">{KIND[it.kind] || '›'}</span>{/if}
          <span class="l">{it.label}</span>
          {#each it.badges.slice(0, 4) as b}<span class="mono badge">{b.label}</span>{/each}
          {#if it.kind === 'task'}<span class="mono vd" class:ask={it.verdict === 'ask'}>{it.verdict === 'ask' ? 'ask owner' : 'yes'}</span>{/if}
          <span class="mono dim s">{it.sub}</span>
        </button></li>
      {:else}
        <li class="mono dim none">nothing matches “{q}”</li>
      {/each}
    </ul>
    <div class="mono dim hint">↑↓ move · enter open/run · esc close · tasks: restart reboot start stop console snapshot upgrade · new …</div>
  </div>
{/if}

<style>
  .shade { position: fixed; inset: 0; background: var(--shade); z-index: 40; }
  .pal { position: fixed; z-index: 41; top: 12vh; left: 50%; transform: translateX(-50%); width: min(660px, calc(100vw - 16px));
    background: var(--panel); border: 1px solid var(--line); border-radius: 6px; box-shadow: 0 20px 60px rgba(0, 0, 0, .35); overflow: hidden; }
  .in { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--line); }
  input { flex: 1; min-width: 0; border: none; background: transparent; font-size: 15px; outline: none; }
  ul { list-style: none; margin: 0; padding: 6px; max-height: 56vh; overflow-y: auto; }
  li button { width: 100%; display: flex; align-items: center; gap: 8px; padding: 6px 10px; border: none; background: transparent; border-radius: 4px;
    text-align: left; min-width: 0; color: var(--ink); }
  li button.on { background: var(--raise); box-shadow: inset 2px 0 0 var(--sig); }
  .k { font-size: 10px; width: 26px; flex: none; }
  .l { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .badge { font-size: 10px; padding: 0 5px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); flex: none; }
  .vd { font-size: 10.5px; padding: 0 6px; border-radius: 3px; background: var(--sig); color: var(--sigink); flex: none; }
  .vd.ask { background: transparent; color: var(--sig); border: 1px dashed var(--sig); }
  .s { font-size: 11px; flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 40%; }
  .none { padding: 10px; font-size: 12px; }
  .hint { padding: 8px 16px; font-size: 10.5px; border-top: 1px solid var(--line); }
  @media (max-width: 600px) { .pal { top: 8px; } .badge { display: none; } .hint { display: none; } .s { max-width: 30%; } }
</style>
