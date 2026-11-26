<script>
  // the "cloudflare" hub on the map: zones, record counts, Access apps (traffic is drift's facet)
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import { staleA } from './cf.js';
  let { object, data, ctx } = $props();
  const addr = $derived(data.records.filter((r) => ['A', 'AAAA', 'CNAME'].includes(r.type)));
  const stale = $derived(staleA(data.records));
</script>

{#if ctx.settings.hub && object.id === ctx.settings.hub}
  <Section title="zones" src="cloudflare">
    <Stats items={[{ n: 'zones', v: data.zones.length }, { n: 'names', v: addr.length }, { n: 'proxied', v: addr.filter((r) => r.proxied).length },
      { n: 'access apps', v: data.apps.length }]} />
    <Lines items={[
      ...data.zones.map((z) => ({ p: z.status === 'active' ? '●' : '▲', s: z.status === 'active' ? 'ok' : 'warn',
        t: `${z.name} · ${z.plan} · ${data.records.filter((r) => r.zone === z.name).length} records` })),
      ...stale.map((r) => ({ p: '▲', s: 'warn', t: `${r.name} A ${r.content} ≠ apex (dynamic DNS?)` })),
    ]} />
  </Section>
  <Section title="access" src="cloudflare · zero trust">
    <Lines items={data.apps.map((a) => ({ p: '◆', c: 'var(--sig)', t: `${a.domain} · ${a.policies.map((p) => p.name).join(', ')}` }))} empty="no Access apps" />
  </Section>
{/if}
