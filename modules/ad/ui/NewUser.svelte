<script>
  // New AD user in the users OU. The connector generates the start password (shown once, to the owner) unless the owner
  // types one; an admin's request goes to the owner for approval and the password then only reaches the owner.
  import Icon from '$lab/Icon.svelte';
  import { act } from '$lab/sdk.js';
  import { authentikLoaded, akSource, ouName } from './ad.js';
  let { data, ctx, onclose } = $props();

  let nu = $state({ sam: '', given: '', sn: '', mail: '', description: '', groups: [], mustChange: true, enabled: true, password: '' });
  let result = $state(null);
  const v = $derived(ctx.can('POST', '/api/users'));
  const managedGroups = $derived(data.groups.filter((g) => g.managed));
  const samOk = $derived(/^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$/.test(nu.sam.trim()));
  const taken = $derived(data.users.some((u) => u.sam.toLowerCase() === nu.sam.trim().toLowerCase()));
  // username_link: an Authentik user with this username gets LINKED to the new AD account on the next sync
  const akTwin = $derived(nu.sam.trim() ? (ctx.peer('authentik')?.users || []).find((x) => x.username.toLowerCase() === nu.sam.trim().toLowerCase()) : null);

  async function create(e) {
    e.preventDefault();
    if (akTwin && !confirm(`Authentik already has a user "${akTwin.username}". The next LDAP sync LINKS it to this AD account, and the first sync after linking WIPES their Authentik password (they must then log in with the AD password). Create anyway?`)) return;
    const body = { sam: nu.sam.trim(), given: nu.given.trim(), sn: nu.sn.trim(), mail: nu.mail.trim(), description: nu.description.trim(),
      groups: nu.groups, mustChange: nu.mustChange, enabled: nu.enabled };
    if (v === 'yes' && nu.password) body.password = nu.password;  // never put a password into an approval request
    const r = await act(ctx, { path: '/api/users', body, label: `create AD user ${body.sam}` });
    if (!r) return;
    result = v === 'yes' ? { ...r, sam: body.sam } : { asked: true, sam: body.sam };
    nu = { sam: '', given: '', sn: '', mail: '', description: '', groups: [], mustChange: true, enabled: true, password: '' };
  }
</script>

<form class="new" onsubmit={create}>
  <input class="field mono" placeholder="sAMAccountName" bind:value={nu.sam} required aria-label="Username" maxlength="20" autocomplete="off" />
  <input class="field" placeholder="first name" bind:value={nu.given} aria-label="First name" />
  <input class="field" placeholder="last name" bind:value={nu.sn} aria-label="Last name" />
  <input class="field mono" type="email" placeholder="mail (optional)" bind:value={nu.mail} aria-label="Mail" />
  <input class="field" placeholder="description (optional)" bind:value={nu.description} aria-label="Description" />
  {#if v === 'yes'}<input class="field mono" type="password" placeholder="password (empty = generate)" bind:value={nu.password} aria-label="Start password" autocomplete="new-password" />{/if}
  <div class="opts mono">
    <label><input type="checkbox" bind:checked={nu.mustChange} /> must change at next logon</label>
    <label><input type="checkbox" bind:checked={nu.enabled} /> enabled</label>
    {#each managedGroups as g}<label><input type="checkbox" value={g.name} bind:group={nu.groups} /> {g.name}</label>{/each}
  </div>
  <button class="btn primary" disabled={!samOk || taken}><Icon name={v === 'ask' ? 'lock' : 'user'} size={13} />{v === 'ask' ? 'ask owner' : `create in ${ouName(data.usersOu)}`}</button>
  <button type="button" class="btn" onclick={onclose}>cancel</button>
  {#if nu.sam && !samOk}<span class="mono bad msg">1–20 characters: letters, digits, . _ - (no spaces)</span>{/if}
  {#if taken}<span class="mono bad msg">{nu.sam} already exists in AD</span>{/if}
  {#if akTwin}
    <span class="mono warn msg">▲ Authentik already has “{akTwin.username}”: the LDAP source (username_link) will LINK it to this AD account on the next sync,
      and the first sync after linking wipes their Authentik password — they then log in with the AD password only. Tell them first, or pick another name.</span>
  {/if}
  <span class="mono dim msg">The account shows up in Authentik (as a new user with no groups) after the next LDAP sync{akSource(ctx) ? ` of source ${akSource(ctx)}` : ''} — not immediately.
    {nu.mustChange ? 'With "must change" on, AD refuses the start password for Authentik logins until it is changed on a Windows machine — turn it off for Authentik-only users.' : ''}
    {authentikLoaded(ctx) ? '' : '(Authentik data not loaded in lab — name clashes are not checked.)'}</span>
</form>

{#if result}
  <div class="res">
    {#if result.asked}
      <span class="mono">asked the owner to create {result.sam}; the generated start password is shown only to the owner (in the approval result).</span>
    {:else}
      <span class="mono ok">created {result.sam} in {ouName(data.usersOu)}{result.warnings?.length ? ' — ' + result.warnings.join('; ') : ''}</span>
      {#if result.password}
        <label class="mono dim pw">start password (shown once, copy it now)
          <input class="field mono" readonly value={result.password} aria-label="Start password" onfocus={(e) => e.currentTarget.select()} /></label>
      {/if}
    {/if}
    <button class="btn" onclick={() => (result = null)}>done</button>
  </div>
{/if}

<style>
  .new { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 20px; border-bottom: 1px solid var(--line); align-items: center; }
  .new .field { max-width: 200px; padding: 6px 10px; font-size: 12.5px; }
  .opts { display: flex; flex-wrap: wrap; gap: 4px 14px; width: 100%; font-size: 11.5px; color: var(--dim); }
  .msg { font-size: 11px; width: 100%; line-height: 1.5; }
  .bad { color: var(--bad); }
  .warn { color: var(--warn); }
  .res { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); font-size: 12px; }
  .pw { display: flex; flex-direction: column; gap: 4px; font-size: 11px; flex: 1; min-width: 220px; }
</style>
