<script>
  // ~/directory — Active Directory: users, groups, computers, OUs. Reading: admin. Changes: owner (admin → ask owner).
  // Only users and groups in the connector's managed OUs are changeable (the service account's delegation).
  import Icon from '$lab/Icon.svelte';
  import Table from '$lab/Table.svelte';
  import { ago } from '$lab/sdk.js';
  import { pwState, userStatus, isBuiltin, expiryDays, computerId, authentikUser, authentikLoaded, ouPath, ouName, akSource } from './ad.js';
  import NewUser from './NewUser.svelte';
  let { data, ctx } = $props();

  let tab = $state('users');
  let q = $state('');
  let only = $state('');           // '' | locked | expiring | disabled
  let builtinPick = $state(null);  // the viewer's toggle; until then the owner's module setting
  const builtin = $derived(builtinPick ?? !!ctx.settings.builtin);
  let creating = $state(false);

  const days = $derived(expiryDays(ctx));
  const hit = (s) => !q || s.toLowerCase().includes(q.toLowerCase());
  const users = $derived(data ? data.users.filter((u) => (builtin || !isBuiltin(u, data))
    && hit(`${u.sam} ${u.name} ${u.mail} ${u.description}`)
    && (!only || (only === 'locked' && u.locked) || (only === 'disabled' && !u.enabled)
      || (only === 'expiring' && u.enabled && pwState(u, days).s))) : []);
  const groups = $derived(data ? data.groups.filter((g) => (builtin || g.managed || !isBuiltin(g, data)) && hit(`${g.name} ${g.description}`)) : []);
  const comps = $derived(data ? data.computers.filter((c) => hit(`${c.name} ${c.dns} ${c.os}`)) : []);
  const counts = $derived(data ? {
    locked: data.users.filter((u) => u.locked).length,
    expiring: data.users.filter((u) => u.enabled && pwState(u, days).s).length,
    disabled: data.users.filter((u) => !u.enabled && (builtin || !isBuiltin(u, data))).length,
  } : {});
  const byDn = $derived(data ? Object.fromEntries(data.users.map((u) => [u.dn.toLowerCase(), u])) : {});
  const inOu = (dn) => {
    const l = dn.toLowerCase();
    const direct = (x) => x.ou.toLowerCase() === l;
    return { users: data.users.filter(direct).length, groups: data.groups.filter(direct).length, computers: data.computers.filter(direct).length };
  };
  const pol = $derived(data?.policy || {});
  const compId = (c) => computerId(c, ctx).id;
  const compMerged = (c) => computerId(c, ctx).merged;
  const pwSort = (u) => (u.mustChange ? -1e12 : u.pwdNeverExpires || u.pwdExpires == null ? 1e15 : u.pwdExpires);
</script>

