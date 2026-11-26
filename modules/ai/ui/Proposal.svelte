<script>
  // A proposed change: shown, never run by the assistant. "run" runs it from THIS browser through the target
  // module's normal route (verdict, owner approval, audit); "dismiss" just says no.
  import Icon from '$lab/Icon.svelte';
  import { runProposal, dismissProposal } from './state.svelte.js';
  let { p, ctx, after } = $props();
  let busy = $state(false);
  const verdict = $derived(ctx.via(p.module)?.can(p.method, p.path) ?? 'no');
  const mine = $derived(p.owner === ctx.me?.username || ctx.role === 'owner');
  const ST = { pending: ['○', 'var(--sig)'], ran: ['●', 'var(--ok)'], failed: ['■', 'var(--bad)'], asked: ['▲', 'var(--warn)'],
    dismissed: ['○', 'var(--faint)'], expired: ['○', 'var(--faint)'] };
  const st = $derived(ST[p.status] || ST.pending);
  async function go(fn) {
    busy = true;
    try { await fn(p, after); } finally { busy = false; }
  }
</script>

<div class="card" class:done={p.status !== 'pending'}>
  <div class="top">
    <span class="mono g" style:color={st[1]}>{st[0]}</span>
    <span class="lbl">{p.label}</span>
    <span class="mono dim st">#{p.id} · {p.status}{p.code ? ` · ${p.code}` : ''}</span>
  </div>
  <div class="mono req"><span class="sig">{p.method}</span> {p.module} {p.path}{p.query ? `?${p.query}` : ''}</div>
  {#if p.body != null}<pre class="mono body">{JSON.stringify(p.body)}</pre>{/if}
  {#if p.why}<div class="why">{p.why}</div>{/if}
  {#if p.status === 'pending' && mine}
    <div class="acts">
      <button class="btn primary" disabled={busy || verdict === 'no'} onclick={() => go(runProposal)}
        title={verdict === 'ask' ? 'owner-only: sends an approval request' : 'runs once, as you, through lab'}>
        <Icon name={verdict === 'ask' ? 'lock' : 'play'} size={12} />{verdict === 'ask' ? 'ask owner' : 'run'}
      </button>
      <button class="btn" disabled={busy} onclick={() => go(dismissProposal)}><Icon name="close" size={12} />dismiss</button>
      {#if verdict === 'no'}<span class="mono dim">not allowed for you</span>{/if}
      {#if busy}<span class="mono spin dim"></span>{/if}
    </div>
  {/if}
</div>

<style>
  .card { border: 1px solid var(--sig); border-radius: 4px; padding: 8px 10px; display: flex; flex-direction: column; gap: 5px; background: var(--panel); }
  .card.done { border-color: var(--line); }
  .top { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .g { font-size: 11px; }
  .lbl { font-size: 13px; font-weight: 500; flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .st { font-size: 10.5px; white-space: nowrap; }
  .req { font-size: 11.5px; overflow-wrap: anywhere; color: var(--dim); }
  .body { margin: 0; font-size: 11px; background: var(--bg); border: 1px solid var(--line); border-radius: 3px; padding: 4px 7px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .why { font-size: 12px; color: var(--dim); }
  .acts { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
</style>
