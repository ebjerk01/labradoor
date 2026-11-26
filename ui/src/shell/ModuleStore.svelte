<script>
  // Settings → ~/catalogs (owner only): modules from signed catalogs (docs/catalog.md). Trusted publishers (added as root
  // on the host: lab-admin publisher add FILE), catalog URLs, the modules they offer, an install dialog that shows what a
  // module asks for BEFORE it is installed, and per installed module: update, roll back, remove (with or without its
  // config). The gateway asks a root helper for every step; it verifies signatures, sha256 and the MANIFEST, and the
  // svelte ABI of the package's UI. Every step is audited.
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';

  let { onchanged } = $props();
  let info = $state(null);
  let err = $state('');
  let busy = $state('');
  let draft = $state('');
  let addErr = $state(null);
  let results = $state(null);       // check: [{url, ok, catalog, modules, error}]
  let dialog = $state(null);        // {staged, catalog} — the install / update dialog
  let removing = $state(null);      // {id, keep}

  async function load() {
    try { info = await api.get('/api/modules/store'); err = ''; } catch (e) { err = e.message; }
  }
  $effect(() => { if (lab.role === 'owner') load(); });

  const st = $derived(info?.helper || null);
  const installed = $derived(st?.installed || []);
  const pubs = $derived(st?.publishers || []);
  const fp = (p) => (p ? `${p.name} · ${p.fingerprint}` : '');
  const when = (t) => (t ? new Date(t * 1000).toLocaleString() : '');
  // the newest installable version per module across the checked catalogs (an update for installed ones)
  const offers = $derived.by(() => {
    const out = new Map();
    for (const r of results || []) {
      if (!r.ok) continue;
      for (const m of r.modules) {
        const have = out.get(m.id);
        if (!have || (m.available && !have.available)) out.set(m.id, { ...m, catalog: r.catalog });
      }
    }
    return [...out.values()].sort((a, b) => (a.category + a.id).localeCompare(b.category + b.id));
  });
  const updateFor = (id) => offers.find((o) => o.id === id && o.action === 'update');

  async function addCatalog() {
    busy = 'add'; addErr = null;
    try {
      const r = await api.post('/api/modules/catalogs', { url: draft.trim() });
      info.catalogs = r.catalogs; draft = '';
      results = [...(results || []).filter((x) => x.url !== r.check.catalog.url), { url: r.check.catalog.url, ok: true, ...r.check }];
      lab.notify(`catalog added: ${r.check.catalog.name || r.check.catalog.url} ✓`);
      await load();
    } catch (e) { addErr = { error: e.message, signer: e.body?.signer }; } finally { busy = ''; }
  }
  async function removeCatalog(url) {
    if (!confirm(`Remove the catalog ${url}? Installed modules stay installed.`)) return;
    try { const r = await api.post('/api/modules/catalogs', { url, remove: true }); info.catalogs = r.catalogs; results = (results || []).filter((x) => x.url !== url); }
    catch (e) { lab.notify(e.message, 'bad'); }
  }
  async function check() {
    busy = 'check';
    try { results = (await api.post('/api/modules/check')).results; await load(); }
    catch (e) { lab.notify(e.message, 'bad'); } finally { busy = ''; }
  }
  async function stage(m, version) {
    busy = `stage:${m.id}`;
    try {
      const r = await api.post('/api/modules/stage', { id: m.id, version, catalog: m.catalog?.url });
      dialog = { staged: r.staged };
    } catch (e) { lab.notify(`${m.id}: ${e.message}`, 'bad'); } finally { busy = ''; }
  }
  async function confirmInstall() {
    const s = dialog.staged;
    busy = 'install';
    try {
      const r = await api.post(`/api/modules/${s.action}`, { id: s.id, version: s.version });
      lab.notify(`${s.id} ${r.version} ${s.action === 'update' ? `(was ${r.previous})` : 'installed'} ✓`);
      dialog = null;
      await after();
    } catch (e) { lab.notify(`${s.id}: ${e.message}`, 'bad'); } finally { busy = ''; }
  }
  async function rollback(m) {
    if (!confirm(`Roll ${m.id} back from ${m.version} to ${m.previous}?`)) return;
    busy = `rb:${m.id}`;
    try { const r = await api.post('/api/modules/rollback', { id: m.id }); lab.notify(`${m.id}: back to ${r.version} ✓`); await after(); }
    catch (e) { lab.notify(`${m.id}: ${e.message}`, 'bad'); } finally { busy = ''; }
  }
  async function remove() {
    const { id, keep } = removing;
    busy = `rm:${id}`;
    try {
      const r = await api.post('/api/modules/remove', { id, keep_config: keep });
      lab.notify(`${id} removed${keep ? ' (its config is kept)' : ''}${r.bundled_remains ? ` — the bundled ${r.bundled_remains} is back` : ''} ✓`);
      removing = null;
      await after();
    } catch (e) { lab.notify(`${id}: ${e.message}`, 'bad'); } finally { busy = ''; }
  }
  async function after() {
    await load();
    if (results) { try { results = (await api.post('/api/modules/check')).results; } catch { /* the list stays */ } }
    await lab.loadRegistry();
    lab.refresh();
    onchanged?.();
  }
