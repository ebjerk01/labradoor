<script>
  // Facet on a jellyfin-user object: account facts, the linked Authentik person, the editor.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago } from '$lab/fmt.js';
  import { UID, access, links, mbit, label } from './jf.js';
  import { lazy } from '$lab/sdk.js';
  import { remember } from './store.svelte.js';
  import UserEdit from './UserEdit.svelte';
  let { object, data, ctx } = $props();
  const u = $derived(data?.users.find((x) => UID(x.name) === object.id));
  const person = $derived(u ? `user:${links(ctx.settings).toAuthentik(u.name)}` : null);
  const known = $derived(person && ctx.object(person));
  const playing = $derived(u ? data.sessions.filter((s) => s.user === u.name && s.playing).length : 0);
  // watch stats, straight from Jellyfin's play state (lab keeps no history)
  const stat = (types) => () => ({ userId: u?.id, Recursive: 'true', IsPlayed: 'true', IncludeItemTypes: types, Limit: 0, EnableTotalRecordCount: 'true' });
  const mv = lazy(() => ctx, () => (u ? '/Items' : null), { query: stat('Movie') });
  const ep = lazy(() => ctx, () => (u ? '/Items' : null), { query: stat('Episode') });
  const last = lazy(() => ctx, () => (u ? '/Items' : null), { query: () => ({ userId: u?.id, Recursive: 'true', IsPlayed: 'true', IncludeItemTypes: 'Movie,Episode',
    SortBy: 'DatePlayed', SortOrder: 'Descending', Limit: 6, Fields: 'ProductionYear', EnableImages: 'false' }) });
  const signins = $derived(u ? data.activity.filter((a) => a.type === 'AuthenticationFailed' && a.name.toLowerCase().endsWith(` ${u.name.toLowerCase()}`)).length : 0);
</script>

{#if u}
  <Section title="jellyfin account" src="jellyfin">
    <Stats items={[
      { n: 'role', v: u.admin ? 'admin' : 'user', s: u.admin ? 'warn' : null },
      { n: 'state', v: u.disabled ? 'disabled' : 'active', s: u.disabled ? 'off' : 'ok' },
      { n: 'last login', v: u.lastLogin ? ago(u.lastLogin, ctx.now) : 'never' },
      { n: 'playing now', v: playing },
    ]} />
    <span class="mono dim s">{access(u)} · max sessions {u.maxSessions || '∞'} · {u.hasPassword ? 'has password' : 'NO password'}{u.failed ? ` · ${u.failed} failed logins` : ''}{u.hidden ? ' · hidden on login screen' : ''}</span>
    <span class="mono dim s">rating {u.rating != null ? `≤ ${u.rating}` : 'any'} · remote {u.remote ? mbit(u.bitrate) : 'OFF'}{signins ? ` · ${signins} recent failed sign-ins` : ''}</span>
    {#if known}
      <button class="btn" onclick={() => ctx.open(person)}><Icon name="user" size={12} />authentik: {person.slice(5)}</button>
    {:else if ctx.peer('authentik')}
      <span class="mono dim s">no Authentik user “{person.slice(5)}” — pair names in Settings → jellyfin → user_links</span>
    {:else}
      <span class="mono dim s">authentik: {person.slice(5)} (pairs: Settings → jellyfin → user_links)</span>
    {/if}
  </Section>
  <Section title="watched" src="jellyfin play state">
    <Stats items={[{ n: 'movies', v: mv.data?.TotalRecordCount ?? '–' }, { n: 'episodes', v: ep.data?.TotalRecordCount ?? '–' }, { n: 'devices', v: data.sessions.filter((s) => s.user === u.name).length }]} cols={3} />
    {#each last.data?.Items || [] as it (it.Id)}
      <button class="lnk mono s ell" onclick={() => ctx.open(remember(it))}>{label(it)}{it.UserData?.LastPlayedDate ? ` · ${ago(Date.parse(it.UserData.LastPlayedDate) / 1000, ctx.now)} ago` : ''}</button>
    {/each}
  </Section>
  <Section title="change" src="owner only · identity">
    <UserEdit {u} libs={data.libs} {ctx} />
  </Section>
{/if}

<style>.s { font-size: 10.5px; } .btn { align-self: flex-start; } .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: left; }</style>
