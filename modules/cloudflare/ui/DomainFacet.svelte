<script>
  // a hostname's Cloudflare side: its records (or the wildcard that answers for it) + Access
  import Section from '$lab/Section.svelte';
  import Lines from '$lab/Lines.svelte';
  let { object, data } = $props();
  const own = $derived(data.records.filter((r) => r.name === object.id));
  const pointing = $derived(data.records.filter((r) => r.name !== object.id && r.content === object.id));
  const apps = $derived(data.apps.filter((a) => (a.domains || [a.domain]).some((d) => d?.split('/')[0] === object.id)));
  const wc = $derived(own.length ? null : data.records.find((r) => r.name === `*.${object.id.split('.').slice(1).join('.')}`));
</script>

{#if own.length || apps.length || wc || pointing.length}
  <Section title="dns" src="cloudflare">
    <Lines items={[
      ...own.map((r) => ({ p: r.proxied ? '●' : '○', s: r.proxied ? 'ok' : null, c: r.proxied ? null : 'var(--dim)',
        t: `${r.type} → ${r.content}${r.proxied ? ' · proxied' : ' · dns only'}${r.comment ? ' · ' + r.comment : ''}` })),
      ...(wc ? [{ p: '*', t: `via ${wc.name} ${wc.type} ${wc.content} · dns only` }] : []),
      ...pointing.map((r) => ({ p: '←', t: `${r.type} ${r.name} points here` })),
      ...apps.map((a) => ({ p: '◆', c: 'var(--sig)', t: `access ${a.domain} · ${a.policies.map((p) => (p.decision === 'bypass' ? '↷ ' : '') + p.name).join(', ')} · ${a.session}` })),
    ]} />
  </Section>
{/if}
