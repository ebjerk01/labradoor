<script>
  // the gateway hub (setting `gateway`): WAN health + networks/VLANs (devices and traffic are drift's facet, from unpoller)
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import { ago } from '$lab/sdk.js';
  let { object, data, ctx } = $props();
  const w = $derived(data.health.wan || {});
  const lans = $derived(data.networks.filter((n) => n.purpose === 'corporate' || n.purpose === 'guest' || n.purpose === 'remote-user-vpn'));
</script>

{#if ctx.settings.gateway && object.id === ctx.settings.gateway}
  <Section title="wan · networks" src="unifi">
    <Stats items={[
      { n: 'wan', v: w.status || '?', s: w.status === 'ok' ? 'ok' : 'bad' },
      { n: 'isp', v: w.isp || '–' },
      { n: 'gw up', v: w.uptime ? ago(ctx.now - Number(w.uptime), ctx.now) : '–' },
      { n: 'reserved', v: data.clients.filter((c) => c.reserved).length },
    ]} />
    <Lines items={lans.map((n) => ({ p: n.isolated ? '◇' : '●', c: 'var(--sig)',
      t: `${n.name}${n.vlan ? ' · vlan ' + n.vlan : ''} · ${n.subnet || ''} · ${data.clients.filter((c) => c.online && c.networkId === n.id).length} online` }))} />
  </Section>
{/if}
