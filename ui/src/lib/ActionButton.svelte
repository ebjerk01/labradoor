<script>
  // A button for one of the module's routes, with the manifest's verdict built in: hidden when the user may not call
  // it, a lock + "ask owner" when it needs the owner's approval, a spinner while it runs. confirm: the first click
  // arms it ("restart?"), a second click within 4 s runs it. Runs through act() (docs/sdk.md); body may be a function
  // (read at click time).
  import Icon from './Icon.svelte';
  import { act } from './sdk-core.js';

  let { ctx, method = 'POST', path, body = undefined, query = undefined, label, confirm = false, ok = undefined,
    done = undefined, check = undefined, quiet = false, reason = '', icon = '', primary = false, small = false, disabled = false,
    showDenied = false, title = '', children } = $props();

  const verdict = $derived(ctx.can(method, path));
  let busy = $state(false);
  let armed = $state(false);
  let timer;

  async function click() {
    if (confirm && !armed) {
      armed = true;
      clearTimeout(timer);
      timer = setTimeout(() => (armed = false), 4000);
      return;
    }
    armed = false;
    clearTimeout(timer);
    busy = true;
    try {
      await act(ctx, { method, path, query, label, ok, done, check, quiet, reason, body: typeof body === 'function' ? body() : body });
    } finally { busy = false; }
  }
</script>

{#if verdict !== 'no' || showDenied}
  <button type="button" class="btn" class:primary class:sm={small} class:armed
    disabled={disabled || busy || verdict === 'no'} aria-busy={busy}
    title={verdict === 'ask' ? `${label}: needs the owner's approval` : verdict === 'no' ? `${label}: not allowed` : title || label}
    onclick={click}>
    {#if busy}<span class="spin"></span>{:else if verdict === 'ask' || verdict === 'no'}<Icon name="lock" size={11} />{:else if icon}<Icon name={icon} size={12} />{/if}
    {#if armed}{typeof confirm === 'string' ? confirm : `${label}?`}{:else if children}{@render children()}{:else}{label}{/if}
    {#if verdict === 'ask' && !armed}<span class="ask">ask owner</span>{/if}
  </button>
{/if}

<style>
  .sm { padding: 3px 8px; font-size: 11px; gap: 4px; }
  .armed { border-color: var(--warn); color: var(--warn); }
  .ask { color: var(--faint); }
  .primary .ask { color: inherit; opacity: .7; }
</style>
