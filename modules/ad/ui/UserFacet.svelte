<script>
  // An AD user: account state, password/expiry, lockout, groups, the Authentik twin, and (owner) changes.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import Icon from '$lab/Icon.svelte';
  import { act, ago } from '$lab/sdk.js';
  import { UP, enc, pwState, expiryDays, authentikUser, authentikLoaded, ouPath, ouName, lockIcon, akSource } from './ad.js';
  let { object, data, ctx } = $props();

  const u = $derived(data.users.find((x) => `aduser:${x.sam}` === object.id));
  const days = $derived(expiryDays(ctx));
  const p = $derived(u ? pwState(u, days) : null);
  const ak = $derived(u ? authentikUser(u, ctx) : null);
  const mine = $derived(new Set((u?.groups || []).map((g) => g.dn.toLowerCase())));
  const addable = $derived(data.groups.filter((g) => g.managed && !mine.has(g.dn.toLowerCase())));
  const can = (m, path) => ctx.can(m, path);

  let addGroup = $state('');
  let pw = $state('');
  let mustChange = $state(null);   // null = default (on, unless an Authentik user uses this account)
  const must = $derived(mustChange ?? !ak);
  let shown = $state(null);
  let edit = $state(null);
  let del = $state('');

  async function reset() {
    const yes = can('POST', `${UP(u.sam)}/password`) === 'yes';
    if (ak && !confirm(`${u.sam} is used by Authentik user "${ak.username}". A reset makes AD's password newer than Authentik's: on the next LDAP sync Authentik marks their own password unusable and they must log in with this AD password${must ? ' — and with "must change" on, AD refuses it for Authentik logins until it is changed on a Windows machine' : ''}. Continue?`)) return;
    const body = { mustChange: must };
    if (yes && pw) body.password = pw;  // typed passwords only on the owner's direct call, never into an approval
    const r = await act(ctx, { path: `${UP(u.sam)}/password`, body, label: `reset AD password of ${u.sam}` });
    if (!r) return;
    pw = '';
    shown = yes ? (r.password || null) : null;
    if (!yes) ctx.notify('the generated password goes to the owner with the approval result');
  }
  async function saveEdit(e) {
    e.preventDefault();
    const body = {};
    for (const [k, was] of [['displayName', u.name], ['givenName', u.given], ['sn', u.sn], ['mail', u.mail], ['description', u.description]]) {
      if ((edit[k] ?? '') !== (was ?? '')) body[k] = edit[k] ?? '';
    }
    if (!Object.keys(body).length) { edit = null; return; }
    if (await act(ctx, { method: 'PATCH', path: UP(u.sam), body, label: `edit AD user ${u.sam}` })) edit = null;
  }
  async function remove() {
    if (del !== u.sam) return;
    if (!confirm(`Delete AD user ${u.sam} for good? (AD recycle bin is not enabled.)${ak ? ` Authentik keeps its user "${ak.username}" but AD logins stop.` : ''}`)) return;
    const r = await act(ctx, { method: 'DELETE', path: UP(u.sam), query: { confirm: u.sam }, label: `delete AD user ${u.sam}` });
    if (r) del = '';
  }
</script>

