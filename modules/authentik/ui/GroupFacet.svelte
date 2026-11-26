<script>
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Icon from '$lab/Icon.svelte';
  import { write, appAccess, humans, G } from './ak.js';
  let { object, data, ctx } = $props();
  const g = $derived(data.groups.find((x) => x.pk === object.pk));
  const byId = $derived(Object.fromEntries(data.groups.map((x) => [x.pk, x])));
  const members = $derived(data.users.filter((u) => (g?.users || []).includes(u.pk)));
  const unlocks = $derived(data.apps.filter((a) => appAccess(a, data.bindings, byId).groups.some((x) => x.pk === g?.pk)));
  let add = $state('');
</script>

{#if g}
  <Section title="group" src="authentik">
    <Stats items={[{ n: 'members', v: members.length }, { n: 'unlocks', v: `${unlocks.length} apps` }, { n: 'superuser', v: g.is_superuser ? 'YES' : 'no', s: g.is_superuser ? 'warn' : null }, { n: 'source', v: g.attributes?.distinguishedName ? 'AD' : 'local' }]} />
  </Section>
  <Section title="members" src="authentik">
    <div class="chips">
      {#each members as u (u.pk)}
        <span class="chip mono"><button class="lnk" onclick={() => ctx.open(`user:${u.username}`)}>{u.username}</button>
          {#if ctx.can('POST', `${G}${g.pk}/remove_user/`) !== 'no'}<button class="x" aria-label="Remove {u.username}" onclick={() => write(ctx, { path: `${G}${g.pk}/remove_user/`, body: { pk: u.pk }, label: `remove ${u.username} from ${g.name}` })}>×</button>{/if}
        </span>
      {:else}<span class="mono dim">empty</span>{/each}
    </div>
    {#if ctx.can('POST', `${G}${g.pk}/add_user/`) !== 'no'}
      <div class="row">
        <select class="field mono" bind:value={add} aria-label="Add member">
          <option value="">+ add member…</option>
          {#each humans(data.users).filter((u) => !(g.users || []).includes(u.pk)) as u}<option value={u.pk}>{u.username}</option>{/each}
        </select>
        <button class="btn" disabled={!add} onclick={async () => { const u = data.users.find((x) => x.pk === Number(add)); if (await write(ctx, { path: `${G}${g.pk}/add_user/`, body: { pk: u.pk }, label: `add ${u.username} to ${g.name}` })) add = ''; }}>
          <Icon name={ctx.can('POST', `${G}${g.pk}/add_user/`) === 'ask' ? 'lock' : 'check'} size={13} />add</button>
      </div>
    {/if}
  </Section>
  <Section title="unlocks" src="authentik · bindings">
    <div class="chips">{#each unlocks as a}<span class="chip mono ok">{a.slug}</span>{:else}<span class="mono dim">no app is bound to this group</span>{/each}</div>
  </Section>
{/if}

<style>
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; padding: 2px 6px 2px 8px; border: 1px solid var(--line); border-radius: 3px; }
  .x { border: none; background: transparent; color: var(--dim); padding: 0 2px; font-size: 13px; line-height: 1; }
  .x:hover { color: var(--bad); }
  .row { display: flex; gap: 6px; }
  .row .field { flex: 1; padding: 5px 8px; font-size: 12px; }
</style>
