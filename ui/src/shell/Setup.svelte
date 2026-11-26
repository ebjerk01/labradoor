<script>
  // First run (/setup#<token>): create the owner account. The token comes from the installer / journal /
  // `lab-admin setup-link`, works once and for one hour; once an owner exists this page has nothing to do.
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';
  import PasswordField from './PasswordField.svelte';
  import TotpEnrol from './TotpEnrol.svelte';
  import RecoveryCodes from './RecoveryCodes.svelte';

  // the token leaves the address bar (history, screenshots) but survives a reload of this tab (sessionStorage, dropped
  // when the owner is created); a link opened without it says so instead of calling it invalid
  const KEY = 'lab.setup-token';
  const fromHash = location.hash.replace(/^#/, '');
  let token = fromHash;
  try { if (fromHash) sessionStorage.setItem(KEY, fromHash); else token = sessionStorage.getItem(KEY) || ''; } catch { /* storage off */ }
  history.replaceState(null, '', '/setup');
  const forget = () => { try { sessionStorage.removeItem(KEY); } catch { /* storage off */ } };
  let state = $state('checking');  // checking | form | notoken | bad | done | owner
  let username = $state('');
  let name = $state('');
  let password = $state('');
  let confirm = $state('');
  let with2fa = $state(true);
  let secret = $state('');
  let code = $state('');
  let err = $state('');
  let busy = $state(false);
  let recovery = $state(null);

  (async () => {
    let firstRun = true;
    try { const me = await api.get('/api/me'); if (me.brand) lab.brand = me.brand; firstRun = !!me.setup; } catch { /* offline */ }
    if (!token) { state = firstRun ? 'notoken' : 'owner'; if (!firstRun) forget(); return; }
    try { state = (await api.post('/api/setup/check', { token })).ok ? 'form' : 'bad'; }
    catch (e) { state = e.status === 404 ? 'owner' : 'bad'; err = e.status === 429 ? e.message : ''; }
    if (state === 'owner') forget();
  })();

  async function submit(e) {
    e.preventDefault();
    err = '';
    if (password !== confirm) { err = 'the two passwords differ'; return; }
    if (with2fa && !/^\d{6}$/.test(code.trim())) { err = 'type the 6-digit code from the app (or switch 2FA off for now)'; return; }
    busy = true;
    try {
      const r = await api.post('/api/setup', { token, username: username.trim(), name: name.trim(), password,
        ...(with2fa ? { totp_secret: secret, totp_code: code.trim() } : {}) });
      forget();
      if (r.recovery) { recovery = r.recovery; state = 'done'; } else location.href = '/';
    } catch (x) { err = x.message; if (x.status === 404) state = 'owner'; } finally { busy = false; }
  }
</script>

<main class="setup">
  <div class="box">
    <div><span class="mono word">{lab.brand}</span><span class="mono word sig">/</span><span class="mono dim">setup</span><span class="cursor"></span></div>
    {#if state === 'checking'}
      <p class="mono dim"><span class="spin">checking the setup link</span></p>
    {:else if state === 'owner'}
      <p class="mono">● this installation has an owner already.</p>
      <a class="btn primary go" href="/">log in</a>
    {:else if state === 'notoken'}
      <p class="mono bad">■ there is no setup token in this address.</p>
      <p class="dim small">Open the whole setup link again, exactly as the installer printed it (the part after <span class="mono">#</span> is the token). If you no longer have it, print a fresh one on the Proxmox host (ID = the container):</p>
      <pre class="mono cmd">pct exec ID -- lab-admin setup-link</pre>
    {:else if state === 'bad'}
      <p class="mono bad">■ this setup link is invalid, used or expired.</p>
      {#if err}<p class="mono dim small">{err}</p>{/if}
      <p class="dim small">A setup link works once, for one hour, and only the newest one works. Print a fresh one on the Proxmox host (ID = the container), or run <span class="mono">lab-admin setup-link</span> as root inside it:</p>
      <pre class="mono cmd">pct exec ID -- lab-admin setup-link</pre>
    {:else if state === 'done'}
      <p class="mono">● owner <span class="sig">{username}</span> created, two-factor login is on.</p>
      <RecoveryCodes codes={recovery} ondone={() => (location.href = '/')} />
    {:else}
      <pre class="mono dim">root@{lab.brand}:~# useradd --owner</pre>
      <p class="dim small">Create the owner account: it can do everything here, including adding people and single sign-on (Settings → login).</p>
      <form onsubmit={submit}>
        <label class="cap" for="su">username</label>
        <input id="su" class="field" bind:value={username} autocomplete="username" autocapitalize="none" spellcheck="false" />
        <label class="cap" for="sn">display name <span class="faint">· optional</span></label>
        <input id="sn" class="field" bind:value={name} autocomplete="name" />
        <PasswordField bind:value={password} id="sp" />
        <label class="cap" for="sc">password again</label>
        <input id="sc" class="field" type="password" bind:value={confirm} autocomplete="new-password" />
        <div class="tf">
          <button type="button" class="tog mono" aria-pressed={with2fa} onclick={() => (with2fa = !with2fa)}>{with2fa ? 'on' : 'off'}</button>
          <span class="mono small">two-factor login (TOTP) <span class="dim">· recommended</span></span>
        </div>
        {#if with2fa}<TotpEnrol username={username || 'owner'} bind:secret bind:code />{/if}
        {#if err}<p class="mono bad small" role="alert">{err}</p>{/if}
        <button class="btn primary go" disabled={busy || !username || !password}>{busy ? 'creating…' : 'create owner'}</button>
      </form>
    {/if}
  </div>
</main>

<style>
  .setup { min-height: 100vh; display: grid; place-items: center; padding: 16px;
    background-image: radial-gradient(var(--line) 1px, transparent 1px); background-size: 22px 22px; }
  .box { width: min(480px, 100%); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 28px; display: flex; flex-direction: column; gap: 12px; }
  .word { font-size: 30px; font-weight: 600; letter-spacing: -.02em; }
  pre { margin: 0; font-size: 12px; white-space: pre-wrap; }
  .cmd { background: var(--q); padding: 8px 10px; border-radius: 4px; color: var(--ink); }
  p { margin: 0; }
  .small { font-size: 12px; }
  form { display: flex; flex-direction: column; gap: 6px; }
  .go { justify-content: center; padding: 10px; font-size: 13px; text-decoration: none; margin-top: 8px; }
  .tf { display: flex; align-items: center; gap: 10px; margin: 10px 0 4px; }
  .tog { min-width: 52px; padding: 4px 10px; font-size: 11.5px; border: 1px solid var(--line); border-radius: 12px; background: transparent; color: var(--dim); }
  .tog[aria-pressed="true"] { background: var(--sig); border-color: var(--sig); color: var(--sigink); }
  @media (max-width: 420px) { .box { padding: 20px 16px; } }
</style>