{#if !data}<p class="mono dim pad"><span class="spin"></span> loading active directory</p>{:else}
<div class="dv fade">
  <div class="bar">
    <div class="seg" role="group" aria-label="Section">
      {#each [['users', users.length], ['groups', groups.length], ['computers', comps.length], ['OUs', data.ous.length]] as [t, n]}
        <button aria-pressed={tab === t} onclick={() => (tab = t)}>{t} <span class="faint">{n}</span></button>
      {/each}
    </div>
    <input class="field mono s" placeholder="$ grep …" bind:value={q} aria-label="Search" />
    <label class="mono dim tg"><input type="checkbox" checked={builtin} onchange={(e) => (builtinPick = e.currentTarget.checked)} /> built-in</label>
    <span class="mono dim note">{data.domain} · DC {data.dc} · bound as {data.bind} · {ctx.role === 'owner' ? 'changes apply immediately' : 'changes are owner-only → each one asks the owner'}</span>
    {#if tab === 'users' && ctx.can('POST', '/api/users') !== 'no'}
      <button class="btn primary" onclick={() => (creating = !creating)}><Icon name="user" size={13} />create user</button>
    {/if}
  </div>

  {#if tab === 'users'}
    {#if creating}<NewUser {data} {ctx} onclose={() => (creating = false)} />{/if}
    <div class="filters mono">
      <button class="chip" aria-pressed={only === ''} onclick={() => (only = '')}>all</button>
      <button class="chip bad" aria-pressed={only === 'locked'} onclick={() => (only = only === 'locked' ? '' : 'locked')}>■ locked {counts.locked}</button>
      <button class="chip warn" aria-pressed={only === 'expiring'} onclick={() => (only = only === 'expiring' ? '' : 'expiring')}>▲ password &lt; {days}d / must change {counts.expiring}</button>
      <button class="chip" aria-pressed={only === 'disabled'} onclick={() => (only = only === 'disabled' ? '' : 'disabled')}>○ disabled {counts.disabled}</button>
      <span class="dim pol">policy: max age {pol.maxPwdAge ? Math.round(pol.maxPwdAge / 86400) + 'd' : 'none'} · min {pol.minPwdLength} chars{pol.complexity ? ' + complexity' : ''} · history {pol.history} · lockout {pol.lockoutThreshold ? `after ${pol.lockoutThreshold} bad, ${Math.round((pol.lockoutDuration || 0) / 60)} min` : 'off (threshold 0)'}</span>
    </div>
    <Table rows={users} key="dn" {ctx} object={(u) => `aduser:${u.sam}`} status={(u) => userStatus(u, days)} muted={(u) => !u.enabled} label="AD users" empty="nothing matches"
      columns={[
        { key: 'name', label: 'user', render: userCell },
        { key: 'ou', label: 'ou', dim: true, phone: false, format: (v) => ouPath(v, data.base) },
        { key: 'groups', label: 'groups', sort: false, render: groupCell, phone: false },
        { key: 'pw', label: 'password', get: pwSort, render: pwCell },
        { key: 'lastLogon', label: 'last logon', desc: true, dim: true, format: (v) => (v ? ago(v, ctx.now) : 'never') },
        { key: 'authentik', label: 'authentik', sort: false, render: akCell, phone: false },
      ]} />
    {#snippet userCell(u)}<span class="nm">{u.name}</span> <span class="dim">{u.sam}</span>{#if u.locked}<span class="bad tag">LOCKED</span>{/if}{#if !u.enabled}<span class="dim tag">disabled</span>{/if}{#if u.protected}<span class="warn tag" title="adminCount=1 (AdminSDHolder-protected)">admin</span>{/if}{/snippet}
    {#snippet groupCell(u)}<span class="gs">{#each u.groups.slice(0, 4) as g}<span class="chip">{g.name}</span>{/each}{#if u.groups.length > 4}<span class="dim">+{u.groups.length - 4}</span>{/if}</span>{/snippet}
    {#snippet pwCell(u)}{@const p = pwState(u, days)}<span class:warn={p.s === 'warn'} class:bad={p.s === 'bad'} class:dim={!p.s}>{p.t}</span>{/snippet}
    {#snippet akCell(u)}{@const ak = authentikUser(u, ctx)}{#if ak}<button class="lnk" onclick={(e) => { e.stopPropagation(); ctx.open(ak.id); }} title={ak.linked ? `synced from AD${akSource(ctx) ? ` (LDAP source ${akSource(ctx)})` : ''}` : 'same username, not linked yet'}>{ak.username}{ak.linked ? '' : ' ?'}</button>{:else if u.managed && authentikLoaded(ctx)}<span class="faint">not synced yet</span>{/if}{/snippet}

  {:else if tab === 'groups'}
    <Table rows={groups} key="dn" {ctx} object={(g) => `adgroup:${g.name}`} label="AD groups" empty="no groups match"
      columns={[
        { key: 'name', label: 'group', render: gNameCell },
        { key: 'scope', label: 'scope', dim: true, phone: false, get: (g) => `${g.scope} ${g.kind}` },
        { key: 'members', label: 'members', get: (g) => g.members.length, desc: true, render: memberCell },
        { key: 'ou', label: 'ou', dim: true, phone: false, format: (v) => ouPath(v, data.base) },
        { key: 'changed', label: 'changed', desc: true, dim: true, phone: false, format: (v) => (v ? ago(v, ctx.now) : '–') },
      ]} />
    {#snippet gNameCell(g)}{g.name}{#if g.managed}<span class="sig tag">lab</span>{/if}{#if g.protected}<span class="warn tag">admin</span>{/if}{/snippet}
    {#snippet memberCell(g)}<span class="gs">{#each g.members.slice(0, 6) as m}{@const u = byDn[m.toLowerCase()]}<span class="chip">{u ? u.sam : m.split(',')[0].replace(/^CN=/i, '')}</span>{/each}{#if g.members.length > 6}<span class="dim">+{g.members.length - 6}</span>{/if}</span>{/snippet}

  {:else if tab === 'computers'}
    <Table rows={comps} key="dn" {ctx} onrow={(c) => ctx.open(compId(c))} status={(c) => (c.enabled ? 'ok' : 'off')} muted={(c) => !c.enabled} label="AD computers" empty="no computers"
      columns={[
        { key: 'name', label: 'computer', render: cNameCell },
        { key: 'os', label: 'os', dim: true, phone: false, get: (c) => `${c.os || ''} ${c.osVersion || ''}`.trim() },
        { key: 'ou', label: 'ou', dim: true, phone: false, format: (v) => ouPath(v, data.base) },
        { key: 'lastLogon', label: 'last logon', desc: true, dim: true, format: (v) => (v ? ago(v, ctx.now) : 'never') },
        { key: 'lab', label: 'lab object', dim: true, phone: false, sort: false, get: (c) => (compMerged(c) ? compId(c) : '— (AD only)') },
      ]} />
    {#snippet cNameCell(c)}{c.name}{#if c.dc}<span class="sig tag">DC</span>{/if} <span class="dim">{c.dns}</span>{/snippet}
    <p class="mono dim hint">{ctx.settings.computers_ou ? `new domain joins land in ${ouName(ctx.settings.computers_ou)} (redircmp). ` : ''}{data.bind} only reads computers.</p>

  {:else}
    <div class="scroll-x"><table>
      <thead><tr class="cap"><th>ou / container</th><th>users</th><th>groups</th><th>computers</th><th>lab may change</th></tr></thead>
      <tbody>
        {#each data.ous as o (o.dn)}
          {@const n = inOu(o.dn)}
          {@const depth = o.dn.split(/(?<!\\),/).length - data.base.split(',').length - 1}
          <tr class="row">
            <td class="mono" style:padding-left="{20 + depth * 18}px">{o.container ? 'CN=' : ''}{o.name}{#if o.description}<span class="dim"> · {o.description}</span>{/if}</td>
            <td class="mono dim">{n.users || ''}</td><td class="mono dim">{n.groups || ''}</td><td class="mono dim">{n.computers || ''}</td>
            <td class="mono dim">{o.dn.toLowerCase() === data.usersOu.toLowerCase() ? 'create/delete users, attrs, password, unlock, enable' : o.dn.toLowerCase() === data.groupsOu.toLowerCase() ? 'group membership' : ''}</td>
          </tr>
        {/each}
      </tbody>
    </table></div>
    <p class="mono dim hint">{data.bind} is delegated (dsacls) on {ouName(data.managedOu)} only; built-in containers and Domain Controllers are read-only here.</p>
  {/if}
</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .s { max-width: 220px; padding: 6px 10px; font-size: 12px; }
  .tg { font-size: 11px; display: flex; gap: 4px; align-items: center; }
  .note { flex: 1; font-size: 11px; min-width: 200px; }
  .filters { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 10px 20px; border-bottom: 1px solid var(--q); font-size: 11px; }
  .filters .chip { background: transparent; cursor: pointer; }
  .filters .chip[aria-pressed='true'] { border-color: var(--sig); color: var(--ink); }
  .pol { margin-left: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-weight: 400; padding: 8px 12px; border-bottom: 1px solid var(--line); }
  td { padding: 6px 12px; border-bottom: 1px solid var(--q); vertical-align: middle; }
  td:first-child, th:first-child { padding-left: 20px; }
  .nm { font-family: var(--sans, inherit); }
  .gs { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { font-size: 10.5px; padding: 1px 6px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .chip.bad { color: var(--bad); }
  .chip.warn { color: var(--warn); }
  .tag { font-size: 10px; margin-left: 6px; }
  .bad { color: var(--bad); }
  .warn { color: var(--warn); }
  .hint { padding: 10px 20px; font-size: 11px; }
</style>
