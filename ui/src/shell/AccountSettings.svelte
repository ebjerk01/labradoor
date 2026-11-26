<script>
  // Settings → ~/account: your own password and two-factor login (local accounts). SSO accounts manage both at the
  // login service.
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';
  import PasswordField from './PasswordField.svelte';
  import TotpEnrol from './TotpEnrol.svelte';
  import RecoveryCodes from './RecoveryCodes.svelte';

  let acc = $state(null);
  let mode = $state('');   // '' | password | enrol | recovery | off
  let cur = $state('');
  let next = $state('');
  let secret = $state('');
  let code = $state('');
  let codes = $state(null);
  let busy = $state(false);
  async function load() { try { acc = await api.get('/api/account'); } catch { acc = null; } }
  $effect(() => { load(); });
  function open(m) { mode = mode === m ? '' : m; cur = ''; next = ''; code = ''; secret = ''; codes = null; }
  async function go(url, body, ok) {
    busy = true;
    try { const r = await api.post(url, body); lab.notify(ok); if (r.recovery) codes = r.recovery; else mode = ''; await load(); }
    catch (e) { lab.notify(e.message, 'bad'); } finally { busy = false; }
  }
</script>

{#if acc}
  <section>
    <div class="sh"><span class="cap">~/account</span><span class="mono dim">{acc.username} · {acc.via === 'oidc' ? 'logged in with SSO' : 'local login'}</span></div>
    <div class="grid">
      {#if acc.local}
        <span class="k">password</span>
        <div class="row"><button class="btn" onclick={() => open('password')}>{mode === 'password' ? 'cancel' : 'change password'}</button></div>
        {#if mode === 'password'}
          <span></span>
          <form class="box" onsubmit={(e) => { e.preventDefault(); go('/api/account/password', { current: cur, password: next }, 'password changed ✓'); }}>
            <label class="cap" for="ac">current password</label><input id="ac" class="field" type="password" bind:value={cur} autocomplete="current-password" />
            <PasswordField bind:value={next} id="an" label="new password" />
            <button class="btn primary" disabled={busy || !cur || next.length < 12}>save</button>
          </form>
        {/if}
        <span class="k">two-factor</span>
        <div class="row">
          <span class="mono {acc.totp ? 'ok' : 'faint'}">{acc.totp ? `● on · ${acc.recoveryLeft} recovery codes left` : '○ off'}</span>
          {#if !acc.totp}<button class="btn" onclick={() => open('enrol')}>{mode === 'enrol' ? 'cancel' : 'turn on'}</button>
          {:else}
            <button class="btn" onclick={() => open('recovery')}>{mode === 'recovery' ? 'cancel' : 'new recovery codes'}</button>
            <button class="btn" disabled={acc.require2fa && lab.role !== 'guest'} title={acc.require2fa && lab.role !== 'guest' ? 'required for owners and admins here' : ''} onclick={() => open('off')}>{mode === 'off' ? 'cancel' : 'turn off'}</button>
          {/if}
        </div>
        {#if mode && mode !== 'password'}
          <span></span>
          {#if codes}
            <div class="box"><RecoveryCodes {codes} ondone={() => { codes = null; mode = ''; }} /></div>
          {:else}
            <form class="box" onsubmit={(e) => { e.preventDefault();
              if (mode === 'enrol') go('/api/account/totp', { password: cur, secret, code: code.trim() }, '2FA on ✓');
              else if (mode === 'recovery') go('/api/account/recovery', { password: cur }, 'new recovery codes ✓');
              else go('/api/account/totp/off', { password: cur }, '2FA off'); }}>
              {#if mode === 'enrol'}<TotpEnrol username={acc.username} bind:secret bind:code />{/if}
              <label class="cap" for="ap">your password</label><input id="ap" class="field" type="password" bind:value={cur} autocomplete="current-password" />
              <button class="btn primary" disabled={busy || !cur}>{mode === 'enrol' ? 'turn on 2FA' : mode === 'recovery' ? 'make new codes (old ones stop working)' : 'turn 2FA off'}</button>
            </form>
          {/if}
        {/if}
      {:else}
        <span class="k">login</span><span class="mono dim">your password and 2FA live at {lab.ssoName || 'the login service'}</span>
      {/if}
    </div>
  </section>
{/if}

<style>
  section { border-bottom: 1px solid var(--line); padding-bottom: 8px; }
  .sh { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; padding: 14px 20px 10px; font-size: 11.5px; }
  .grid { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 10px 16px; align-items: center; padding: 6px 20px 12px; max-width: 900px; }
  .k { font: 12px "Geist Mono Variable", monospace; color: var(--dim); }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; font-size: 12px; }
  .box { display: flex; flex-direction: column; gap: 6px; max-width: 480px; padding: 12px; border: 1px solid var(--line); border-radius: 4px; background: var(--panel); }
  .box .btn.primary { align-self: flex-start; margin-top: 6px; }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; padding: 6px 16px 12px; } .sh { padding: 14px 16px 10px; } }
</style>
