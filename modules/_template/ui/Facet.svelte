<script>
  // The module's part of the object panel. Buttons come from ActionButton: it hides routes this user may not call,
  // shows "ask owner" for owner-only ones and runs them through act() (toast, refresh, approvals).
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { ago } from '$lab/sdk.js';
  let { object, data, ctx } = $props();
</script>

{#if object.id === '__ID__'}
  <Section title="__ID__" src="__ID__">
    <Stats items={[
      { n: 'state', v: data.status?.ok ? 'up' : 'down', s: data.status?.ok ? 'ok' : 'bad' },
      { n: 'items', v: data.count },
      { n: 'checked', v: ago(data.at, ctx.now) },
    ]} />
    <div class="row">
      <ActionButton {ctx} path="/api/restart" label="restart __ID__" icon="restart" confirm="restart __ID__ now?" small />
      <ActionButton {ctx} path="/api/secret-thing" label="rotate secret" icon="key" small />
    </div>
  </Section>
{/if}

<style>
  .row { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
