<script>
  // ~/settings — personal preferences for everyone; module switches + access + module settings for the owner
  // (admins see them read-only). Changes save immediately and are audited.
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';
  import Icon from '$lab/Icon.svelte';
  import ModuleConfig from '../shell/ModuleConfig.svelte';
  import AccountSettings from '../shell/AccountSettings.svelte';
  import LoginSettings from '../shell/LoginSettings.svelte';
  import UpdateSettings from '../shell/UpdateSettings.svelte';
  import ModuleStore from '../shell/ModuleStore.svelte';

  let mods = $state([]);
  let editable = $state(false);
  let open = $state(null);
  let q = $state('');
  let groupDraft = $state({});

  async function load() {
    if (lab.role === 'guest') return;
    try { const r = await api.get('/api/settings'); mods = r.modules; editable = r.editable; } catch (e) { lab.notify(e.message, 'bad'); }
  }
  $effect(() => { load(); });

  async function save(m, body, label) {
    try {
      const r = await api.post('/api/settings/module', { module: m.id, ...body });
      m.values = r.values; m.enabled = r.enabled;
      if (body.extraGroups) m.extraGroups = body.extraGroups;
      lab.notify(`${m.id}: ${label} ✓`);
      await lab.loadRegistry();
      lab.refresh();
    } catch (e) { lab.notify(`${m.id}: ${e.message}`, 'bad'); }
  }
  const setVal = (m, key, value, label) => save(m, { values: { [key]: value } }, label || key);
  // what a module may do beyond its own routes (review 2026-11-15 L4 / owner decision #10): shown before it is turned on
  const privileged = (m) => [m.delegate ? 'its connector reads every module as the person using it (delegate)' : '',
    m.usesCredentialsOf?.length ? `its connector uses ${m.usesCredentialsOf.join(', ')}: their third-party API credentials, and their own backends as the person using it` : '']
    .filter(Boolean).join('; ');
  const shown = $derived(mods.filter((m) => !q || `${m.id} ${m.name} ${m.description}`.toLowerCase().includes(q.toLowerCase())));
  // start page: grouped like the rail (core views, then category → module → page), same unique labels
  const homeCore = $derived(lab.nav.top);
  const homeGroups = $derived(lab.nav.groups.map((g) => ({ label: g.label, entries: g.modules.flatMap((m) => m.entries) })));
</script>

