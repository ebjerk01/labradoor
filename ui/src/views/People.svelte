<script>
  // ~/people — every account (local and/or SSO), its role, groups, 2FA and sessions. The owner adds local accounts,
  // changes role/groups, links an account to SSO, disables, resets 2FA or a password, logs out, deletes. Admins read.
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';
  import { ago } from '$lab/fmt.js';
  import { ROLES } from '$lab/login.js';
  import PasswordField from '../shell/PasswordField.svelte';

  let users = $state([]);
  let sessions = $state([]);
  let q = $state('');
  let open = $state(null);      // username being edited
  let adding = $state(false);
  let draft = $state({ username: '', name: '', password: '', role: 'guest', groups: '', sso: false });
  let pw = $state('');          // a new password for the open account
  let busy = $state(false);
  const owner = $derived(lab.role === 'owner');

  async function load() { try { const r = await api.get('/api/users'); users = r.users; sessions = r.sessions; } catch (e) { lab.notify(e.message, 'bad'); } }
  $effect(() => { load(); });

  const split = (s) => s.split(',').map((x) => x.trim()).filter(Boolean);
  async function run(fn, ok) {
    busy = true;
    try { const r = await fn(); lab.notify(typeof ok === 'function' ? ok(r) : ok); await load(); return true; }
    catch (e) { lab.notify(e.message, 'bad'); return false; } finally { busy = false; }
  }
  const change = (u, body, label) => run(() => api.post(`/api/users/${encodeURIComponent(u.username)}`, body),
    (r) => `${u.username}: ${label} ✓${r.ended ? ` · ${r.ended} session(s) ended` : ''}`);
  async function create(e) {
    e.preventDefault();
    const d = draft;
    if (await run(() => api.post('/api/users', { username: d.username.trim(), name: d.name.trim(), password: d.password,
      role: d.role, groups: split(d.groups), sso: d.sso }), `${d.username}: created ✓`)) {
      adding = false; draft = { username: '', name: '', password: '', role: 'guest', groups: '', sso: false };
    }
  }
  const revoke = (u) => run(() => api.post(`/api/users/${encodeURIComponent(u.username)}/logout`), (r) => `${u.username}: ${r.ended} session(s) ended`);
  function remove(u) {
    if (!confirm(`Delete ${u.username}? Their prefs and sessions go too.${u.sso ? ' An SSO account comes back at its next SSO login: disable it instead to keep it out.' : ''}`)) return;
    run(() => api.post(`/api/users/${encodeURIComponent(u.username)}/delete`), `${u.username}: deleted`).then(() => (open = null));
  }
  const shown = $derived(users.filter((u) => !q || `${u.username} ${u.name} ${u.email} ${u.role} ${u.groups.join(' ')}`.toLowerCase().includes(q.toLowerCase())));
  const RC = { owner: 'sig', admin: 'ok', guest: 'dim' };
  const nsess = (u) => sessions.filter((s) => s.username === u.username).length;
</script>

