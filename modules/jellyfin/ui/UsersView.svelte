<script>
  // ~/jellyfin-users — Jellyfin's own accounts (separate from Authentik). Reading: admin. Every change: owner (admin → ask).
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago } from '$lab/fmt.js';
  import { UID, access, links } from './jf.js';
  import { act, forget } from '$lab/sdk.js';
  import UserEdit from './UserEdit.svelte';
  let { data, ctx } = $props();
  let open = $state(null);
  let creating = $state(false);
  let nu = $state({ name: '', pw: '', all: true, libs: [] });
  const canCreate = $derived(ctx.can('POST', '/Users/New') === 'yes');  // a new user needs a password: owner only, never via an approval
  const l = $derived(links(ctx.settings));

  async function create(e) {
    e.preventDefault();
    const name = nu.name.trim();
    if (!name || nu.pw.length < 8) return ctx.notify('name + a password of at least 8 characters', 'bad');
    forget(`${ctx.id}:users`);
    const r = await act(ctx, { path: '/Users/New', body: { Name: name, Password: nu.pw }, label: `jellyfin: create user ${name}` });
    if (!r?.Id) return;
    if (!nu.all) {  // Jellyfin creates users with every library open; narrow it right away
      await act(ctx, { path: `/Users/${r.Id}/Policy`, body: { ...r.Policy, EnableAllFolders: false, EnabledFolders: nu.libs }, label: `jellyfin ${name}: library access` });
    }
    nu = { name: '', pw: '', all: true, libs: [] };
    creating = false;
  }
</script>

{#if !data}<p class="mono dim pad spin">loading jellyfin</p>{:else}
<div class="uv fade">
  <div class="bar">
    <span class="cap">~/jellyfin-users · {data.users.length}</span>
    <span class="mono dim note">{ctx.role === 'owner' ? 'changes apply immediately' : 'changes are owner-only → each one asks owner'}</span>
    {#if canCreate}<button class="btn primary" onclick={() => (creating = !creating)}><Icon name="user" size={13} />new user</button>{/if}
  </div>
  {#if creating}
    <form class="new" onsubmit={create}>
      <input class="field mono" placeholder="name (= Authentik username if possible)" bind:value={nu.name} required aria-label="Name" />
      <input class="field mono" type="password" autocomplete="new-password" placeholder="password" bind:value={nu.pw} required aria-label="Password" />
      <label class="mono"><input type="checkbox" bind:checked={nu.all} /> all libraries</label>
      {#if !nu.all}{#each data.libs as lib (lib.id)}<label class="mono"><input type="checkbox" value={lib.id} bind:group={nu.libs} /> {lib.name}</label>{/each}{/if}
      <button class="btn primary">create</button>
    </form>
  {/if}
  <div class="scroll-x"><div class="t">
    <span class="h"></span><span class="h">user</span><span class="h">authentik</span><span class="h">libraries</span><span class="h">sessions</span><span class="h">last login</span><span class="h">seen</span><span class="h"></span>
    {#each data.users as u (u.id)}
      {@const p = `user:${l.toAuthentik(u.name)}`}
      <Glyph status={u.disabled ? 'off' : 'ok'} size={10} />
      <button class="lnk nm" onclick={() => ctx.open(UID(u.name))}>{u.name}{#if u.admin}<span class="mono warn tag">admin</span>{/if}{#if !u.hasPassword}<span class="mono bad tag">no pw</span>{/if}</button>
      {#if ctx.object(p)}<button class="lnk mono s" onclick={() => ctx.open(p)}>{p.slice(5)}</button>{:else}<span class="mono dim s" title="not a person lab knows (authentik module)">{p.slice(5)}?</span>{/if}
      <span class="s dim ell" title={access(u)}>{access(u)}</span>
      <span class="mono s">{u.maxSessions || '∞'} · {data.sessions.filter((s) => s.user === u.name && s.playing).length}▶</span>
      <span class="mono s dim">{u.lastLogin ? ago(u.lastLogin, ctx.now) : 'never'}</span>
      <span class="mono s dim">{u.lastActivity ? ago(u.lastActivity, ctx.now) : '–'}</span>
      <button class="btn x" aria-expanded={open === u.id} aria-label="edit {u.name}" onclick={() => (open = open === u.id ? null : u.id)}><Icon name="wrench" size={11} /></button>
      {#if open === u.id}<div class="edit"><UserEdit {u} libs={data.libs} {ctx} /></div>{/if}
    {/each}
  </div></div>
  {#if !data.usersOk}<p class="mono warn pad">▲ could not read /Users</p>{/if}
</div>
{/if}

<style>
  .uv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 12px; }
  .bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .note { font-size: 11px; flex: 1; }
  .new { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 10px; border: 1px solid var(--line); border-radius: 4px; }
  .new .field { width: 220px; }
  .new label { font-size: 11.5px; display: flex; gap: 4px; align-items: center; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 12px; }
  .t { display: grid; grid-template-columns: 12px minmax(120px, 1fr) minmax(90px, auto) minmax(0, 2fr) auto auto auto auto; gap: 6px 14px; align-items: center; font-size: 12.5px; min-width: 680px; }
  .h { font: 10px "Geist Mono Variable", monospace; color: var(--dim); }
  .nm { display: flex; gap: 6px; align-items: baseline; }
  .tag { font-size: 9.5px; }
  .s { font-size: 11px; }
  .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .x { padding: 3px 6px; }
  .edit { grid-column: 1 / -1; padding: 8px 0 12px 20px; border-bottom: 1px solid var(--line); }
  .pad { padding: 12px 0; }
</style>
