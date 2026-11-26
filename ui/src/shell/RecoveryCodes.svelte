<script>
  // Recovery codes, shown once: each logs in once instead of a 2FA code (lost phone). Copy or download, then continue.
  import { lab } from '$lab/lab.svelte.js';
  let { codes = [], ondone } = $props();
  let saved = $state(false);
  const text = $derived(`${lab.brand} recovery codes (each works once)\n\n${codes.join('\n')}\n`);
  function download() {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    a.download = `${lab.brand}-recovery-codes.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
    saved = true;
  }
  async function copy() { try { await navigator.clipboard.writeText(text); saved = true; } catch { /* no clipboard */ } }
</script>

<div class="rc">
  <span class="cap">~/recovery codes · {codes.length}</span>
  <p class="dim small">Each code logs you in once in place of a 2FA code. Keep them somewhere safe (a password manager): they are not shown again.</p>
  <div class="codes mono">{#each codes as c}<span>{c}</span>{/each}</div>
  <div class="row">
    <button type="button" class="btn" onclick={copy}>copy</button>
    <button type="button" class="btn" onclick={download}>download .txt</button>
    {#if ondone}<button type="button" class="btn primary" onclick={ondone}>{saved ? 'continue' : 'I saved them · continue'}</button>{/if}
  </div>
</div>

<style>
  .rc { display: flex; flex-direction: column; gap: 8px; }
  .small { font-size: 12px; margin: 0; }
  .codes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 16px; padding: 10px 12px; background: var(--q); border-radius: 4px; font-size: 13px; }
  .row { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
