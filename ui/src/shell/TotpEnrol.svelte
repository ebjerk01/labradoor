<script>
  // 2FA enrolment: a fresh secret as a QR code + text, and the first code from the app (the caller sends both; the
  // gateway checks the code before it stores anything). Used by the first-run page, Settings → account and the
  // "enrol first" screen.
  import { lab } from '$lab/lab.svelte.js';
  import { newSecret, otpauth, groupSecret } from '$lab/login.js';
  import { qr, qrPath } from '$lab/qr.js';

  let { username = '', secret = $bindable(''), code = $bindable('') } = $props();
  if (!secret) secret = newSecret();
  const uri = $derived(otpauth(secret, username || 'me', lab.brand));
  const code_ = $derived(qr(uri));
  let copied = $state(false);
  async function copy() {
    try { await navigator.clipboard.writeText(secret); copied = true; setTimeout(() => (copied = false), 1500); } catch { /* no clipboard */ }
  }
</script>

<div class="enrol">
  <!-- QR codes scan dark-on-light in every reader: fixed black on white, in both themes -->
  <svg class="qr" viewBox="0 0 {code_.size + 8} {code_.size + 8}" role="img" aria-label="QR code for your authenticator app" shape-rendering="crispEdges">
    <rect width="100%" height="100%" fill="#fff" /><path d={qrPath(code_)} fill="#000" />
  </svg>
  <div class="txt">
    <span class="cap">1 · scan with an authenticator app</span>
    <span class="mono dim small">or type the key: <span class="mono key">{groupSecret(secret)}</span>
      <button type="button" class="lnk mono small" onclick={copy}>{copied ? 'copied ✓' : 'copy'}</button></span>
    <a class="mono small" href={uri}>open in the app on this device</a>
    <label class="cap" for="totp-code">2 · the 6-digit code it shows</label>
    <input id="totp-code" class="field mono code" bind:value={code} inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000000" />
  </div>
</div>

<style>
  .enrol { display: flex; gap: 14px; flex-wrap: wrap; align-items: flex-start; }
  .qr { width: 164px; height: 164px; flex: none; border-radius: 4px; }
  .txt { flex: 1 1 180px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .small { font-size: 11.5px; }
  .key { color: var(--ink); word-break: break-all; }
  .code { letter-spacing: .3em; font-size: 16px; max-width: 160px; }
</style>
