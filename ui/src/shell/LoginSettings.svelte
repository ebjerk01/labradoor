<script>
  // Settings → ~/login (owner edits, admins read): single sign-on (OpenID Connect), the SSO groups that make owner /
  // admin, the 2FA policy and session lengths. A field set in the server's environment (/etc/lab/lab.env) wins and is
  // shown locked. The client secret is write-only: the gateway only says whether one is stored.
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';

  let cfg = $state(null);
  let draft = $state({});
  let busy = $state('');
  let test = $state(null);
  let err = $state('');
  async function load() {
    try { cfg = await api.get('/api/login/settings'); draft = {}; err = ''; } catch (e) { err = e.message; }
  }
  $effect(() => { if (lab.role !== 'guest') load(); });
  const f = $derived(Object.fromEntries((cfg?.fields || []).map((x) => [x.key, x])));
  const val = (k) => (k in draft ? draft[k] : f[k]?.value ?? '');
  const locked = (k) => !cfg?.editable || f[k]?.source === 'env';
  const dirty = (keys) => keys.some((k) => k in draft);
  const SSO = ['sso_issuer', 'sso_client_id', 'sso_client_secret', 'sso_name', 'owner_group', 'admin_group'];
  const POLICY = ['require_2fa', 'session_days', 'local_session_days', 'sso_max_age_hours'];

  async function save(keys, label) {
    busy = 'save'; test = null;
    const values = {};
    for (const k of keys) if (k in draft) values[k] = draft[k] === '' ? null : draft[k];
    try {
      const r = await api.post('/api/login/settings', { values });
      cfg = { ...cfg, fields: r.fields, ssoActive: r.ssoActive }; draft = {};
      lab.notify(`login: ${label} saved ✓`);
      await load();
    } catch (e) { lab.notify(e.message, 'bad'); } finally { busy = ''; }
  }
  async function runTest() {
    busy = 'test'; test = null;
    try { test = await api.post('/api/login/test', draft.sso_issuer ? { issuer: draft.sso_issuer } : {}); }
    catch (e) { test = { ok: false, error: e.message }; } finally { busy = ''; }
  }
  async function copy(t) { try { await navigator.clipboard.writeText(t); lab.notify('copied ✓'); } catch { /* none */ } }
</script>

