<script>
  // One Proxmox request as a button: hidden when the manifest says no, dashed "· ask" when owner-only for this user,
  // and a second click within 4 s when `confirm` is set (stop, rollback, delete, migrate, resize).
  import Icon from '$lab/Icon.svelte';
  import { pveAct } from './pve.svelte.js';
  let { ctx, path, body = {}, label, text = '', icon = '', confirm = false, method = 'POST', disabled = false, done = null } = $props();

  const v = $derived(ctx.can(method, path));
  let armed = $state(false);
  let busy = $state(false);
  let timer;

  async function go() {
    if (confirm && !armed && v === 'yes') {
      armed = true;
      clearTimeout(timer);
      timer = setTimeout(() => (armed = false), 4000);
      return;
    }
    armed = false;
    busy = true;
    const r = await pveAct(ctx, method, path, typeof body === 'function' ? body() : body, label);
    busy = false;
    if (r && done) done(r);
  }
</script>

{#if v !== 'no'}
  <button class="btn sm" class:ask={v === 'ask'} class:armed disabled={disabled || busy} onclick={go}
    title={v === 'ask' ? 'owner only: asks owner for a one-time approval' : armed ? 'click again to confirm' : label}>
    {#if v === 'ask'}<Icon name="lock" size={11} />{:else if icon}<Icon name={icon} size={11} />{/if}
    {#if busy}<span class="spin"></span>{/if}{armed ? `${text || label}?` : text || label}{#if v === 'ask'}<span class="faint">· ask</span>{/if}
  </button>
{/if}

<style>
  .sm { padding: 2px 7px; font-size: 11px; gap: 4px; }
  .ask { border-style: dashed; border-color: var(--sig); }
  .armed { border-color: var(--warn); color: var(--warn); }
</style>
