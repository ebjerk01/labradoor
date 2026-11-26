<script>
  // The login page: local accounts (password, then a 2FA code when the account has one) and, when single sign-on is
  // configured, its button. With SSO on, the local form is one click away (local accounts / break-glass).
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';
  const params = new URLSearchParams(location.search);
  let local = $state(params.get('login') === 'local' || !lab.sso);
  let username = $state('');
  let password = $state('');
  let code = $state('');
  let needCode = $state(false);
  let err = $state(params.get('sso_error') || '');
  let busy = $state(false);
  const next = location.pathname + location.hash;

  async function submit(e) {
    e.preventDefault();
    busy = true; err = '';
    try {
      await api.post('/auth/local', { username, password, ...(needCode ? { code } : {}) });
      location.href = '/' + location.hash;
    } catch (x) {
      if (x.body?.totp) {
        if (needCode) err = x.message;
        needCode = true; code = '';
        setTimeout(() => document.getElementById('c')?.focus(), 0);
      } else { err = x.message; needCode = false; }
    } finally { busy = false; }
  }
</script>

<main class="login">
  <div class="box">
    <div><span class="mono word">{lab.brand}</span><span class="mono word sig">/</span><span class="cursor"></span></div>
    <pre class="mono dim">guest@{lab.brand}:~$ whoami
whoami: cannot find name for user ID 65534
guest@{lab.brand}:~$ <span class="sig">login</span></pre>
    {#if lab.setup}
      <p class="mono small setup"><span class="warn">▲</span> first run: no owner yet. Open the one-time setup link the installer printed
        (or run <span class="sig">lab-admin setup-link</span> on the server).</p>
    {/if}
    {#if err}<p class="mono bad small" role="alert">{err}</p>{/if}
    {#if lab.sso && !local}
      <a class="btn primary go" href="/auth/login?next={encodeURIComponent(next)}">sign in with {lab.ssoName || 'SSO'}</a>
      <button class="lnk mono dim small" onclick={() => (local = true)}>local account</button>
    {:else}
      <form onsubmit={submit}>
        {#if !needCode}
          <label class="cap" for="u">user</label><input id="u" class="field" bind:value={username} autocomplete="username" />
          <label class="cap" for="p">password</label><input id="p" class="field" type="password" bind:value={password} autocomplete="current-password" />
        {:else}
          <p class="mono dim small">{username} · two-factor</p>
          <label class="cap" for="c">code from your authenticator app</label>
          <input id="c" class="field mono code" bind:value={code} inputmode="text" autocomplete="one-time-code" maxlength="12" placeholder="000000" />
          <span class="mono dim small">lost the phone? type a recovery code (xxxxx-xxxxx) instead</span>
        {/if}
        <button class="btn primary go" disabled={busy}>{busy ? 'checking…' : needCode ? 'verify' : 'log in'}</button>
        {#if needCode}<button type="button" class="lnk mono dim small" onclick={() => { needCode = false; err = ''; }}>back</button>{/if}
        {#if lab.sso}<button type="button" class="lnk mono dim small" onclick={() => (local = false)}>use {lab.ssoName || 'SSO'}</button>{/if}
      </form>
    {/if}
  </div>
</main>

<style>
  .login { min-height: 100vh; display: grid; place-items: center; padding: 16px;
    background-image: radial-gradient(var(--line) 1px, transparent 1px); background-size: 22px 22px; }
  .box { width: min(400px, 100%); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 28px; display: flex; flex-direction: column; gap: 14px; }
  .word { font-size: 30px; font-weight: 600; letter-spacing: -.02em; }
  pre { margin: 0; font-size: 12px; white-space: pre-wrap; }
  .go { justify-content: center; padding: 10px; font-size: 13px; text-decoration: none; }
  form { display: flex; flex-direction: column; gap: 6px; }
  form .go { margin-top: 10px; }
  .small { font-size: 11.5px; margin: 0; }
  .setup { color: var(--dim); }
  .code { letter-spacing: .25em; font-size: 16px; }
  @media (max-width: 420px) { .box { padding: 20px 16px; } }
</style>
