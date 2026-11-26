<script>
  // Wall tile (admin): episodes + movie releases coming up (Sonarr/Radarr calendars).
  import Upcoming from '$lab/arr/Upcoming.svelte';
  import { upcoming } from './media.js';
  let { ctx } = $props();
  const items = $derived(upcoming(ctx).filter((x) => x.at > ctx.now - 43200));
</script>

<Upcoming {items} limit={8} {ctx} />
