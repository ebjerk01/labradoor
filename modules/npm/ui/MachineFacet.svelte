<script>
  // the proxy machine itself (setting `machine`): proxy summary. Any other machine: the public names NPM forwards to it
  // (IP from the UniFi module's clients).
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import { days, dayTxt, certLevel, clientFor } from './net.js';
  let { object, data, ctx } = $props();

  const client = $derived(clientFor(ctx.peer('unifi'), object.id));
  const ip = $derived(client?.fixedIp || client?.ip);
  const mine = $derived(ip ? data.hosts.filter((h) => h.host === ip || h.extra.some((x) => x.host === ip)) : []);
  const minCert = $derived(Math.min(...data.certs.map((c) => days(c.expires))));
</script>

{#if ctx.settings.machine && object.id === ctx.settings.machine}
  <Section title="proxy" src="npm">
    <Stats items={[
      { n: 'hosts', v: `${data.hosts.filter((h) => h.enabled && h.online !== false).length}/${data.hosts.length}` },
      { n: 'cf-only', v: data.hosts.filter((h) => h.originLock).length },
      { n: 'cert left', v: dayTxt(isFinite(minCert) ? minCert : null), s: certLevel(isFinite(minCert) ? minCert : null) },
      { n: 'acl hosts', v: data.hosts.filter((h) => h.accessLists.length).length },
    ]} />
    <Lines items={[
      ...data.hosts.filter((h) => !h.enabled || h.online === false).map((h) => ({ p: h.enabled ? '■' : '○', s: h.enabled ? 'bad' : 'off', t: `#${h.id} ${h.domains[0]} ${h.enabled ? h.err || 'nginx error' : 'disabled'}` })),
      ...data.certs.map((c) => ({ p: '●', s: certLevel(days(c.expires)), t: `cert ${c.name} · ${dayTxt(days(c.expires))}` })),
    ]} />
  </Section>
{:else if mine.length}
  <Section title="published as" src="npm">
    <Lines items={mine.map((h) => ({ p: !h.enabled ? '○' : h.online === false ? '■' : '●', s: !h.enabled ? 'off' : h.online === false ? 'bad' : 'ok',
      t: `${h.domains.join(' ')} → :${h.host === ip ? h.port : h.extra.find((x) => x.host === ip).port}${h.originLock ? ' · cf-only' : ''}${h.accessLists.length ? ' · acl' : ''}` }))} />
  </Section>
{/if}
