<script>
  import { lab } from '$lab/lab.svelte.js';
  import Rail from './shell/Rail.svelte';
  import Topbar from './shell/Topbar.svelte';
  import Ticker from './shell/Ticker.svelte';
  import ObjectPanel from './shell/ObjectPanel.svelte';
  import Palette from './shell/Palette.svelte';
  import Approvals from './shell/Approvals.svelte';
  import Login from './shell/Login.svelte';
  import Setup from './shell/Setup.svelte';
  import Enrol from './shell/Enrol.svelte';
  import Overview from './views/Overview.svelte';
  import Wall from './views/Wall.svelte';
  import Map from './views/Map.svelte';
  import Log from './views/Log.svelte';
  import People from './views/People.svelte';
  import Settings from './views/Settings.svelte';
  import ModuleHome from './views/ModuleHome.svelte';

  const setupPage = location.pathname === '/setup';  // first run: /setup#<one-time token>
  if (setupPage) lab.applyTheme(); else lab.boot();

  function onkey(e) {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); lab.palette = !lab.palette; }
    else if (!typing && e.key === '/' && lab.me) { e.preventDefault(); lab.palette = true; }
    else if (e.key === 'Escape') { if (lab.palette) lab.palette = false; else if (lab.drawer) lab.drawer = null; else if (lab.panelOpen && lab.view !== 'map') lab.close(); }
  }
  // the map keeps its panel only while something is selected: an empty "select an object" column took 340px and
  // the map got clipped on both sides
  const showPanel = $derived(lab.view === 'map' ? !!lab.sel && lab.panelOpen : lab.panelOpen && !['log', 'people', 'settings'].includes(lab.view));
</script>

<svelte:window onkeydown={onkey} />

{#if setupPage}
  <Setup />
{:else if !lab.booted}
  <div class="boot mono dim"><span class="spin">booting lab</span></div>
{:else if !lab.me}
  <Login />
{:else if lab.me.mustEnrol}
  <Enrol />
{:else}
  <div class="shell">
    <Rail />
    <main class="main">
      <Topbar />
      <Ticker />
      {#if Object.keys(lab.errors).length}
        <div class="errs mono">{#each Object.entries(lab.errors) as [m, e]}<span><span class="warn">▲</span> {m}: {e}</span>{/each}</div>
      {/if}
      <div class="body">
        <div class="view">
          {#if lab.view === 'overview'}<Overview />
          {:else if lab.view === 'wall'}<Wall />
          {:else if lab.view === 'map'}<div class="scroll-x"><Map /></div>
          {:else if lab.view === 'log'}<Log />
          {:else if lab.view === 'people'}<People />
          {:else if lab.view === 'settings'}<Settings />
          {:else if lab.nav.byId.get(lab.view)?.home}<ModuleHome module={lab.nav.byId.get(lab.view).module} />
          {:else}
            {@const mv = lab.moduleViews.find((v) => v.id === lab.view)}
            {#if mv}{@const C = mv.component}<C data={lab.data[mv.module]} ctx={lab.ctx(mv.module)} {...(mv.props || {})} />
            {:else}<p class="mono dim pad">no such view: {lab.view}</p>{/if}
          {/if}
        </div>
        {#if showPanel}<ObjectPanel />{/if}
      </div>
    </main>
  </div>
  <Palette />
  <Approvals />
  {#if lab.toast}<div class="toast mono" class:bad={lab.toast.kind === 'bad'} role="status">{lab.toast.msg}</div>{/if}
{/if}

<style>
  .boot { min-height: 100vh; display: grid; place-items: center; }
  .boot .spin { display: inline-flex; flex-direction: row-reverse; gap: 8px; }
  .shell { display: flex; flex-wrap: wrap; min-height: 100vh; }
  .main { flex: 999 1 560px; min-width: 0; display: flex; flex-direction: column; }
  .body { flex: 1; display: flex; flex-wrap: wrap; min-height: 0; align-items: stretch; }
  .view { flex: 999 1 560px; min-width: 0; }
  .pad { padding: 20px; }
  .errs { display: flex; flex-wrap: wrap; gap: 16px; padding: 6px 20px; font-size: 11.5px; color: var(--dim); border-bottom: 1px solid var(--line); }
  .toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); background: var(--raise); border: 1px solid var(--sig);
    padding: 8px 14px; border-radius: 4px; font-size: 12px; z-index: 50; box-shadow: 0 10px 30px rgba(0, 0, 0, .3); }
  .toast.bad { border-color: var(--bad); color: var(--bad); }
</style>
