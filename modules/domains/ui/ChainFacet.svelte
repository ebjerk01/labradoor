<script>
  // the whole path of one hostname: dns → cloudflare edge → npm → backend → machine, with drift's checks
  import Section from '$lab/Section.svelte';
  import Lines from '$lab/Lines.svelte';
  import { rows } from './rows.js';
  import { dayTxt, probeLevel } from './net.js';
  let { object, ctx } = $props();
  const r = $derived(rows(ctx).find((x) => x.name === object.id));
  const lvl = (ok) => (ok ? 'ok' : 'bad');
</script>

{#if r}
  <Section title="path" src="domains">
    <Lines items={[
      { p: r.dns.kind === 'none' ? '■' : '●', s: r.dns.kind === 'none' && r.npm ? 'warn' : 'ok',
        t: `dns   ${r.dns.kind === 'record' ? `${r.dns.type} ${r.dns.content}` : r.dns.kind === 'wildcard' ? `wildcard → ${r.dns.content}` : r.dns.kind}` },
      { p: r.dns.proxied ? '●' : '○', c: r.dns.proxied ? 'var(--sig)' : 'var(--dim)',
        t: `edge  ${r.dns.proxied ? 'cloudflare proxy' : 'dns only (straight to home IP)'}${r.access.length ? ` · access: ${r.access.map((a) => (a.path ? a.path + ' ' : '') + a.policies.join(', ')).join(' | ')}` : ''}` },
      ...(r.npm ? [
        { p: !r.npm.enabled ? '○' : r.npm.online === false ? '■' : '●', s: !r.npm.enabled ? 'off' : lvl(r.npm.online !== false),
          t: `npm   #${r.npm.id}${r.npm.originLock ? ' · cf-only' : ''}${r.npm.accessLists.length ? ' · acl' : ''} · cert ${r.cert ? dayTxt(r.cert.days) : 'none'}` },
        { p: probeLevel(r.npm.backend) === 'ok' ? '●' : probeLevel(r.npm.backend) === 'unknown' ? '·' : '▲', s: probeLevel(r.npm.backend),
          t: `→     ${r.npm.scheme}://${r.npm.host}:${r.npm.port} ${r.npm.backend?.state || 'not probed'}${r.machine ? ` · ${r.machine.machine || r.machine.name}` : ''}` },
      ] : [{ p: '·', c: 'var(--faint)', t: 'npm   no proxy host' }]),
      ...[...r.checks.pub, ...r.checks.back].map((c) => ({ p: c.ok ? '●' : '■', s: lvl(c.ok), t: `check ${c.name}` })),
      ...r.refs.map((x) => ({ p: '←', t: `ref   ${x}` })),
    ]} />
    {#if r.reasons.length}<span class="mono t" class:warn={r.status === 'warn'} class:bad={r.status === 'bad'}>{r.reasons.join(' · ')}</span>{/if}
    {#if r.machine?.machine}<button class="btn" onclick={() => ctx.open(r.machine.machine)}>open {r.machine.machine}</button>{/if}
  </Section>
{/if}

<style>.t { font-size: 11px; } .btn { align-self: flex-start; }</style>