{#if u}
  <Section title="account" src="active directory">
    <Stats items={[
      { n: 'account', v: !u.enabled ? 'off' : u.locked ? 'locked' : 'on', s: !u.enabled ? 'off' : u.locked ? 'bad' : 'ok' },
      { n: 'password', v: p.t.replace('expires in ', ''), s: p.s },
      { n: 'last logon', v: u.lastLogon ? ago(u.lastLogon, ctx.now) : 'never' },
      { n: 'bad pw', v: u.badPwdCount, s: u.badPwdCount ? 'warn' : null },
    ]} />
    <span class="mono dim s">{u.sam} · {u.upn || 'no UPN'} · {u.mail || 'no mail'} · {ouPath(u.ou, data.base)}{u.description ? ' · ' + u.description : ''}</span>
    <Lines items={[
      { p: '●', t: `password set ${u.pwdLastSet ? ago(u.pwdLastSet, ctx.now) + ' ago' : u.mustChange ? '— must change at next logon' : 'never'}${u.pwdNeverExpires ? ' · never expires' : u.pwdExpires ? ' · expires ' + new Date(u.pwdExpires * 1000).toLocaleDateString('nb-NO') : ''}`, s: p.s },
      ...(u.locked ? [{ p: '■', s: 'bad', t: `locked out ${u.lockoutTime ? ago(u.lockoutTime, ctx.now) + ' ago' : ''} · ${u.badPwdCount} bad passwords` }] : []),
      ...(u.badPasswordTime ? [{ p: '▲', s: u.locked ? 'bad' : null, c: 'var(--dim)', t: `last bad password ${ago(u.badPasswordTime, ctx.now)} ago` }] : []),
      { p: '·', c: 'var(--dim)', t: `created ${u.created ? ago(u.created, ctx.now) + ' ago' : '–'} · changed ${u.changed ? ago(u.changed, ctx.now) + ' ago' : '–'} · ${u.logonCount} logons` },
      ...(u.protected ? [{ p: '▲', s: 'warn', t: 'adminCount=1: protected by AdminSDHolder (privileged group member)' }] : []),
      ...(!u.managed ? [{ p: '○', c: 'var(--dim)', t: `outside ${ouName(data.usersOu)}: read-only in lab (${data.bind} is delegated on ${ouName(data.usersOu)} only)` }] : []),
    ]} />
  </Section>

  <Section title="authentik" src={akSource(ctx) ? `authentik · ldap source ${akSource(ctx)}` : 'authentik'}>
    {#if ak}
      <div class="row">
        <button class="btn" onclick={() => ctx.open(ak.id)}><Icon name="shield" size={13} />{ak.username}</button>
        <span class="mono dim s">{ak.linked ? 'synced from AD — password changes in Authentik are written back to AD' : 'same username, not linked yet: the next sync links them (username_link)'}</span>
      </div>
      <span class="mono warn s">▲ an AD password reset here makes Authentik drop {ak.username}'s own password on the next sync — they then log in with the AD password.</span>
    {:else if !u.managed}
      <span class="mono dim s">not in {ouName(data.usersOu)}: Authentik doesn't sync this account.</span>
    {:else if authentikLoaded(ctx)}
      <span class="mono dim s">no Authentik user yet — it appears after the next LDAP sync{akSource(ctx) ? ` of ${akSource(ctx)}` : ''}.</span>
    {:else}
      <span class="mono dim s">Authentik data not loaded in lab.</span>
    {/if}
  </Section>

  <Section title="groups · {u.groups.length}" src="active directory">
    <div class="chips">
      {#if u.primaryGroup}<span class="chip mono dim" title="primary group (not in memberOf)">{u.primaryGroup}</span>{/if}
      {#each u.groups as g (g.dn)}
        {@const managed = data.groups.find((x) => x.dn.toLowerCase() === g.dn.toLowerCase())?.managed}
        <span class="chip mono"><button class="lnk" onclick={() => ctx.open(`adgroup:${g.name}`)}>{g.name}</button>
          {#if managed && u.managed && can('DELETE', `${UP(u.sam)}/groups/${enc(g.name)}`) !== 'no'}
            <button class="x" aria-label="Remove {u.sam} from {g.name}" title={can('DELETE', `${UP(u.sam)}/groups/${enc(g.name)}`) === 'ask' ? 'ask owner' : 'remove'}
              onclick={() => act(ctx, { method: 'DELETE', path: `${UP(u.sam)}/groups/${enc(g.name)}`, label: `remove ${u.sam} from AD group ${g.name}` })}>×</button>
          {/if}
        </span>
      {/each}
    </div>
    {#if u.managed && addable.length && can('POST', `${UP(u.sam)}/groups/x`) !== 'no'}
      <div class="row">
        <select class="field mono" bind:value={addGroup} aria-label="Add to group">
          <option value="">+ add to group…</option>
          {#each addable as g}<option value={g.name}>{g.name}</option>{/each}
        </select>
        <button class="btn" disabled={!addGroup} onclick={async () => { if (await act(ctx, { path: `${UP(u.sam)}/groups/${enc(addGroup)}`, label: `add ${u.sam} to AD group ${addGroup}` })) addGroup = ''; }}>
          <Icon name={lockIcon(can('POST', `${UP(u.sam)}/groups/x`))} size={13} />{can('POST', `${UP(u.sam)}/groups/x`) === 'ask' ? 'ask' : 'add'}</button>
      </div>
    {/if}
  </Section>

  {#if u.managed && can('POST', `${UP(u.sam)}/password`) !== 'no'}
    <Section title="password" src="active directory">
      <div class="row">
        {#if can('POST', `${UP(u.sam)}/password`) === 'yes'}
          <input class="field mono" type="password" placeholder="new password (empty = generate)" bind:value={pw} aria-label="New password" autocomplete="new-password" />
        {/if}
        <label class="mono dim ck"><input type="checkbox" checked={must} onchange={(e) => (mustChange = e.currentTarget.checked)} /> must change</label>
        <button class="btn" onclick={reset}><Icon name={can('POST', `${UP(u.sam)}/password`) === 'ask' ? 'lock' : 'key'} size={13} />{can('POST', `${UP(u.sam)}/password`) === 'ask' ? 'ask owner' : 'reset'}</button>
      </div>
      {#if shown}
        <label class="mono dim s">new password (shown once — copy it now)
          <input class="field mono" readonly value={shown} aria-label="Generated password" onfocus={(e) => e.currentTarget.select()} /></label>
        <button class="btn" onclick={() => (shown = null)}>hide</button>
      {/if}
      <span class="mono dim s">also clears a lockout. Policy: {data.policy.minPwdLength}+ chars{data.policy.complexity ? ', 3 of upper/lower/digit/symbol, not containing the username' : ''}, last {data.policy.history} remembered.{ak ? '' : ' Turn "must change" off for accounts used only through Authentik: AD refuses a must-change password for LDAP logins.'}</span>
    </Section>
  {/if}

  {#if u.managed && can('PATCH', UP(u.sam)) !== 'no'}
    <Section title="details" src="active directory">
      {#if edit}
        <form class="ed" onsubmit={saveEdit}>
          <input class="field" placeholder="display name" bind:value={edit.displayName} aria-label="Display name" />
          <input class="field" placeholder="first name" bind:value={edit.givenName} aria-label="First name" />
          <input class="field" placeholder="last name" bind:value={edit.sn} aria-label="Last name" />
          <input class="field mono" type="email" placeholder="mail" bind:value={edit.mail} aria-label="Mail" />
          <input class="field" placeholder="description" bind:value={edit.description} aria-label="Description" />
          <div class="row"><button class="btn primary">{can('PATCH', UP(u.sam)) === 'ask' ? 'ask owner' : 'save'}</button><button type="button" class="btn" onclick={() => (edit = null)}>cancel</button></div>
        </form>
      {:else}
        <button class="btn" onclick={() => (edit = { displayName: u.name, givenName: u.given, sn: u.sn, mail: u.mail, description: u.description })}><Icon name="wrench" size={13} />edit name / mail / description</button>
      {/if}
    </Section>
  {/if}

  {#if u.managed && !u.undeletable && can('DELETE', UP(u.sam)) !== 'no'}
    <Section title="delete" src="active directory">
      <div class="row">
        <input class="field mono" placeholder="type {u.sam} to confirm" bind:value={del} aria-label="Confirm username" autocomplete="off" />
        <button class="btn danger" disabled={del !== u.sam} onclick={remove}><Icon name={can('DELETE', UP(u.sam)) === 'ask' ? 'lock' : 'close'} size={13} />{can('DELETE', UP(u.sam)) === 'ask' ? 'ask owner' : 'delete'}</button>
      </div>
    </Section>
  {/if}
{/if}

<style>
  .s { font-size: 11px; line-height: 1.5; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; padding: 2px 4px 2px 8px; border: 1px solid var(--line); border-radius: 3px; }
  .x { border: none; background: transparent; color: var(--dim); padding: 0 4px; font-size: 13px; line-height: 1; }
  .x:hover { color: var(--bad); }
  .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .row .field { flex: 1; min-width: 120px; padding: 5px 8px; font-size: 12px; }
  .ck { font-size: 11px; display: flex; gap: 4px; align-items: center; }
  .ed { display: flex; flex-direction: column; gap: 6px; }
  .ed .field { padding: 5px 8px; font-size: 12px; }
  label.s { display: flex; flex-direction: column; gap: 4px; }
  .warn { color: var(--warn); }
  .danger:hover:not(:disabled) { border-color: var(--bad); color: var(--bad); }
</style>
