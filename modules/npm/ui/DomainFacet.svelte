<script>
  // a hostname's NPMplus side: the proxy host that serves it
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import { days, dayTxt, certLevel, probeLevel } from './net.js';
  let { object, data } = $props();
  const h = $derived(data.hosts.find((x) => x.domains.includes(object.id)));
  const c = $derived(h ? data.certs.find((x) => x.id === h.certId) : null);
</script>

{#if h}
  <Section title="proxy host #{h.id}" src="npm">
    <Stats items={[
      { n: 'nginx', v: !h.enabled ? 'disabled' : h.online === false ? 'error' : 'online', s: !h.enabled ? 'off' : h.online === false ? 'bad' : 'ok' },
      { n: 'backend', v: h.backend?.state || '–', s: probeLevel(h.backend) === 'unknown' ? null : probeLevel(h.backend) },
      { n: 'cert', v: c ? dayTxt(days(c.expires)) : 'none', s: c ? certLevel(days(c.expires)) : 'warn' },
      { n: 'gate', v: h.originLock ? 'cf-only' : h.accessLists.length ? 'acl' : h.authRequest !== 'none' ? h.authRequest : 'open', c: h.originLock ? 'var(--sig)' : null },
    ]} />
    <span class="mono dim t">{h.scheme}://{h.host}:{h.port}{h.extra.map((x) => ` + ${x.scheme}://${x.host}:${x.port}`).join('')} · {[h.sslForced && 'ssl', h.http2 && 'h2', h.websockets && 'ws', h.hsts && 'hsts', h.blockExploits && 'exploits'].filter(Boolean).join(' ')}{h.domains.length > 1 ? ` · also ${h.domains.filter((d) => d !== object.id).join(' ')}` : ''}</span>
  </Section>
{/if}

<style>.t { font-size: 11px; word-break: break-all; }</style>
