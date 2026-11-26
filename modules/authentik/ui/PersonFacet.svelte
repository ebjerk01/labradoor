<script>
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import Icon from '$lab/Icon.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { ago } from '$lab/sdk.js';
  import { write, appAccess, U, G } from './ak.js';
  let { object, data, ctx } = $props();

  const u = $derived(data.users.find((x) => x.pk === object.pk));
  const mine = $derived(new Set(u?.groups || []));
  const byId = $derived(Object.fromEntries(data.groups.map((g) => [g.pk, g])));
  const apps = $derived(data.apps.map((a) => ({ a, acc: appAccess(a, data.bindings, byId) }))
    .map(({ a, acc }) => ({ a, ok: acc.everyone || acc.groups.some((g) => mine.has(g.pk)) || acc.users.some((x) => x.pk === u?.pk), via: acc.everyone ? 'everyone' : acc.groups.filter((g) => mine.has(g.pk)).map((g) => g.name).join(', ') || (acc.users.some((x) => x.pk === u?.pk) ? 'direct' : '') })));
  const evs = $derived(data.events.filter((e) => e.user?.pk === u?.pk || e.context?.username === u?.username).slice(0, 8));
  const lock = (m, p) => ctx.can(m, p);
  let addGroup = $state('');
  let link = $state('');
  let pw = $state('');

</script>

{#if u}
  <Section title="account" src="authentik">
    <Stats items={[
      { n: 'state', v: u.is_active ? 'active' : 'disabled', s: u.is_active ? 'ok' : 'off' },
      { n: 'last login', v: u.last_login ? ago(Date.parse(u.last_login) / 1000, ctx.now) : 'never' },
      { n: 'password', v: u.password_change_date ? ago(Date.parse(u.password_change_date) / 1000, ctx.now) : '–' },
      { n: 'type', v: u.is_superuser ? 'super' : u.type, s: u.is_superuser ? 'warn' : null },
    ]} />
    <span class="mono dim s">{u.username} · {u.email || 'no email'} · joined {ago(Date.parse(u.date_joined) / 1000, ctx.now)} ago{u.attributes?.distinguishedName ? ' · AD-linked' : ''}</span>
  </Section>

  <Section title="groups · {mine.size}" src="authentik">
    <div class="chips">
      {#each (u.groups_obj || []) as g (g.pk)}
        <span class="chip mono" class:su={g.is_superuser}>{g.name}
          {#if lock('POST', `${G}${g.pk}/remove_user/`) !== 'no'}
            <button class="x" aria-label="Remove {u.username} from {g.name}" title={lock('POST', `${G}${g.pk}/remove_user/`) === 'ask' ? 'ask owner' : 'remove'}
              onclick={() => write(ctx, { path: `${G}${g.pk}/remove_user/`, body: { pk: u.pk }, label: `remove ${u.username} from ${g.name}` })}>×</button>
          {/if}
        </span>
      {/each}
    </div>
    {#if ctx.can('POST', `${G}x/add_user/`) !== 'no'}
      <div class="row">
        <select class="field mono" bind:value={addGroup} aria-label="Add to group">
          <option value="">+ add to group…</option>
          {#each data.groups.filter((g) => !mine.has(g.pk)) as g}<option value={g.pk}>{g.name}{g.is_superuser ? ' (superuser)' : ''}</option>{/each}
        </select>
        <button class="btn" disabled={!addGroup} onclick={async () => { const g = byId[addGroup]; if (await write(ctx, { path: `${G}${g.pk}/add_user/`, body: { pk: u.pk }, label: `add ${u.username} to ${g.name}` })) addGroup = ''; }}>
          <Icon name={ctx.can('POST', `${G}x/add_user/`) === 'ask' ? 'lock' : 'check'} size={13} />{ctx.can('POST', `${G}x/add_user/`) === 'ask' ? 'ask' : 'add'}</button>
      </div>
    {/if}
  </Section>

  <Section title="apps · {apps.filter((x) => x.ok).length}/{apps.length}" src="authentik">
    <div class="apps">
      {#each apps as x (x.a.pk)}
        <span class="app mono" class:no={!x.ok} title={x.ok ? `via ${x.via}` : 'no access'}>{x.ok ? '●' : '○'} {x.a.slug}</span>
      {/each}
    </div>
  </Section>

  <Section title="recent" src="authentik · events">
    <Lines items={evs.map((e) => ({ p: e.action === 'login_failed' ? '▲' : '●', s: e.action === 'login_failed' ? 'warn' : 'ok',
      t: `${e.action.replace('_', ' ')} · ${ago(Date.parse(e.created) / 1000, ctx.now)} ago${e.client_ip ? ' · ' + e.client_ip : ''}` }))} empty="no recent events" />
  </Section>

  {#if ctx.can('POST', `${U}${u.pk}/recovery/`) !== 'no'}
    <Section title="access recovery" src="authentik">
      <div class="row">
        <ActionButton {ctx} path={`${U}${u.pk}/recovery/`} body={{ token_duration: 'hours=24' }} label={`create recovery link for ${u.username}`} icon="key"
          done={(r) => { if (r?.link) link = r.link; return false; }}>recovery link (24h)</ActionButton>
        {#if ctx.can('POST', `${U}${u.pk}/set_password/`) === 'yes'}
          <input class="field mono" type="password" placeholder="new password (12+ characters)" bind:value={pw} aria-label="New password" autocomplete="new-password" />
          <ActionButton {ctx} path={`${U}${u.pk}/set_password/`} body={() => ({ password: pw })} label={`set password for ${u.username}`} disabled={pw.length < 12}
            done={() => { pw = ''; return false; }}>set password</ActionButton>
        {/if}
      </div>
      {#if link}<input class="field mono" readonly value={link} aria-label="Recovery link" onfocus={(e) => e.currentTarget.select()} />{/if}
    </Section>
  {/if}
{/if}

<style>
  .s { font-size: 11px; }
  .chips, .apps { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; padding: 2px 4px 2px 8px; border: 1px solid var(--line); border-radius: 3px; }
  .chip.su { border-color: var(--warn); color: var(--warn); }
  .x { border: none; background: transparent; color: var(--dim); padding: 0 4px; font-size: 13px; line-height: 1; }
  .x:hover { color: var(--bad); }
  .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .row .field { flex: 1; min-width: 120px; padding: 5px 8px; font-size: 12px; }
  .app { font-size: 11px; color: var(--ok); }
  .app.no { color: var(--faint); }
</style>