{#if cfg}
  <section>
    <div class="sh">
      <span class="cap">~/login</span>
      <span class="mono dim">{cfg.editable ? 'owner: applies to everyone at once' : 'read-only — login settings are owner-only'}</span>
    </div>

    <div class="sub mono"><span class={cfg.ssoActive ? 'ok' : 'faint'}>{cfg.ssoActive ? '●' : '○'}</span> single sign-on (OpenID Connect) <span class="dim">· {cfg.ssoActive ? 'on' : 'off: local accounts only'}</span></div>
    <div class="grid">
      {#each SSO as k (k)}
        {@const x = f[k]}
        <label class="k" for="lg-{k}">{x.label}</label>
        <div class="fld">
          {#if x.type === 'secret'}
            <input id="lg-{k}" class="field mono" type="password" autocomplete="new-password" disabled={locked(k)}
              placeholder={x.set ? '•••••• stored (type to replace)' : 'not set'} value={draft[k] ?? ''} oninput={(e) => (draft[k] = e.currentTarget.value)} />
          {:else}
            <input id="lg-{k}" class="field mono" disabled={locked(k)} value={val(k)} spellcheck="false"
              placeholder={k === 'sso_issuer' ? 'https://login.example.com/application/o/labradoor/' : k === 'sso_name' ? 'shown on the button' : ''}
              oninput={(e) => (draft[k] = e.currentTarget.value)} />
          {/if}
          {#if x.source === 'env'}<span class="tag mono" title="set in /etc/lab/lab.env: change it there">env {x.env}</span>{/if}
        </div>
      {/each}
      <span class="k">redirect URI</span>
      <div class="fld"><span class="mono uri">{cfg.redirectUri}</span><button class="lnk mono small" onclick={() => copy(cfg.redirectUri)}>copy</button></div>
      <span class="k">role refresh</span>
      <span class="mono dim small">{cfg.rolesync === 'authentik' ? `● from the authentik module every ${Math.round(cfg.rolesyncSeconds / 60)} min (removed users are logged out)`
        : `○ none — SSO sessions end after ${f.sso_max_age_hours.value} h, then roles are read again at login`}</span>
      {#if cfg.editable}
        <span></span>
        <div class="row">
          <button class="btn" disabled={!!busy || !(val('sso_issuer'))} onclick={runTest}>{busy === 'test' ? 'testing…' : 'test issuer'}</button>
          <button class="btn primary" disabled={!!busy || !dirty(SSO)} onclick={() => save(SSO, 'single sign-on')}>save</button>
          {#if test}<span class="mono small {test.ok ? 'ok' : 'bad'}">{test.ok ? `● discovery ok${test.pkce ? ' · PKCE' : ' · ▲ no PKCE S256 advertised'}` : `■ ${test.error}`}</span>{/if}
        </div>
      {/if}
    </div>

    <div class="sub mono">policy</div>
    <div class="grid">
      <span class="k">{f.require_2fa.label}</span>
      <div class="fld">
        <button class="tog mono" aria-pressed={!!val('require_2fa')} disabled={locked('require_2fa') || !!busy}
          onclick={() => { draft.require_2fa = !val('require_2fa'); save(['require_2fa'], '2FA policy'); }}>{val('require_2fa') ? 'on' : 'off'}</button>
        {#if f.require_2fa.source === 'env'}<span class="tag mono">env {f.require_2fa.env}</span>{/if}
        {#if cfg.without2fa.length}<span class="mono small warn" title="local owners/admins without 2FA: they must enrol at their next login when this is on">▲ no 2FA: {cfg.without2fa.join(', ')}</span>{/if}
      </div>
      {#each ['session_days', 'local_session_days', 'sso_max_age_hours'] as k (k)}
        {@const x = f[k]}
        <label class="k" for="lg-{k}">{x.label}</label>
        <div class="fld">
          <input id="lg-{k}" class="field mono num" type="number" min={x.min} max={x.max} disabled={locked(k)} value={val(k)}
            oninput={(e) => (draft[k] = Number(e.currentTarget.value))} />
          {#if x.source === 'env'}<span class="tag mono">env {x.env}</span>{/if}
        </div>
      {/each}
      {#if cfg.editable}
        <span></span>
        <div class="row"><button class="btn primary" disabled={!!busy || !dirty(POLICY.slice(1))} onclick={() => save(POLICY.slice(1), 'session lengths')}>save</button>
          <span class="mono dim small">new lengths apply to the next login</span></div>
      {/if}
    </div>
  </section>
{:else if err}
  <p class="mono bad pad">{err}</p>
{/if}

<style>
  section { border-bottom: 1px solid var(--line); padding-bottom: 8px; }
  .sh { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; padding: 14px 20px 6px; font-size: 11.5px; }
  .sub { padding: 10px 20px 2px; font-size: 12px; color: var(--ink); }
  .grid { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 8px 16px; align-items: center; padding: 6px 20px 10px; max-width: 900px; }
  .k { font: 12px "Geist Mono Variable", monospace; color: var(--dim); }
  .fld { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-width: 0; }
  .fld .field { flex: 1 1 220px; max-width: 520px; padding: 6px 8px; font-size: 12px; }
  .fld .num { flex: 0 0 110px; }
  .field:disabled { opacity: .7; }
  .tag { font-size: 10.5px; padding: 1px 6px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .uri { font-size: 12px; word-break: break-all; }
  .small { font-size: 11.5px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .pad { padding: 14px 20px; }
  .tog { min-width: 52px; padding: 4px 10px; font-size: 11.5px; border: 1px solid var(--line); border-radius: 12px; background: transparent; color: var(--dim); }
  .tog[aria-pressed="true"] { background: var(--sig); border-color: var(--sig); color: var(--sigink); }
  .tog:disabled { opacity: .6; }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; padding: 6px 16px 10px; gap: 4px 0; } .sh, .sub { padding-left: 16px; padding-right: 16px; } .grid .k { margin-top: 6px; } }
</style>
