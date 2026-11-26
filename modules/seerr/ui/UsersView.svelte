<script>
  // ~/seerr-users — Seerr's accounts: permissions (request / auto-approve / 4K / issues = admin; admin / users / settings
  // = owner), quotas, request counts; import from Jellyfin + delete = owner (admins ask).
  import { untrack } from 'svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago } from '$lab/fmt.js';
  import { act, ts } from '$lab/sdk.js';
  import PermEdit from './PermEdit.svelte';
  import { permSummary, quotaText } from './sr.js';
  let { data, ctx } = $props();

  let res = $state(null);
  let err = $state('');
  let open = $state(null);
  let perm = $state(0);
  let q = $state({ movieLimit: null, movieDays: null, tvLimit: null, tvDays: null });
  let jf = $state(null);
  let pick = $state([]);

  async function load() {
    try { res = await ctx.api.get('/api/users'); err = ''; } catch (e) { err = e.body?.error || e.message; }
  }
  $effect(() => { untrack(load); });

  function edit(u) {
    if (open === u.id) { open = null; return; }
    open = u.id;
    perm = u.permissions;
    q = { ...u.quotaSet };
  }
  const P = $derived(res?.perms);
  async function savePerms(u) {
    const full = (perm & res.privileged) !== (u.permissions & res.privileged);
    const path = `/api/users/${u.id}/permissions${full ? '/full' : ''}`;
    const r = await act(ctx, { path: path, body: { permissions: perm }, label: `seerr: permissions of ${u.name}${full ? ' (incl. admin-level)' : ''}`, confirm: full && perm & P.ADMIN ? `Make ${u.name} a Seerr ADMIN (manage everything in Seerr)?` : null });
    if (r?.ok) load();
  }
  async function saveQuota(u) {
    const n = (v) => (v === '' || v == null ? null : Number(v));
    const body = { movieLimit: n(q.movieLimit), movieDays: n(q.movieDays), tvLimit: n(q.tvLimit), tvDays: n(q.tvDays) };
    if (await act(ctx, { path: `/api/users/${u.id}/quota`, body, label: `seerr: quota of ${u.name}` })) load();
  }
  async function del(u) {
    const r = await act(ctx, { method: 'DELETE', path: `/api/users/${u.id}`, label: `seerr: delete user ${u.name}`, confirm: `Delete the Seerr user ${u.name}? Their ${u.requests} request(s) go with them (media stays). They can sign in again with Jellyfin.` });
    if (r?.ok) { open = null; load(); }
  }
  async function loadJf() {
    if (jf) { jf = null; return; }
    try { jf = (await ctx.api.get('/api/users/jellyfin')).users; pick = []; } catch (e) { ctx.notify(e.message, 'bad'); }
  }
  async function doImport() {
    if (!pick.length) return;
    const names = jf.filter((u) => pick.includes(u.id)).map((u) => u.name).join(', ');
    const r = await act(ctx, { path: '/api/users/import', body: { ids: pick }, label: `seerr: import ${names} from Jellyfin` });
    if (r?.ok) { jf = null; load(); }
  }
  const vImport = $derived(ctx.can('POST', '/api/users/import'));
</script>

