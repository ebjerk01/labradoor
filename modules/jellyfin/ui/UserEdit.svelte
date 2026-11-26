<script>
  // Edit one Jellyfin user. Every write is an owner-only route: the owner applies it, an admin's click asks the owner.
  import Icon from '$lab/Icon.svelte';
  import { setPolicy, setPassword, removeUser, mbit } from './jf.js';
  import { lazy } from '$lab/sdk.js';
  let { u, libs = [], ctx } = $props();
  const ratings = lazy(() => ctx, () => '/Localization/ParentalRatings');
  // one entry per age (Jellyfin lists every country's names for the same value)
  const ages = $derived([...new Map((ratings.data || []).filter((r) => r.Value != null).map((r) => [r.Value, r.Name])).entries()].sort((a, b) => a[0] - b[0]));
  const verdict = $derived(ctx.can('POST', `/Users/${u.id}/Policy`));
  const ro = $derived(verdict === 'no');
  let all = $state(true);
  let picked = $state([]);
  let sessions = $state(0);
  let rating = $state('');
  let rate = $state(0);
  let remote = $state(true);
  let lockout = $state(-1);
  let pw = $state('');
  let lastId = null;
  $effect.pre(() => {
    if (u.id !== lastId) {  // reset the form when another user is shown; keep edits across refreshes
      lastId = u.id;
      all = u.allFolders;
      picked = libs.filter((l) => u.folderIds.some((f) => f.replace(/-/g, '') === l.id.replace(/-/g, ''))).map((l) => l.id);
      sessions = u.maxSessions;
      rating = u.rating ?? '';
      rate = u.bitrate / 1e6;
      remote = u.remote;
      lockout = u.lockout ?? -1;
      pw = '';
    }
  });
  const dirty = $derived(all !== u.allFolders || sessions !== u.maxSessions || String(rating) !== String(u.rating ?? '') || Math.round((Number(rate) || 0) * 1e6) !== u.bitrate
    || remote !== u.remote || Number(lockout) !== (u.lockout ?? -1)
    || (!all && [...picked].sort().join() !== libs.filter((l) => u.folderIds.some((f) => f.replace(/-/g, '') === l.id.replace(/-/g, ''))).map((l) => l.id).sort().join()));

  const saveAccess = () => setPolicy(ctx, u, { EnableAllFolders: all, EnabledFolders: all ? [] : picked, MaxActiveSessions: Number(sessions) || 0,
    MaxParentalRating: rating === '' ? null : Number(rating), RemoteClientBitrateLimit: Math.round((Number(rate) || 0) * 1e6), EnableRemoteAccess: remote,
    LoginAttemptsBeforeLockout: Number(lockout) }, 'access + limits');
  async function savePw(e) {
    e.preventDefault();
    if (pw.length < 8) return ctx.notify('at least 8 characters', 'bad');
    if (await setPassword(ctx, u, pw)) pw = '';
  }
</script>

<div class="ed">
  <div class="row1">
    <button class="btn" disabled={ro} onclick={() => setPolicy(ctx, u, { IsDisabled: !u.disabled }, u.disabled ? 'enable' : 'disable', u.disabled ? null : `Disable ${u.name}? They are signed out everywhere.`)}>
      <Icon name={verdict === 'ask' ? 'lock' : 'user'} size={12} />{u.disabled ? 'enable' : 'disable'}
    </button>
    <button class="btn" disabled={ro} onclick={() => setPolicy(ctx, u, { IsAdministrator: !u.admin }, u.admin ? 'remove admin' : 'make admin', u.admin ? null : `Make ${u.name} a Jellyfin administrator (full server control)?`)}>
      <Icon name={verdict === 'ask' ? 'lock' : 'shield'} size={12} />{u.admin ? 'remove admin' : 'make admin'}
    </button>
    <button class="btn danger" disabled={ro} onclick={() => removeUser(ctx, u)}><Icon name={verdict === 'ask' ? 'lock' : 'close'} size={12} />delete</button>
  </div>
  <fieldset disabled={ro}>
    <legend class="cap">libraries + limits</legend>
    <label class="mono"><input type="checkbox" bind:checked={all} /> all libraries (also future ones)</label>
    {#if !all}
      {#each libs as l (l.id)}<label class="mono"><input type="checkbox" value={l.id} bind:group={picked} /> {l.name}</label>{/each}
    {/if}
    <label class="mono">max sessions <input class="field n" type="number" min="0" max="20" bind:value={sessions} aria-label="Max active sessions" /> <span class="dim">0 = no limit</span></label>
    <label class="mono">max rating
      <select class="field" bind:value={rating} aria-label="Max parental rating">
        <option value="">no limit</option>
        {#each ages as [v, n] (v)}<option value={v}>{v}+ ({n})</option>{/each}
      </select>
    </label>
    <label class="mono"><input type="checkbox" bind:checked={remote} /> remote access (outside the LAN)</label>
    <label class="mono">remote bitrate <input class="field n" type="number" min="0" max="400" step="0.5" bind:value={rate} aria-label="Remote bitrate limit in Mbit/s" /> <span class="dim">Mbit/s · 0 = {mbit(0)}</span></label>
    <label class="mono">lock after <input class="field n" type="number" min="-1" max="100" bind:value={lockout} aria-label="Failed logins before lockout" /> <span class="dim">failed logins · -1 default · 0 never</span></label>
    <button class="btn" class:primary={dirty} disabled={!dirty} onclick={saveAccess}>{verdict === 'ask' ? 'ask owner to apply' : 'apply'}</button>
  </fieldset>
  {#if ctx.can('POST', '/Users/Password') === 'yes'}
    <form class="pw" onsubmit={savePw}>
      <input class="field mono" type="password" autocomplete="new-password" placeholder="new password" bind:value={pw} aria-label="New password for {u.name}" />
      <button class="btn" disabled={!pw}>set password</button>
    </form>
  {:else if !ro}
    <!-- an approval stores its body in lab's DB until the owner acts: never put a password there -->
    <span class="mono dim s">passwords: owner only (never through the approval queue)</span>
  {/if}
  {#if verdict === 'ask'}<span class="mono dim s">identity: each change asks owner once</span>{/if}
</div>

<style>
  .ed { display: flex; flex-direction: column; gap: 10px; }
  .row1 { display: flex; flex-wrap: wrap; gap: 6px; }
  fieldset { border: 1px solid var(--line); border-radius: 4px; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; margin: 0; }
  legend { padding: 0 4px; }
  label { font-size: 11.5px; display: flex; align-items: center; gap: 6px; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font-size: 12px; }
  .n { width: 60px; }
  fieldset .btn { align-self: flex-start; margin-top: 4px; }
  .pw { display: flex; gap: 6px; }
  .pw .field { flex: 1; }
  .danger:not(:disabled) { color: var(--bad); border-color: var(--bad); }
  .s { font-size: 10.5px; }
</style>
