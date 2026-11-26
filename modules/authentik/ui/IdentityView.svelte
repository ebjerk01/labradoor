<script>
  // ~/identity — Authentik users, groups and who may open which app. Reading: admin. Changes: owner (admin → ask owner).
  import Icon from '$lab/Icon.svelte';
  import Table from '$lab/Table.svelte';
  import { ago } from '$lab/sdk.js';
  import { write, appAccess, humans, U, G, B } from './ak.js';
  let { data, ctx } = $props();

  let tab = $state('people');
  let q = $state('');
  let creating = $state(false);
  let nu = $state({ username: '', name: '', email: '', groups: [] });
  let ng = $state('');
  const verb = (m, p) => ctx.can(m, p);
  const people = $derived(data ? humans(data.users).filter((u) => !q || `${u.username} ${u.name} ${u.email}`.toLowerCase().includes(q.toLowerCase())) : []);
  const byId = $derived(data ? Object.fromEntries(data.groups.map((g) => [g.pk, g])) : {});
  const groups = $derived(data ? data.groups.filter((g) => !q || g.name.toLowerCase().includes(q.toLowerCase())) : []);
  const access = $derived(data ? data.apps.map((a) => ({ a, acc: appAccess(a, data.bindings, byId) })) : []);
  const cols = $derived(data ? data.groups.filter((g) => !g.attributes?.distinguishedName || access.some((x) => x.acc.groups.some((y) => y.pk === g.pk))) : []);

  async function createUser(e) {
    e.preventDefault();
    const body = { username: nu.username.trim(), name: nu.name.trim() || nu.username.trim(), email: nu.email.trim(), groups: nu.groups, is_active: true, type: 'internal', path: 'users' };
    if (await write(ctx, { path: U, body, label: `create user ${body.username}` })) { nu = { username: '', name: '', email: '', groups: [] }; creating = false; }
  }
  async function createGroup(e) {
    e.preventDefault();
    if (await write(ctx, { path: G, body: { name: ng.trim() }, label: `create group ${ng.trim()}` })) ng = '';
  }
  function toggle(app, g, acc) {
    const b = acc.groups.find((x) => x.pk === g.pk);
    if (b) return write(ctx, { method: 'DELETE', path: `${B}${b.binding}/`, label: `revoke ${g.name} → ${app.slug}` });
    const order = Math.max(0, ...acc.bindings.map((x) => x.order)) + 10;
    return write(ctx, { path: B, body: { target: app.pk, group: g.pk, order, enabled: true, negate: false, timeout: 30 }, label: `grant ${g.name} → ${app.slug}`,
      confirm: acc.everyone ? `${app.slug} is open to EVERY Authentik user today. Binding ${g.name} limits it to that group (plus any later bindings). Continue?` : false });
  }
</script>