<div class="uv fade">
  <div class="bar">
    <span class="cap">~/seerr-users{res ? ` · ${res.users.length}` : ''}</span>
    <span class="mono dim note">quotas + request permissions: admins · admin-level permissions, import, delete: {ctx.role === 'owner' ? 'you' : 'owner (asks owner)'}</span>
    {#if vImport !== 'no'}<button class="btn" aria-expanded={!!jf} onclick={loadJf}><Icon name={vImport === 'ask' ? 'lock' : 'user'} size={12} />import from Jellyfin</button>{/if}
  </div>
  {#if jf}
    <div class="imp">
      {#each jf as u (u.id)}
        <label class="mono s"><input type="checkbox" value={u.id} bind:group={pick} disabled={u.imported} /> {u.name}{#if u.imported}<span class="dim"> · in Seerr</span>{/if}</label>
      {/each}
      <button class="btn primary" disabled={!pick.length} onclick={doImport}>{vImport === 'ask' ? 'ask owner to import' : 'import'} {pick.length || ''}</button>
    </div>
  {/if}
  {#if err}<p class="mono bad">■ {err}</p>{/if}
  {#if !res && !err}<p class="mono dim spin">loading </p>{/if}
  {#if res}
    <div class="scroll-x"><div class="t">
      <span class="h"></span><span class="h">user</span><span class="h">lab</span><span class="h">permissions</span><span class="h">quota (used/limit)</span><span class="h">req</span><span class="h">since</span><span class="h"></span>
      {#each res.users as u (u.id)}
        <Glyph status={u.admin ? 'warn' : 'ok'} size={10} />
        <span class="nm">{u.name}<span class="mono dim tag">#{u.id} {u.type}</span>{#if u.admin}<span class="mono warn tag">admin</span>{/if}</span>
        <span class="mono s">{#each u.lab as l (l)}{#if ctx.object(`user:${l}`)}<button class="lnk" onclick={() => ctx.open(`user:${l}`)}>{l}</button>{:else}{l}{/if} {:else}<span class="dim">–</span>{/each}</span>
        <span class="mono s ell" title={u.flags.join(', ')}>{permSummary(u.permissions, P)}</span>
        <span class="mono s ell">{u.admin ? 'no limit (admin)' : quotaText(u.quota)}</span>
        <span class="mono s">{u.requests}</span>
        <span class="mono s dim">{ago(ts(u.created), ctx.now)}</span>
        {#if u.id === 1}<span class="mono dim s" title="Seerr's owner account is managed in Seerr only">owner</span>
        {:else}<button class="btn x" aria-expanded={open === u.id} aria-label="edit {u.name}" onclick={() => edit(u)}><Icon name="wrench" size={11} /></button>{/if}
        {#if open === u.id}
          {@const full = (perm & res.privileged) !== (u.permissions & res.privileged)}
          {@const v = ctx.can('POST', `/api/users/${u.id}/permissions${full ? '/full' : ''}`)}
          <div class="edit">
            <PermEdit bind:value={perm} perms={P} />
            <div class="row">
              <button class="btn" class:primary={perm !== u.permissions} disabled={perm === u.permissions || v === 'no'} onclick={() => savePerms(u)}>
                {#if v === 'ask'}<Icon name="lock" size={11} />ask owner to apply{:else}apply permissions{/if}</button>
              {#if full}<span class="mono warn s">▲ admin-level change: owner only</span>{/if}
            </div>
            {#if !u.admin}
              <div class="row mono s">
                <span class="cap">quota</span>
                <label>movies <input class="field n" type="number" min="0" max="1000" placeholder="∞" bind:value={q.movieLimit} aria-label="Movie limit" /></label>
                <label>per <input class="field n" type="number" min="0" max="365" placeholder="–" bind:value={q.movieDays} aria-label="Movie days" /> d</label>
                <label>series <input class="field n" type="number" min="0" max="1000" placeholder="∞" bind:value={q.tvLimit} aria-label="TV limit" /></label>
                <label>per <input class="field n" type="number" min="0" max="365" placeholder="–" bind:value={q.tvDays} aria-label="TV days" /> d</label>
                <button class="btn" onclick={() => saveQuota(u)}>apply quota</button>
                <span class="dim">empty = Seerr's global default</span>
              </div>
            {:else}<span class="mono dim s">quotas don't apply to Seerr admins</span>{/if}
            {#if ctx.can('DELETE', `/api/users/${u.id}`) !== 'no'}
              <button class="btn danger" onclick={() => del(u)}><Icon name={ctx.can('DELETE', `/api/users/${u.id}`) === 'ask' ? 'lock' : 'close'} size={11} />delete user</button>
            {/if}
          </div>
        {/if}
      {/each}
    </div></div>
  {/if}
</div>

<style>
  .uv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 12px; }
  .bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .note { font-size: 11px; flex: 1; }
  .imp { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; padding: 10px; border: 1px solid var(--line); border-radius: 4px; }
  .imp label { display: flex; gap: 5px; align-items: center; }
  .t { display: grid; grid-template-columns: 12px minmax(110px, 1fr) auto minmax(90px, 1.2fr) minmax(110px, 1.2fr) auto auto auto; gap: 6px 14px; align-items: center; font-size: 12.5px; min-width: 700px; }
  .h { font: 10px "Geist Mono Variable", monospace; color: var(--dim); }
  .nm { display: flex; gap: 6px; align-items: baseline; }
  .tag { font-size: 9.5px; }
  .s { font-size: 11px; }
  .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .x { padding: 3px 6px; }
  .edit { grid-column: 1 / -1; display: flex; flex-direction: column; gap: 10px; padding: 8px 0 12px 20px; border-bottom: 1px solid var(--line); }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .row label { display: flex; gap: 4px; align-items: center; }
  .n { width: 64px; padding: 4px 6px; }
  .danger { align-self: flex-start; }
  .danger:hover { color: var(--bad); border-color: var(--bad); }
</style>
