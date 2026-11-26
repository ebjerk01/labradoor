<script>
  // On an Authentik person (user:<username>): their Jellyfin account, if one is linked by name or by the user_links setting.
  import Section from '$lab/Section.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import { ago } from '$lab/fmt.js';
  import { UID, access, links } from './jf.js';
  let { object, data, ctx } = $props();
  const name = $derived(object.id.startsWith('user:') ? links(ctx.settings).toJellyfin(object.id.slice(5)) : null);
  const u = $derived(name && data?.users.find((x) => x.name.toLowerCase() === name));
</script>

{#if u}
  <Section title="jellyfin" src="jellyfin">
    <button class="lnk r" onclick={() => ctx.open(UID(u.name))}>
      <Glyph status={u.disabled ? 'off' : 'ok'} size={10} />
      <span>{u.name}{u.admin ? ' · admin' : ''}</span>
      <span class="mono dim">{access(u)} · {u.lastActivity ? 'seen ' + ago(u.lastActivity, ctx.now) + ' ago' : 'never seen'}</span>
    </button>
  </Section>
{/if}

<style>
  .r { display: grid; grid-template-columns: 14px auto minmax(0, 1fr); gap: 8px; align-items: baseline; font-size: 12.5px; }
  .r .mono { font-size: 10.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