{#if !data}<p class="mono dim pad"><span class="spin"></span> loading authentik</p>{:else}
<div class="iv fade">
  <div class="bar">
    <div class="seg" role="group" aria-label="Section">
      {#each [['people', humans(data.users).length], ['groups', data.groups.length], ['access', data.appsReady ? data.apps.length : '…']] as [t, n]}
        <button aria-pressed={tab === t} onclick={() => (tab = t)}>{t} <span class="faint">{n}</span></button>
      {/each}
    </div>
    <input class="field mono s" placeholder="$ grep …" bind:value={q} aria-label="Search" />
    <span class="mono dim note">{ctx.role === 'owner' ? 'changes apply immediately' : 'changes are owner-only → each one asks the owner'}</span>
    {#if tab === 'people' && verb('POST', U) !== 'no'}<button class="btn primary" onclick={() => (creating = !creating)}><Icon name="user" size={13} />create user</button>{/if}
  </div>

  {#if tab === 'people'}
    {#if creating}
      <form class="new" onsubmit={createUser}>
        <input class="field mono" placeholder="username" bind:value={nu.username} required aria-label="Username" />
        <input class="field" placeholder="full name" bind:value={nu.name} aria-label="Name" />
        <input class="field mono" type="email" placeholder="email" bind:value={nu.email} aria-label="Email" />
        <div class="gpick">
          {#each data.groups.filter((g) => !g.is_superuser) as g}
            <label class="mono"><input type="checkbox" value={g.pk} bind:group={nu.groups} /> {g.name}</label>
          {/each}
        </div>
        <button class="btn primary">{verb('POST', U) === 'ask' ? 'ask owner' : 'create'}</button>
        <span class="mono dim hint">then open the person → recovery link (24 h) to let them set a password</span>
      </form>
    {/if}
    <Table rows={people} key="pk" {ctx} object={(u) => `user:${u.username}`} status={(u) => (u.is_active ? 'ok' : 'off')} label="people"
      muted={(u) => !u.is_active} empty="nobody matches"
      columns={[
        { key: 'username', label: 'user', render: userCell, get: (u) => u.name || u.username },
        { key: 'email', label: 'email', dim: true, phone: false },
        { key: 'groups', label: 'groups', sort: false, render: groupCell, phone: false },
        { key: 'last_login', label: 'last login', desc: true, dim: true, get: (u) => (u.last_login ? Date.parse(u.last_login) : 0), format: (v) => (v ? ago(v / 1000, ctx.now) : 'never') },
        { key: 'is_superuser', label: 'super', sort: false, render: suCell },
      ]} />
    {#snippet userCell(u)}<span class="nm">{u.name || u.username}</span> <span class="dim">{u.username}</span>{/snippet}
    {#snippet groupCell(u)}<span class="gs">{#each (u.groups_obj || []) as g}<span class="chip mono" class:su={g.is_superuser}>{g.name}</span>{/each}</span>{/snippet}
    {#snippet suCell(u)}{#if u.is_superuser}<span class="warn" title="superuser">su</span>{/if}{/snippet}

  {:else if tab === 'groups'}
    {#if verb('POST', G) !== 'no'}
      <form class="new" onsubmit={createGroup}>
        <input class="field mono" placeholder="new group name" bind:value={ng} required aria-label="Group name" />
        <button class="btn primary">{verb('POST', G) === 'ask' ? 'ask owner' : 'create group'}</button>
      </form>
    {/if}
    <Table rows={groups} key="pk" {ctx} object={(g) => `group:${g.name}`} label="groups" empty="no groups match"
      columns={[
        { key: 'name', label: 'group' },
        { key: 'users', label: 'members', render: memberCell, get: (g) => (g.users || []).length, desc: true },
        { key: 'unlocks', label: 'unlocks', sort: false, render: unlockCell, phone: false },
        { key: 'flags', label: 'flags', sort: false, render: flagCell, phone: false },
      ]} />
    {#snippet memberCell(g)}<span class="gs">{#each data.users.filter((u) => (g.users || []).includes(u.pk)) as u}<span class="chip mono">{u.username}</span>{/each}</span>{/snippet}
    {#snippet unlockCell(g)}<span class="gs">{#each access.filter((x) => x.acc.groups.some((y) => y.pk === g.pk)) as x}<span class="chip mono ok">{x.a.slug}</span>{/each}</span>{/snippet}
    {#snippet flagCell(g)}{#if g.is_superuser}<span class="warn">superuser</span>{/if}{#if g.attributes?.distinguishedName}<span class="dim"> AD</span>{/if}{/snippet}

  {:else if !data.appsReady}
    <p class="mono dim pad"><span class="spin"></span> reading the apps from Authentik</p>
  {:else}
    <p class="mono dim intro">who may open each app: an app with no group bound is open to every Authentik user. Click a cell to grant/revoke.</p>
    <div class="scroll-x"><table class="mx">
      <thead><tr><th class="cap">app</th>{#each cols as g}<th class="vt mono" title={g.name}><span>{g.name}</span></th>{/each}</tr></thead>
      <tbody>
        {#each access as { a, acc } (a.pk)}
          <tr class="row">
            <td class="mono an">{a.slug}{#if acc.everyone}<span class="sig"> · everyone</span>{/if}{#if acc.users.length}<span class="dim"> · +{acc.users.length} users</span>{/if}{#if acc.other}<span class="dim"> · +{acc.other} policies</span>{/if}</td>
            {#each cols as g}
              {@const on = acc.groups.some((x) => x.pk === g.pk)}
              <td class="c"><button class="cell" class:on aria-label="{a.slug} for {g.name}: {on ? 'granted' : 'not granted'}" aria-pressed={on}
                disabled={verb('POST', B) === 'no'} onclick={() => toggle(a, g, acc)}>{on ? '●' : '·'}</button></td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table></div>
  {/if}
</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .s { max-width: 220px; padding: 6px 10px; font-size: 12px; }
  .note { flex: 1; font-size: 11px; }
  .new { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 20px; border-bottom: 1px solid var(--line); align-items: center; }
  .new .field { max-width: 220px; padding: 6px 10px; font-size: 12.5px; }
  .gpick { display: flex; flex-wrap: wrap; gap: 4px 12px; width: 100%; font-size: 11.5px; color: var(--dim); }
  .hint { font-size: 11px; width: 100%; }
  .mx { width: 100%; border-collapse: collapse; font-size: 13px; }
  .mx th { text-align: left; font-weight: 400; padding: 8px 12px; border-bottom: 1px solid var(--line); }
  .mx td { padding: 6px 12px; border-bottom: 1px solid var(--q); vertical-align: middle; }
  .mx td:first-child, .mx th:first-child { padding-left: 20px; }
  .nm { font-family: var(--sans, inherit); }
  .warn { color: var(--warn); }
  .gs { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { font-size: 10.5px; padding: 1px 6px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .chip.su { color: var(--warn); border-color: var(--warn); }
  .chip.ok { color: var(--ok); }
  .intro { padding: 12px 20px 0; font-size: 11.5px; }
  .mx th.vt { height: 120px; vertical-align: bottom; padding: 4px 2px; width: 26px; }
  .mx th.vt span { display: inline-block; writing-mode: vertical-rl; transform: rotate(180deg); font-size: 10.5px; color: var(--dim); white-space: nowrap; }
  .an { white-space: nowrap; font-size: 12px; }
  .c { padding: 0; text-align: center; }
  .cell { width: 26px; height: 26px; border: none; background: transparent; color: var(--faint); font-size: 14px; }
  .cell.on { color: var(--sig); }
  .cell:hover:not(:disabled) { background: var(--raise); color: var(--ink); }
</style>
