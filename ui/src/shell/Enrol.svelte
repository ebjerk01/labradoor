<script>
  // "Set up two-factor first": the owner requires 2FA for owners/admins and this local account has none yet. The
  // gateway answers everything else with 403 until enrolment is done.
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';
  import TotpEnrol from './TotpEnrol.svelte';
  import RecoveryCodes from './RecoveryCodes.svelte';

  let password = $state('');
  let secret = $state('');
  let code = $state('');
  let err = $state('');
  let busy = $state(false);
  let recovery = $state(null);

  async function submit(e) {
    e.preventDefault();
    busy = true; err = '';
    try { recovery = (await api.post('/api/account/totp', { password, secret, code: code.trim() })).recovery; }
    catch (x) { err = x.message; } finally { busy = false; }
  }
</script>

<main class="enrolpage">
  <div class="box">
    <div><span class="mono word">{lab.brand}</span><span class="mono word sig">/</span><span class="mono dim">2fa</span><span class="cursor"></span></div>
    {#if recovery}
      <p class="mono">● two-factor login is on for <span class="sig">{lab.me.username}</span>.</p>
      <RecoveryCodes codes={recovery} ondone={() => (location.href = '/')} />
    {:else}
      <p class="small"><span class="warn">▲</span> This installation requires two-factor login for owners and admins. Set it up to continue.</p>
      <form onsubmit={submit}>
        <TotpEnrol username={lab.me.username} bind:secret bind:code />
        <label class="cap" for="ep">your password</label>
        <input id="ep" class="field" type="password" bind:value={password} autocomplete="current-password" />
        {#if err}<p class="mono bad small" role="alert">{err}</p>{/if}
        <button class="btn primary go" disabled={busy || !password || !code}>{busy ? 'checking…' : 'turn on 2FA'}</button>
        <button type="button" class="lnk mono dim small" onclick={() => lab.logout()}>log out</button>
      </form>
    {/if}
  </div>
</main>

<style>
  .enrolpage { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
  .box { width: min(480px, 100%); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 28px; display: flex; flex-direction: column; gap: 12px; }
  .word { font-size: 30px; font-weight: 600; letter-spacing: -.02em; }
  p { margin: 0; }
  .small { font-size: 12px; }
  form { display: flex; flex-direction: column; gap: 6px; }
  .go { justify-content: center; padding: 10px; font-size: 13px; margin-top: 8px; }
  @media (max-width: 420px) { .box { padding: 20px 16px; } }
</style>