<div class="ppl fade">
  <div class="head">
    <span class="cap">~/people · {users.length}</span>
    <input class="field mono s" placeholder="$ grep people…" bind:value={q} aria-label="Filter people" />
    {#if owner}<button class="btn" onclick={() => (adding = !adding)}>{adding ? 'cancel' : '+ local account'}</button>{/if}
  </div>
  <p class="mono dim intro">
    {#if lab.sso}SSO accounts get their role from {lab.ssoName || 'the login service'}'s groups at each login:
      <span class="sig">{lab.roleGroups?.owner || '–'}</span> → owner, <span class="ok">{lab.roleGroups?.admin || '–'}</span> → admin,
      anyone else → guest. Local accounts keep the role set here.{:else}Local accounts: the role and guest groups are set here (guests see the modules their groups unlock).{/if}
  </p>

  {#if adding && owner}
    <form class="add" onsubmit={create}>
      <div class="f"><label class="cap" for="nu">username</label><input id="nu" class="field" bind:value={draft.username} autocapitalize="none" spellcheck="false" autocomplete="off" /></div>
      <div class="f"><label class="cap" for="nn">display name</label><input id="nn" class="field" bind:value={draft.name} autocomplete="off" /></div>
      <div class="f"><PasswordField bind:value={draft.password} id="np" label="first password" /></div>
      <div class="f"><span class="cap">role</span>
        <div class="seg" role="group" aria-label="Role">{#each ROLES as r}<button type="button" aria-pressed={draft.role === r} onclick={() => (draft.role = r)}>{r}</button>{/each}</div></div>
      <div class="f"><label class="cap" for="ng">groups <span class="faint">· comma separated</span></label><input id="ng" class="field mono" bind:value={draft.groups} placeholder="media, family" /></div>
      {#if lab.sso}<label class="chk mono"><input type="checkbox" bind:checked={draft.sso} /> may also log in with {lab.ssoName || 'SSO'} (same username)</label>{/if}
      <button class="btn primary" disabled={busy || !draft.username || !draft.password}>create</button>
    </form>
  {/if}

  {#each shown as u (u.username)}
    <div class="u row" class:off={u.disabled}>
      <span class="mono role {u.disabled ? 'faint' : RC[u.role]}">{u.role}</span>
      <div class="who"><span>{u.name || u.username}</span><span class="mono dim">{u.username}{u.email ? ' · ' + u.email : ''}</span></div>
      <span class="mono flags">
        {#if u.disabled}<span class="bad" title="disabled: can't log in">■ disabled</span>{/if}
        {#if u.local}<span class="dim" title="has a local password">pw</span>{/if}
        {#if u.sso}<span class="dim" title="may log in with SSO">sso</span>{/if}
        {#if u.local}<span class={u.totp ? 'ok' : 'faint'} title={u.totp ? `2FA on · ${u.recovery_left} recovery codes left` : 'no 2FA'}>{u.totp ? '● 2fa' : '○ 2fa'}</span>{/if}
      </span>
      <span class="mono dim grp" title={u.groups.join(' ')}>{u.groups.join(' ')}</span>
      <span class="mono dim seen" title="last seen">{u.last_seen ? ago(u.last_seen, lab.now) : 'never'}</span>
      <span class="mono dim n" title="active sessions">{nsess(u) || ''}</span>
      {#if owner}<button class="btn" aria-expanded={open === u.username} onclick={() => { open = open === u.username ? null : u.username; pw = ''; }}>{open === u.username ? 'close' : 'edit'}</button>{/if}
    </div>
    {#if owner && open === u.username}
      {@const self = u.username === lab.me?.username}
      <div class="edit">
        <span class="k">role</span>
        <div class="seg" role="group" aria-label="Role of {u.username}">
          {#each ROLES as r}<button aria-pressed={u.role === r} disabled={busy || self} onclick={() => change(u, { role: r }, `role ${r}`)}>{r}</button>{/each}
        </div>
        <span class="k">groups</span>
        <input class="field mono" value={u.groups.join(', ')} aria-label="Groups of {u.username}"
          onchange={(e) => change(u, { groups: split(e.currentTarget.value) }, 'groups')} />
        {#if u.sso && lab.sso}<span></span><span class="mono dim note">an SSO login replaces role + groups with the login service's</span>{/if}
        {#if lab.sso || u.sso}
          <span class="k">sso login</span>
          <button class="tog mono" aria-pressed={u.sso} disabled={busy} onclick={() => change(u, { sso: !u.sso }, u.sso ? 'sso off' : 'sso on')}>{u.sso ? 'on' : 'off'}</button>
        {/if}
        <span class="k">password</span>
        <div class="pw"><PasswordField bind:value={pw} id="pw-{u.username}" label={u.local ? 'new password' : 'set a local password'} />
          <button class="btn" disabled={busy || pw.length < 12} onclick={() => change(u, { password: pw }, 'password').then(() => (pw = ''))}>save password</button></div>
        {#if u.totp}
          <span class="k">2fa</span>
          <button class="btn" disabled={busy} onclick={() => confirm(`Turn 2FA off for ${u.username}? (lost phone) They can enrol again in Settings.`) && change(u, { totp_reset: true }, '2FA reset')}>reset 2FA (lost phone)</button>
        {/if}
        <span class="k">access</span>
        <div class="acts">
          <button class="btn" disabled={busy || !nsess(u)} onclick={() => revoke(u)}>log out {nsess(u) || ''}</button>
          {#if !self}
            <button class="btn" disabled={busy} onclick={() => change(u, { disabled: !u.disabled }, u.disabled ? 'enabled' : 'disabled')}>{u.disabled ? 'enable' : 'disable'}</button>
            <button class="btn" disabled={busy} onclick={() => remove(u)}>delete</button>
          {/if}
        </div>
      </div>
    {/if}
  {/each}
  {#if !shown.length}<p class="mono dim intro">{q ? 'no match' : 'no accounts yet'}</p>{/if}
</div>

<style>
  .head { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 14px 20px 4px; font-size: 11.5px; }
  .s { max-width: 220px; padding: 5px 8px; font-size: 12px; }
  .intro { padding: 6px 20px 12px; font-size: 12px; max-width: 900px; margin: 0; }
  .u { display: grid; grid-template-columns: 52px minmax(160px, 1.2fr) minmax(90px, auto) minmax(0, 1.5fr) 64px 24px auto; gap: 12px; align-items: center; padding: 9px 20px; border-top: 1px solid var(--q); }
  .u.off .who span:first-child { color: var(--faint); }
  .role { font-size: 11.5px; }
  .who { display: flex; flex-direction: column; min-width: 0; }
  .who span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .who .mono, .grp, .seen, .n, .flags { font-size: 11px; }
  .flags { display: flex; gap: 8px; }
  .grp { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .add { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: flex-end; padding: 12px 20px 16px; background: var(--panel); border-top: 1px solid var(--q); }
  .add .f { display: flex; flex-direction: column; gap: 4px; flex: 1 1 180px; min-width: 0; }
  .chk { font-size: 11.5px; display: flex; gap: 6px; align-items: center; color: var(--dim); flex-basis: 100%; }
  .edit { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 10px 16px; align-items: center; padding: 10px 20px 14px 84px; background: var(--panel); border-top: 1px solid var(--q); }
  .edit .seg, .edit .tog, .edit > .btn { justify-self: start; }
  .k { font: 12px "Geist Mono Variable", monospace; color: var(--dim); }
  .note { font-size: 11px; }
  .pw { display: flex; flex-direction: column; gap: 4px; max-width: 360px; }
  .pw .btn { align-self: flex-start; margin-top: 4px; }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; }
  .tog { min-width: 52px; padding: 4px 10px; font-size: 11.5px; border: 1px solid var(--line); border-radius: 12px; background: transparent; color: var(--dim); }
  .tog[aria-pressed="true"] { background: var(--sig); border-color: var(--sig); color: var(--sigink); }
  @media (max-width: 760px) {
    .u { grid-template-columns: 48px minmax(0, 1fr) auto; gap: 4px 10px; padding: 9px 16px; }
    .u .grp { grid-column: 2 / 4; grid-row: 2; }
    .u .flags { grid-column: 2; grid-row: 3; }
    .u .seen, .u .n { display: none; }
    .u .btn { grid-column: 3; grid-row: 1; }
    .edit { grid-template-columns: 1fr; padding: 10px 16px 14px; }
    .head, .intro, .add { padding-left: 16px; padding-right: 16px; }
  }
</style>