<div class="st fade">
  <section>
    <div class="sh"><span class="cap">~/you</span><span class="mono dim">only you · saved to your account</span></div>
    <div class="grid">
      <span class="k">theme</span>
      <div class="seg" role="group" aria-label="Theme">
        {#each [['auto', 'auto'], ['dark', 'moon'], ['light', 'sun']] as [t, ic]}
          <button aria-pressed={lab.theme === t} onclick={() => lab.setTheme(t)}><Icon name={ic} size={13} />{t}</button>
        {/each}
      </div>
      <span class="k">refresh</span>
      <div class="seg" role="group" aria-label="Refresh interval">
        {#each [5, 10, 15, 30, 60, 300] as n}
          <button aria-pressed={(Number(lab.prefs.refresh) === 0 ? -1 : Number(lab.prefs.refresh) || 15) === n} onclick={() => lab.savePref('refresh', n)}>{n < 60 ? n + 's' : n / 60 + 'm'}</button>
        {/each}
        <button aria-pressed={Number(lab.prefs.refresh) === 0} onclick={() => lab.savePref('refresh', 0)}>off</button>
      </div>
      <span class="k">start page</span>
      <select class="field mono sel" value={lab.prefs.home || homeCore[0]?.id || lab.views[0]} onchange={(e) => lab.savePref('home', e.currentTarget.value)} aria-label="Start page">
        {#if homeCore.length}<optgroup label="~/lab">{#each homeCore as e (e.id)}<option value={e.id}>{e.label}</option>{/each}</optgroup>{/if}
        {#each homeGroups as g (g.label)}
          <optgroup label="~/{g.label}">{#each g.entries as e (e.id)}<option value={e.id}>{e.label}</option>{/each}</optgroup>
        {/each}
      </select>
      <span class="k">ticker</span>
      <button class="tog mono" aria-pressed={lab.prefs.ticker !== false} onclick={() => lab.savePref('ticker', lab.prefs.ticker === false)}>{lab.prefs.ticker === false ? 'off' : 'on'}</button>
      <span class="k">layout</span>
      <div class="row">
        <button class="btn" onclick={() => { lab.savePref('wall.order', []); lab.savePref('wall.hidden', []); }}>reset wall</button>
        <button class="btn" onclick={() => lab.savePref('rail.state', {})}>reset menu groups</button>
      </div>
    </div>
  </section>

  <AccountSettings />
  {#if lab.role !== 'guest'}<LoginSettings />{/if}
  {#if lab.role === 'owner'}<UpdateSettings />{/if}
  {#if lab.role === 'owner'}<ModuleStore onchanged={load} />{/if}

  {#if lab.role !== 'guest'}
    <section>
      <div class="sh">
        <span class="cap">~/modules · {mods.length}</span>
        <input class="field mono s" placeholder="$ grep modules…" bind:value={q} aria-label="Filter modules" />
        <span class="mono dim">{editable ? 'owner: changes apply to everyone at once' : 'read-only — module settings are owner-only'}</span>
      </div>
      {#each shown as m (m.id)}
        {@const v = m.values}
        <div class="mod" class:off={!m.enabled}>
          <button class="mh lnk" aria-expanded={open === m.id} onclick={() => (open = open === m.id ? null : m.id)}>
            <span class="mono chev">{open === m.id ? '▾' : '▸'}</span>
            <span class={m.needsSetup ? 'warn' : m.health?.up === false ? 'bad' : m.enabled ? 'ok' : 'off'}>{m.needsSetup ? '▲' : '●'}</span>
            <span class="mono id">{m.id}</span>
            <span class="nm">{m.name}</span>
            {#if m.source === 'installed'}<span class="mono src" title="installed from a catalog ({m.installed?.publisher?.name}){m.installed?.replaces ? ` — replaces the bundled ${m.installed.replaces}` : ''}">{m.installed?.version} · catalog</span>{/if}
            <span class="mono dim flags">
              {#if m.needsSetup}needs setup{:else if !m.enabled}off{:else}
                {['_ticker', '_overview', '_alerts', '_tiles'].filter((k) => v[k] === false).map((k) => 'no ' + k.slice(1)).join(' · ')}
              {/if}
            </span>
          </button>
          <button class="tog mono" aria-pressed={m.enabled} disabled={!editable} aria-label="{m.id} on/off"
            onclick={() => { if (m.enabled && !confirm(`Turn ${m.id} off for everyone?`)) return; if (!m.enabled && privileged(m) && !confirm(`${m.id} is privileged: ${privileged(m)}. Turn it on?`)) return; save(m, { enabled: !m.enabled }, m.enabled ? 'off' : 'on'); }}>{m.enabled ? 'on' : 'off'}</button>
        </div>
        {#if open === m.id}
          <div class="body">
            {#if m.description}<p class="dim desc">{m.description}</p>{/if}
            <div class="grid">
              {#if m.configurable}<ModuleConfig {m} {editable} onsaved={load} />{/if}
              {#if privileged(m)}<span class="k">privileged</span><span class="mono warn small">▲ {privileged(m)}</span>{/if}
              <span class="k">access</span>
              <div class="acc">
                <span class="mono">{m.roles.join(' + ')}</span>
                {#each m.groups as g}<span class="chip mono" title="from the manifest">{g}</span>{/each}
                {#each m.extraGroups as g}
                  <span class="chip mono x">{g}{#if editable}<button aria-label="Remove {g}" onclick={() => save(m, { extraGroups: m.extraGroups.filter((x) => x !== g) }, `- ${g}`)}>×</button>{/if}</span>
                {/each}
                {#if editable}
                  <input class="field mono s" placeholder="+ authentik group" bind:value={groupDraft[m.id]} aria-label="Add group"
                    onkeydown={(e) => { if (e.key === 'Enter' && groupDraft[m.id]?.trim()) { save(m, { extraGroups: [...m.extraGroups, groupDraft[m.id].trim()] }, `+ ${groupDraft[m.id].trim()}`); groupDraft[m.id] = ''; } }} />
                {/if}
              </div>
              {#each m.schema as st (st.key)}
                <span class="k" title={st.help || ''}>{st.label || st.key}</span>
                {#if st.type === 'bool'}
                  <button class="tog mono" aria-pressed={v[st.key] !== false} disabled={!editable} onclick={() => setVal(m, st.key, v[st.key] === false, st.label)}>{v[st.key] === false ? 'off' : 'on'}</button>
                {:else if st.type === 'enum'}
                  <select class="field mono sel" value={v[st.key]} disabled={!editable} onchange={(e) => setVal(m, st.key, e.currentTarget.value, st.label)} aria-label={st.label || st.key}>
                    {#each st.options as o}<option value={o}>{o}</option>{/each}
                  </select>
                {:else if st.type === 'int'}
                  <input class="field mono num" type="number" min={st.min} max={st.max} value={v[st.key]} disabled={!editable} aria-label={st.label || st.key}
                    onchange={(e) => setVal(m, st.key, Number(e.currentTarget.value), st.label)} />
                {:else if st.type === 'list'}
                  <input class="field mono" value={(v[st.key] || []).join(', ')} disabled={!editable} aria-label={st.label || st.key}
                    onchange={(e) => setVal(m, st.key, e.currentTarget.value.split(',').map((x) => x.trim()).filter(Boolean), st.label)} />
                {:else}
                  <input class="field mono" value={v[st.key] ?? ''} disabled={!editable} aria-label={st.label || st.key}
                    onchange={(e) => setVal(m, st.key, e.currentTarget.value, st.label)} />
                {/if}
              {/each}
            </div>
          </div>
        {/if}
      {/each}
    </section>
  {/if}
</div>

<style>
  section { border-bottom: 1px solid var(--line); padding-bottom: 8px; }
  .sh { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; padding: 14px 20px 10px; font-size: 11.5px; }
  .grid { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 10px 16px; align-items: center; padding: 6px 20px 12px; max-width: 900px; }
  .k { font: 12px "Geist Mono Variable", monospace; color: var(--dim); }
  .grid .seg, .grid .row { justify-self: start; }
  .row, .acc { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .sel { max-width: 260px; padding: 5px 8px; font-size: 12px; }
  .s { max-width: 200px; padding: 5px 8px; font-size: 12px; }
  .num { max-width: 120px; padding: 5px 8px; }
  .tog { justify-self: start; min-width: 52px; padding: 4px 10px; font-size: 11.5px; border: 1px solid var(--line); border-radius: 12px; background: transparent; color: var(--dim); }
  .tog[aria-pressed="true"] { background: var(--sig); border-color: var(--sig); color: var(--sigink); }
  .tog:disabled { opacity: .6; cursor: default; }
  .mod { display: flex; align-items: center; gap: 10px; padding: 4px 20px 4px 12px; border-top: 1px solid var(--q); }
  .mod.off .nm, .mod.off .id { color: var(--faint); }
  .mh { flex: 1; display: flex; align-items: center; gap: 10px; padding: 6px 0; min-width: 0; }
  .mh > span:nth-child(2) { font-size: 9px; }
  .chev { width: 10px; font-size: 10px; color: var(--dim); }
  .id { font-size: 12.5px; width: 90px; }
  .nm { font-size: 13px; }
  .flags { margin-left: auto; font-size: 11px; }
  .src { font-size: 10.5px; padding: 0 5px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .body { padding: 2px 20px 12px 42px; background: var(--panel); border-top: 1px solid var(--q); }
  .desc { margin: 8px 0 4px; font-size: 12.5px; }
  .chip { font-size: 11px; padding: 1px 7px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); display: inline-flex; gap: 4px; align-items: center; }
  .chip.x { border-color: var(--sig); color: var(--sig); }
  .chip button { border: none; background: none; color: inherit; padding: 0; }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
</style>
