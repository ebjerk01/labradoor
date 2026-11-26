<script>
  // Plugins: installed (enable / disable / uninstall / update), the catalog of the configured repositories (install), and
  // the repositories themselves (owner only: a repository is where server code comes from). Changes need a restart.
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { lazy, qs } from '$lab/sdk.js';
  import { write } from './store.svelte.js';
  let { data, ctx } = $props();

  const ST = { Active: 'ok', Restart: 'warn', Disabled: 'off', Superseded: 'off', Deleted: 'off', Malfunctioned: 'bad', NotSupported: 'bad' };
  let tab = $state('installed');
  let q = $state('');
  const plugins = lazy(() => ctx, () => '/Plugins');
  const catalog = lazy(() => ctx, () => '/Packages');
  const repos = lazy(() => ctx, () => (tab === 'repos' ? '/Repositories' : null));
  const canToggle = $derived(ctx.can('POST', '/Plugins/x/1/Enable') !== 'no');
  const canInstall = $derived(ctx.can('POST', '/Packages/Installed/x') !== 'no');
  const canRemove = $derived(ctx.can('DELETE', '/Plugins/x/1') !== 'no');
  const repoVerdict = $derived(ctx.can('POST', '/Repositories'));

  const ver = (v) => String(v || '0').split('.').map((x) => parseInt(x, 10) || 0);
  const cmp = (a, b) => { const x = ver(a), y = ver(b); for (let i = 0; i < Math.max(x.length, y.length); i++) { const d = (x[i] || 0) - (y[i] || 0); if (d) return d; } return 0; };
  const server = $derived(data.version || '0');
  // newest version this server can run (targetAbi ≤ server version)
  const best = (p) => (p.versions || []).filter((v) => cmp(v.targetAbi, server) <= 0).sort((a, b) => cmp(b.version, a.version))[0] || null;
  const byGuid = $derived(new Map((catalog.data || []).map((p) => [String(p.guid).replace(/-/g, ''), p])));
  const installed = $derived((plugins.data || []).slice().sort((a, b) => a.Name.localeCompare(b.Name)));
  const updateFor = (p) => { const c = byGuid.get(String(p.Id).replace(/-/g, '')); const b = c && best(c); return b && cmp(b.version, p.Version) > 0 ? { pkg: c, v: b } : null; };
  const has = (guid) => installed.some((p) => String(p.Id).replace(/-/g, '') === String(guid).replace(/-/g, ''));
  const shown = $derived((catalog.data || []).filter((p) => !q || `${p.name} ${p.category} ${p.overview}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name)));

  const after = () => { plugins.reload(); };
  const toggle = async (p) => { if (await write(ctx, ['plugins', 'info'], { path: `/Plugins/${p.Id}/${p.Version}/${p.Status === 'Disabled' ? 'Enable' : 'Disable'}`, label: `jellyfin: ${p.Status === 'Disabled' ? 'enable' : 'disable'} plugin ${p.Name}`, confirm: p.Status === 'Disabled' ? null : `Disable the plugin ${p.Name}? Takes effect after a restart.` })) after(); };
  const remove = async (p) => { if (await write(ctx, ['plugins', 'info'], { method: 'DELETE', path: `/Plugins/${p.Id}/${p.Version}`, label: `jellyfin: uninstall plugin ${p.Name}`, confirm: `Uninstall the plugin ${p.Name} ${p.Version}? Takes effect after a restart.` })) after(); };
  const install = async (pkg, v, verb = 'install') => { if (await write(ctx, ['plugins', 'info'], { path: `/Packages/Installed/${encodeURIComponent(pkg.name)}?${qs({ assemblyGuid: pkg.guid, version: v.version })}`, label: `jellyfin: ${verb} plugin ${pkg.name} ${v.version}`, confirm: `${verb === 'update' ? 'Update' : 'Install'} the plugin “${pkg.name}” ${v.version} from ${v.repositoryName}?\n\nPlugins run inside Jellyfin with full access. Needs a restart.` })) setTimeout(after, 3000); };

  let nr = $state({ Name: '', Url: '' });
  async function saveRepos(list) {
    if (await write(ctx, [], { path: '/Repositories', body: list.map((r) => ({ Name: r.Name, Url: r.Url, Enabled: r.Enabled !== false })), label: 'jellyfin: plugin repositories' })) {
      repos.reload();
      catalog.reload();
      nr = { Name: '', Url: '' };
    }
  }
</script>

<div class="bar">
  <div class="seg" role="group" aria-label="plugin tabs">
    <button aria-pressed={tab === 'installed'} onclick={() => (tab = 'installed')}>installed · {installed.length}</button>
    <button aria-pressed={tab === 'catalog'} onclick={() => (tab = 'catalog')}>catalog · {catalog.data?.length ?? '…'}</button>
    <button aria-pressed={tab === 'repos'} onclick={() => (tab = 'repos')}>repositories</button>
  </div>
  {#if tab === 'catalog'}<input class="field q" placeholder="filter" bind:value={q} aria-label="Filter plugins" />{/if}
  {#if data.restart}<span class="mono warn s">▲ restart pending</span>{/if}
</div>
{#if plugins.error || catalog.error}<p class="mono bad s">{plugins.error || catalog.error}</p>{/if}

{#if tab === 'installed'}
  {#each installed as p (p.Id + p.Version)}
    {@const up = updateFor(p)}
    <div class="p">
      <Glyph status={ST[p.Status] || 'unknown'} size={10} />
      <div class="m"><span>{p.Name} <span class="mono dim s">{p.Version}</span></span><span class="dim s ell">{p.Description}</span></div>
      <span class="mono s" class:warn={p.Status !== 'Active'} class:dim={p.Status === 'Active'}>{p.Status.toLowerCase()}{p.CanUninstall ? '' : ' · bundled'}</span>
      <span class="acts">
        {#if up && canInstall}<button class="btn x" onclick={() => install(up.pkg, up.v, 'update')}><Icon name="download" size={11} />{up.v.version}</button>{/if}
        {#if canToggle && ['Active', 'Disabled', 'Malfunctioned', 'NotSupported'].includes(p.Status)}<button class="btn x" onclick={() => toggle(p)}>{p.Status === 'Disabled' ? 'enable' : 'disable'}</button>{/if}
        {#if canRemove && p.CanUninstall}<button class="btn x danger" aria-label="uninstall {p.Name}" onclick={() => remove(p)}><Icon name="close" size={11} /></button>{/if}
      </span>
    </div>
  {/each}
{:else if tab === 'catalog'}
  {#each shown as pkg (pkg.guid)}
    {@const b = best(pkg)}
    {@const inst = has(pkg.guid)}
    <div class="p">
      <Glyph status={inst ? 'ok' : 'off'} size={10} />
      <div class="m"><span>{pkg.name} <span class="mono dim s">{pkg.category.toLowerCase()} · {pkg.owner}</span></span><span class="dim s ell">{pkg.overview || pkg.description}</span></div>
      <span class="mono dim s">{b ? b.version : 'none for ' + server}</span>
      <span class="acts">
        {#if inst}<span class="mono ok s">● installed</span>
        {:else if b && canInstall}<button class="btn x" onclick={() => install(pkg, b)}><Icon name="download" size={11} />install</button>{/if}
      </span>
    </div>
  {:else}<span class="mono dim s">{catalog.loading ? 'loading catalog' : 'nothing'}</span>{/each}
{:else}
  {#if repos.error}<p class="mono dim s">{repos.error}</p>{/if}
  {#each repos.data || [] as r, i (r.Url)}
    <div class="p">
      <Glyph status={r.Enabled ? 'ok' : 'off'} size={10} />
      <div class="m"><span>{r.Name}</span><span class="mono dim s ell">{r.Url}</span></div>
      <span class="s"></span>
      <span class="acts">
        {#if repoVerdict !== 'no'}
          <button class="btn x" onclick={() => saveRepos(repos.data.map((x, j) => (j === i ? { ...x, Enabled: !x.Enabled } : x)))}>{#if repoVerdict === 'ask'}<Icon name="lock" size={10} />{/if}{r.Enabled ? 'disable' : 'enable'}</button>
          <button class="btn x danger" aria-label="remove {r.Name}" onclick={() => confirm(`Remove the repository ${r.Name}?`) && saveRepos(repos.data.filter((_, j) => j !== i))}><Icon name={repoVerdict === 'ask' ? 'lock' : 'close'} size={11} /></button>
        {/if}
      </span>
    </div>
  {/each}
  {#if repoVerdict !== 'no' && repos.data}
    <form class="add" onsubmit={(e) => { e.preventDefault(); if (nr.Name.trim() && /^https:\/\//.test(nr.Url.trim())) saveRepos([...repos.data, { Name: nr.Name.trim(), Url: nr.Url.trim(), Enabled: true }]); else ctx.notify('name + an https:// manifest URL', 'bad'); }}>
      <input class="field" placeholder="name" bind:value={nr.Name} aria-label="Repository name" />
      <input class="field grow" placeholder="https://…/manifest.json" bind:value={nr.Url} aria-label="Repository URL" />
      <button class="btn">{repoVerdict === 'ask' ? 'ask owner to add' : 'add'}</button>
    </form>
  {/if}
  <span class="mono dim s">repositories decide which code Jellyfin can install: owner only{repoVerdict === 'ask' ? ' (each change asks owner)' : ''}</span>
{/if}

<style>
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 6px; }
  .q { flex: 1 1 140px; min-width: 0; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font-size: 12px; color: var(--ink); min-width: 0; }
  .p { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto auto; gap: 4px 10px; align-items: center; padding: 5px 0; border-bottom: 1px solid var(--q); font-size: 12.5px; }
  .m { display: flex; flex-direction: column; min-width: 0; }
  .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .s { font-size: 10.5px; }
  .acts { display: flex; gap: 4px; justify-content: flex-end; }
  .x { padding: 3px 7px; }
  .add { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
  .grow { flex: 1 1 200px; }
  .danger:not(:disabled) { color: var(--bad); border-color: var(--bad); }
  .bad { color: var(--bad); }
  .warn { color: var(--warn); }
  .ok { color: var(--ok); }
  @media (max-width: 640px) { .p { grid-template-columns: 14px minmax(0, 1fr) auto; } .p > .s:nth-child(3) { display: none; } }
</style>
