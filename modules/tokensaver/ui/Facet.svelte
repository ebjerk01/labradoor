<script>
  // Object-panel facet: the full savings breakdown.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import { ago } from '$lab/sdk.js';
  let { object, data, ctx } = $props();
</script>

{#if object.id === 'tokensaver'}
  <Section title="tokenSaver" src="tokensaver">
    <Stats items={[
      { n: 'saved', v: data.disp?.cost, s: 'ok' },
      { n: 'tokens', v: data.disp?.tokens },
      { n: 'calls', v: data.disp?.calls },
      { n: 'time', v: data.disp?.time },
      { n: 'sessions', v: data.disp?.sessions },
    ]} />
    <p class="mono dim meta">v{data.version ?? '?'} · {data.enabled ? 'enabled' : 'disabled'} · updated {ago(data.at, ctx.now)}</p>
  </Section>
{/if}

<style>
  .meta { font-size: 11px; padding-top: 6px; margin: 0; }
</style>