</script>

{#if lab.role === 'owner'}
  <section>
    <div class="sh">
      <span class="cap">~/catalogs</span>
      <span class="mono dim">owner only · modules from signed catalogs; only publishers the host's root trusts</span>
    </div>
    {#if info}
      <div class="grid">
        <span class="k">publishers</span>
        <div class="col">
          {#each pubs as p (p.name)}
            <div class="mono small">{p.name}{#if p.core} <span class="tag">core</span>{/if} <span class="dim">{p.fingerprints.join(' · ')}</span></div>
          {:else}
            <div class="mono small warn">▲ none trusted yet</div>
          {/each}
          {#each st?.publisher_problems || [] as p}<div class="mono small warn">▲ {p}</div>{/each}
          <div class="mono small dim">add one as root on the host: <code>lab-admin publisher add FILE.pub</code> (never from here: a publisher's code runs in your browser with your rights)</div>
        </div>
        {#if info.helperError}<span class="k">helper</span><span class="mono small bad">■ {info.helperError}</span>{/if}

        <span class="k">catalogs</span>
        <div class="col">
          {#each info.catalogs as c (c.url)}
            {@const chk = (st?.catalogs || []).find((x) => x.url === c.url)}
            <div class="cat">
              <span class="mono small url">{c.url}</span>
              <span class="mono small dim">{c.name || ''}{#if chk?.publisher} · {fp(chk.publisher)}{:else if c.publisher} · {fp(c.publisher)}{/if}{#if chk?.checked} · checked {when(chk.checked)}{/if}</span>
              {#if chk?.error}<span class="mono small bad">■ {chk.error}</span>{/if}
              <button class="btn small" onclick={() => removeCatalog(c.url)} aria-label="Remove catalog {c.url}">remove</button>
            </div>
          {:else}
            <div class="mono small dim">no catalogs yet</div>
          {/each}
          <div class="row">
            <input class="field mono" placeholder="https://… /catalog.json" spellcheck="false" bind:value={draft} aria-label="Catalog URL"
              onkeydown={(e) => { if (e.key === 'Enter' && draft.trim()) addCatalog(); }} />
            <button class="btn" disabled={!draft.trim() || !!busy} onclick={addCatalog}>{busy === 'add' ? 'checking…' : 'add'}</button>
            <button class="btn" disabled={!info.catalogs.length || !!busy} onclick={check}>{busy === 'check' ? 'checking…' : 'check catalogs'}</button>
          </div>
          {#if addErr}
            <div class="mono small bad">■ {addErr.error}</div>
            {#if addErr.signer}<div class="mono small dim">signed by {addErr.signer} — compare it with what the publisher says, then as root: <code>lab-admin publisher add FILE.pub</code></div>{/if}
          {/if}
          {#each (results || []).filter((r) => !r.ok) as r (r.url)}<div class="mono small bad">■ {r.url}: {r.error}</div>{/each}
        </div>
      </div>

      {#if installed.length}
        <div class="sub mono">installed from catalogs</div>
        {#each installed as m (m.id)}
          {@const up = updateFor(m.id)}
          <div class="item">
            <span class="ok">●</span>
            <span class="mono id">{m.id}</span>
            <span class="mono small">{m.version}</span>
            <span class="mono small dim grow">{m.publisher?.name}{m.connector ? ' · connector' : ''}{m.kind === 'private' ? ' · private' : ''} · {when(m.updated)}</span>
            {#if info.shadowed?.[m.id]}<span class="mono small warn">▲ {info.shadowed[m.id]}</span>{/if}
            {#if up}<button class="btn small primary" disabled={!!busy} onclick={() => stage(up, up.available)}>{busy === `stage:${m.id}` ? 'checking…' : `update to ${up.available}`}</button>{/if}
            {#if m.previous}<button class="btn small" disabled={!!busy} onclick={() => rollback(m)}>{busy === `rb:${m.id}` ? 'rolling back…' : `roll back to ${m.previous}`}</button>{/if}
            <button class="btn small" disabled={!!busy} onclick={() => (removing = { id: m.id, keep: true })}>remove</button>
          </div>
          {#if removing?.id === m.id}
            <div class="panel">
              <p class="small">Remove <b class="mono">{m.id} {m.version}</b>? Its views disappear for everyone.</p>
              <label class="small chk"><input type="checkbox" bind:checked={removing.keep} /> keep its connection and settings (a reinstall picks them up again)</label>
              <div class="row">
                <button class="btn primary" disabled={!!busy} onclick={remove}>{busy === `rm:${m.id}` ? 'removing…' : removing.keep ? 'remove, keep config' : 'remove with its config'}</button>
                <button class="btn" onclick={() => (removing = null)}>cancel</button>
              </div>
            </div>
          {/if}
        {/each}
      {/if}

      {#if results}
        <div class="sub mono">available · {offers.length}</div>
        {#each offers as m (m.id)}
          <div class="item">
            <span class={m.action === 'install' ? 'sig' : m.installed ? 'ok' : 'off'}>{m.installed ? '●' : '○'}</span>
            <span class="mono id">{m.id}</span>
            <span class="nm">{m.name}</span>
            <span class="mono small dim">{m.category}{m.kind === 'private' ? ' · private' : ''}</span>
            <span class="mono small dim grow">{m.installed ? `installed ${m.installed}` : m.bundled ? `bundled ${m.bundled}` : ''}{m.available ? ` · ${m.available}` : ''}{!m.available && m.versions[0]?.why !== 'installed' ? ` · ${m.versions[0]?.why || 'nothing installable'}` : ''}</span>
            {#if m.action === 'install'}<button class="btn small primary" disabled={!!busy} onclick={() => stage(m, m.available)}>{busy === `stage:${m.id}` ? 'checking…' : `install ${m.available}`}</button>{/if}
            {#if m.action === 'update'}<button class="btn small primary" disabled={!!busy} onclick={() => stage(m, m.available)}>{busy === `stage:${m.id}` ? 'checking…' : `update to ${m.available}`}</button>{/if}
          </div>
          {#if m.description}<p class="desc dim small">{m.description}</p>{/if}
        {/each}
      {/if}

      {#if dialog}
        {@const s = dialog.staged}
        {@const p = s.permissions}
        <div class="panel dlg" role="dialog" aria-label="{s.action} {s.id}">
          <div class="mono"><b>{s.action === 'update' ? `update ${s.id} ${s.installed} → ${s.version}` : `install ${s.id} ${s.version}`}</b> · {s.name}</div>
          <p class="small dim">{s.description}</p>
          <div class="grid2">
            <span class="k">publisher</span><span class="mono small">{fp(s.publisher)}</span>
            <span class="k">kind</span><span class="mono small">{s.kind} · {s.category}{s.min_core ? ` · needs core ${s.min_core}+` : ''}{s.replaces_bundled ? ` · replaces the bundled ${s.replaces_bundled}` : ''}</span>
            <span class="k">package</span><span class="mono small dim">sha256 {s.sha256.slice(0, 16)}… · signature, MANIFEST and svelte ABI verified</span>
            <span class="k">who may use it</span><span class="mono small">{p.access.roles.join(' + ')}{p.access.groups.length ? ` · guests in ${p.access.groups.join(', ')}` : ''}{p.guest_safe ? ' · filters per user' : ''}</span>
            <span class="k">talks to</span>
            <span class="mono small">
              {#if p.connector}a connector on this host (127.0.0.1:{p.connector.port}, its own unix user){/if}
              {#if p.backend && !p.connector}{p.backend.own ? 'your own backend, signed per user' : `an API with one shared ${p.backend.auth || ''} credential`} ({p.backend.url}){/if}
              {#if !p.backend}nothing (it only combines other modules){/if}
              {#each p.network as t}<div class="dim">→ {t.label}{t.example ? ` (e.g. ${t.example})` : ''}</div>{/each}
            </span>
            {#if p.secrets.length}<span class="k">secrets it stores</span><span class="mono small">{p.secrets.join(', ')} (sealed, never sent to a browser{p.connector ? '; handed to its connector' : ''})</span>{/if}
            <span class="k">reads other modules</span><span class="mono small">{p.requires.length ? p.requires.map((r) => r.id + (r.optional ? ' (optional)' : '')).join(', ') : 'none'}</span>
            {#if p.uses_credentials_of.length}<span class="k">uses credentials of</span><span class="mono small warn">▲ {p.uses_credentials_of.join(', ')} — its connector gets their third-party API credentials and calls their own backends as the person using it</span>{/if}
            {#if p.delegate}<span class="k">delegate</span><span class="mono small warn">▲ its connector may read every module as the person using it</span>{/if}
            <span class="k">routes</span><span class="mono small">{p.routes.length} ({p.writes} change something, {p.owner_only} owner-only)</span>
          </div>
          <details>
            <summary class="mono small">every route it may call</summary>
            <table class="mono small">
              <tbody>
                {#each p.routes as r}
                  <tr class:w={r.write}><td>{r.method}</td><td class="path">{r.path}</td><td class={r.owner_only ? 'warn' : 'dim'}>{r.who === 'guest' ? 'everyone with the module' : r.who}{r.secret ? ' · secret' : ''}</td><td class="dim">{r.label}</td></tr>
                {/each}
              </tbody>
            </table>
          </details>
          {#if p.delegate || p.uses_credentials_of.length}
            <p class="small warn priv">▲ PRIVILEGED module: it asks for {[p.delegate ? 'delegate' : '', p.uses_credentials_of.length ? 'other modules\' credentials' : ''].filter(Boolean).join(' and ')}. Allowed here because {s.privileged?.allowed_because || 'root allowed this publisher'} (root decides: <span class="mono">lab-admin publisher allow-privileged / revoke-privileged</span>).</p>
          {/if}
          <p class="small warn">▲ Its screens run in your browser with your rights. Install only what you trust from this publisher.</p>
          <div class="row">
            <button class="btn primary" disabled={!!busy} onclick={confirmInstall}>{busy === 'install' ? 'installing…' : s.action === 'update' ? `update to ${s.version}` : `install ${s.version}`}</button>
            <button class="btn" disabled={!!busy} onclick={() => (dialog = null)}>cancel</button>
          </div>
        </div>
      {/if}
    {:else if err}
      <p class="mono bad pad">{err}</p>
    {/if}
  </section>
{/if}

<style>
  section { border-bottom: 1px solid var(--line); padding-bottom: 8px; }
  .sh { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; padding: 14px 20px 6px; font-size: 11.5px; }
  .sub { padding: 12px 20px 4px; font-size: 12px; color: var(--ink); }
  .grid { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 8px 16px; align-items: start; padding: 6px 20px 10px; max-width: 980px; }
  .grid2 { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 6px 14px; align-items: start; margin: 8px 0; }
  .k { font: 12px "Geist Mono Variable", monospace; color: var(--dim); }
  .col { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .row .field { flex: 1 1 260px; max-width: 520px; padding: 6px 8px; font-size: 12px; }
  .cat { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .url, .col div, .grid2 > span, .item .grow { overflow-wrap: anywhere; }
  .small { font-size: 11.5px; }
  .tag { font-size: 10.5px; padding: 0 5px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .item { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; padding: 6px 20px; border-top: 1px solid var(--q); }
  .item > span:first-child { font-size: 9px; }
  .id { font-size: 12.5px; min-width: 90px; }
  .nm { font-size: 13px; }
  .grow { flex: 1 1 160px; min-width: 0; }
  .desc { margin: 0; padding: 0 20px 6px 46px; }
  .btn.small { padding: 3px 9px; font-size: 11.5px; }
  .panel { margin: 4px 20px 10px; padding: 10px 14px; border: 1px solid var(--line); border-left: 2px solid var(--sig); background: var(--panel); max-width: 940px; }
  .panel p { margin: 4px 0 8px; }
  .priv { border: 1px solid var(--warn); padding: 6px 8px; font-weight: 600; }
  .chk { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; }
  details { margin: 6px 0; }
  table { border-collapse: collapse; width: 100%; margin-top: 6px; }
  td { padding: 2px 8px 2px 0; vertical-align: top; }
  td.path { overflow-wrap: anywhere; }
  tr.w td:first-child { color: var(--sig); }
  .pad { padding: 4px 20px; }
  code { font-size: 11px; }
  @media (max-width: 700px) {
    .grid, .grid2 { grid-template-columns: 1fr; gap: 4px 0; }
    .grid { padding: 6px 16px 10px; }
    .sh, .sub, .item { padding-left: 16px; padding-right: 16px; }
    .panel { margin: 4px 16px 10px; }
    .desc { padding-left: 16px; }
    td:last-child { display: none; }
  }
</style>
