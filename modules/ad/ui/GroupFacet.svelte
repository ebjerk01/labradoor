<script>
  // An AD group: members, scope, whether lab may change it (OU=Grupper only), and the Authentik side.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Icon from '$lab/Icon.svelte';
  import { act, ago } from '$lab/sdk.js';
  import { UP, enc, ouPath, ouName, lockIcon, akSource } from './ad.js';
  let { object, data, ctx } = $props();

  const g = $derived(data.groups.find((x) => `adgroup:${x.name}` === object.id));
  const byDn = $derived(Object.fromEntries(data.users.map((u) => [u.dn.toLowerCase(), u])));
  const members = $derived((g?.members || []).map((dn) => ({ dn, u: byDn[dn.toLowerCase()] })));
  const candidates = $derived(g ? data.users.filter((u) => u.inHomelab && !g.members.some((m) => m.toLowerCase() === u.dn.toLowerCase())) : []);
  // Authentik syncs OU=Grupper as groups with group_matching_mode=identifier (never merged into an existing group by name)
  const akGroup = $derived(g?.managed ? (ctx.peer('authentik')?.groups || []).find((x) => (x.attributes?.distinguishedName || '').toLowerCase() === g.dn.toLowerCase()) : null);
  const vAdd = $derived(ctx.can('POST', '/api/users/x/groups/x'));
  let add = $state('');
</script>

{#if g}
  <Section title="group" src="active directory">
    <Stats items={[
      { n: 'members', v: g.members.length },
      { n: 'scope', v: g.scope === 'domain local' ? 'local' : g.scope },
      { n: 'in lab', v: g.managed ? 'edit' : 'read', s: g.managed ? 'ok' : null },
    ]} cols={3} />
    <span class="mono dim s">{g.kind} group · {ouPath(g.ou, data.base)}{g.description ? ' · ' + g.description : ''} · changed {g.changed ? ago(g.changed, ctx.now) + ' ago' : '–'}{g.protected ? ' · adminCount=1 (privileged)' : ''}</span>
  </Section>

  <Section title="members" src="active directory">
    <div class="chips">
      {#each members as m (m.dn)}
        <span class="chip mono">
          {#if m.u}<button class="lnk" onclick={() => ctx.open(`aduser:${m.u.sam}`)}>{m.u.sam}</button>{:else}<span class="dim">{m.dn.split(/(?<!\\),/)[0].replace(/^CN=/i, '')}</span>{/if}
          {#if g.managed && m.u?.inHomelab && ctx.can('DELETE', `${UP(m.u.sam)}/groups/${enc(g.name)}`) !== 'no'}
            <button class="x" aria-label="Remove {m.u.sam}" onclick={() => act(ctx, { method: 'DELETE', path: `${UP(m.u.sam)}/groups/${enc(g.name)}`, label: `remove ${m.u.sam} from AD group ${g.name}` })}>×</button>
          {/if}
        </span>
      {:else}<span class="mono dim">empty</span>{/each}
    </div>
    {#if g.managed && vAdd !== 'no' && candidates.length}
      <div class="row">
        <select class="field mono" bind:value={add} aria-label="Add member">
          <option value="">+ add member…</option>
          {#each candidates as u}<option value={u.sam}>{u.sam}{u.service ? ' (service)' : ''}</option>{/each}
        </select>
        <button class="btn" disabled={!add} onclick={async () => { if (await act(ctx, { path: `${UP(add)}/groups/${enc(g.name)}`, label: `add ${add} to AD group ${g.name}` })) add = ''; }}>
          <Icon name={lockIcon(vAdd)} size={13} />{vAdd === 'ask' ? 'ask' : 'add'}</button>
      </div>
    {/if}
    {#if !g.managed}<span class="mono dim s">outside {ouName(data.groupsOu)}: membership is changed on the DC, not in lab.</span>{/if}
  </Section>

  {#if g.managed}
    <Section title="authentik" src={akSource(ctx) ? `authentik · ldap source ${akSource(ctx)}` : 'authentik'}>
      {#if akGroup}
        <button class="btn" onclick={() => ctx.open(`group:${akGroup.name}`)}><Icon name="shield" size={13} />{akGroup.name}</button>
      {:else}
        <span class="mono dim s">no synced Authentik group found{ctx.peer('authentik') ? '' : ' (Authentik data not loaded)'}.</span>
      {/if}
      <span class="mono dim s">groups in {ouName(data.groupsOu)} sync into Authentik as their own groups (matched by identifier, never merged by name) — AD membership changes show up there after the next sync.</span>
    </Section>
  {/if}
{/if}

<style>
  .s { font-size: 11px; line-height: 1.5; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; padding: 2px 6px 2px 8px; border: 1px solid var(--line); border-radius: 3px; }
  .x { border: none; background: transparent; color: var(--dim); padding: 0 2px; font-size: 13px; line-height: 1; }
  .x:hover { color: var(--bad); }
  .row { display: flex; gap: 6px; }
  .row .field { flex: 1; padding: 5px 8px; font-size: 12px; }
</style>
