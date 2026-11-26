<script>
  // Accounts: list; create, disable/enable sign-in, set password, delete — all owner-only (admin → ask owner, and an
  // approved request never carries a password). Protected accounts (admin, any non-User role) show no buttons.
  import { untrack } from 'svelte';
  import Table from '$lab/Table.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import Icon from '$lab/Icon.svelte';
  import { act, bytes, rel } from '$lab/sdk.js';
  import { secs } from './sw.js';
  let { data, ctx } = $props();
  let q = $state('');
  let creating = $state(false);
  let nu = $state({ name: '', domain: untrack(() => data.domains[0]?.id) || '', description: '', password: '', disabled: false });
  let pwFor = $state(null);
  let pw = $state('');
  let shown = $state(false);
  const rows = $derived(data.accounts.filter((a) => !q || `${a.email} ${a.description}`.toLowerCase().includes(q.toLowerCase())));
  const sel = $derived(pwFor ? data.accounts.find((a) => a.id === pwFor) : null);
  const canCreate = $derived(ctx.can('POST', '/api/accounts'));

  function generate() {
    const abc = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    const v = crypto.getRandomValues(new Uint32Array(20));
    shown = true;
    return Array.from(v, (n) => abc[n % abc.length]).join('');
  }
  async function create(e) {
    e.preventDefault();
    const body = { name: nu.name.trim().toLowerCase(), domain: nu.domain, description: nu.description.trim(), disabled: nu.disabled };
    if (nu.password && canCreate === 'yes') body.password = nu.password;   // an approval request never carries one
    const r = await act(ctx, { path: '/api/accounts', body, label: `create mail account ${body.name}` });
    if (r) { nu = { name: '', domain: nu.domain, description: '', password: '', disabled: false }; creating = false; shown = false; }
  }
  async function setPw(e) {
    e.preventDefault();
    const r = await act(ctx, { path: `/api/accounts/${sel.id}/password`, body: { password: pw }, label: `set password of ${sel.email}` });
    if (r) { pw = ''; pwFor = null; shown = false; }
  }
</script>

<div class="tools">
  <input class="field mono" placeholder="$ grep …" bind:value={q} aria-label="Filter accounts" />
  {#if canCreate !== 'no'}<button class="btn primary" onclick={() => (creating = !creating)}><Icon name="user" size={13} />create account</button>{/if}
  <span class="mono dim s">disable = sign-in off (mail is still received); passwords go straight to Stalwart and are never shown again</span>
</div>
{#if creating}
  <form class="new" onsubmit={create}>
    <input class="field mono" placeholder="name" bind:value={nu.name} required pattern="[a-z0-9][a-z0-9._\-]*" aria-label="Local part" />
    <select class="field" bind:value={nu.domain} aria-label="Domain">
      {#each data.domains as x (x.id)}<option value={x.id}>@{x.name}</option>{/each}
    </select>
    <input class="field" placeholder="description" bind:value={nu.description} aria-label="Description" />
    {#if canCreate === 'yes'}
      <input class="field mono" type={shown ? 'text' : 'password'} autocomplete="new-password" placeholder="password (optional, ≥ 12)" minlength="12" bind:value={nu.password} aria-label="Password" />
      <button type="button" class="btn" onclick={() => (nu.password = generate())}>generate</button>
    {:else}
      <span class="mono dim s">the owner sets the password after approving</span>
    {/if}
    <label class="mono s"><input type="checkbox" bind:checked={nu.disabled} /> sign-in disabled</label>
    <button class="btn primary">{canCreate === 'ask' ? 'ask owner' : 'create'}</button>
  </form>
{/if}

<Table rows={rows} key="id" label="mail accounts" status={(a) => (a.disabled ? 'off' : 'ok')} muted={(a) => a.disabled} empty="no accounts match"
  columns={[
    { key: 'email', label: 'account', render: nameCell, get: (a) => a.email },
    { key: 'role', label: 'role', dim: true, phone: false },
    { key: 'used', label: 'stored', align: 'right', desc: true, format: (v) => bytes(v), phone: false },
    { key: 'created', label: 'created', get: (a) => secs(a.created) || 0, format: (v) => rel(v, ctx.now), dim: true, phone: false },
    { key: 'actions', label: '', sort: false, render: actCell },
  ]} />
{#snippet nameCell(a)}<span class="mono">{a.email}</span> <span class="dim">{a.description}</span>{#if a.protected}<span class="chip mono" title="protected: not changeable from lab">protected</span>{/if}{#if a.disabled}<span class="chip mono">disabled</span>{/if}{/snippet}
{#snippet actCell(a)}
  {#if !a.protected}
    <span class="acts">
      {#if a.disabled}
        <ActionButton {ctx} path={`/api/accounts/${a.id}/enable`} label={`enable ${a.email}`} icon="play" small>enable</ActionButton>
      {:else}
        <ActionButton {ctx} path={`/api/accounts/${a.id}/disable`} label={`disable ${a.email}`} icon="close" confirm="disable sign-in? click again" small>disable</ActionButton>
      {/if}
      {#if ctx.can('POST', `/api/accounts/${a.id}/password`) === 'yes'}
        <button class="btn sm" onclick={() => { pwFor = pwFor === a.id ? null : a.id; pw = ''; shown = false; }}>password</button>
      {/if}
      <ActionButton {ctx} method="DELETE" path={`/api/accounts/${a.id}`} label={`delete ${a.email}`} icon="close" confirm="delete account AND its mail? click again" small>delete</ActionButton>
    </span>
  {/if}
{/snippet}
{#if sel}
  <form class="new" onsubmit={setPw}>
    <span class="mono s">new password for {sel.email}</span>
    <input class="field mono" type={shown ? 'text' : 'password'} autocomplete="new-password" minlength="12" required bind:value={pw} aria-label="New password" />
    <button type="button" class="btn" onclick={() => (pw = generate())}>generate</button>
    <button class="btn primary">set password</button>
    <button type="button" class="btn" onclick={() => { pwFor = null; pw = ''; }}>cancel</button>
  </form>
{/if}

<style>
  .tools, .new { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .new { border: 1px solid var(--line); border-radius: 4px; padding: 10px; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 12px; }
  .s { font-size: 11px; }
  .acts { display: inline-flex; gap: 4px; flex-wrap: wrap; }
  .chip { font-size: 10px; border: 1px solid var(--line); border-radius: 3px; padding: 0 4px; margin-left: 6px; color: var(--dim); }
</style>
