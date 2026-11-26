<script>
  // the machine the DNS server runs on (setting machine_id): resolver stats on its panel
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  let { object, data, ctx } = $props();
  const s = $derived(data.stats || {});
</script>

{#if ctx?.settings?.machine_id && object.id === ctx.settings.machine_id}
  <Section title="dns · 24h" src="technitium">
    <Stats items={[{ n: 'queries', v: s.totalQueries ?? '–' }, { n: 'blocked', v: s.totalBlocked ?? '–', c: 'var(--sig)' },
      { n: 'clients', v: s.totalClients ?? '–' }, { n: 'zones', v: data.zones.filter((z) => !z.internal).length }]} />
    <Lines items={data.topBlocked.slice(0, 5).map((x) => ({ p: '■', c: 'var(--sig)', t: `${x.name} · ${x.hits}` }))} empty="nothing blocked" />
  </Section>
{/if}
