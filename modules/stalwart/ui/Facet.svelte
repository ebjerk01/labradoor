<script>
  // Facet on the mail server's object: counters, certificate, scheduled tasks, auth failures 24 h (via the graylog
  // module, when it is active for this user), queue pause/resume (owner).
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Icon from '$lab/Icon.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { rel, when, safeUrl } from '$lab/sdk.js';
  import { objId, secs, blockedSince, logQuery } from './sw.js';
  let { object, data, ctx } = $props();
  const d = $derived(data);
  const mine = $derived(object.id === objId(ctx.settings));
  const day = $derived(ctx.now - 86400);
  const cert = $derived(d?.certificates?.[0]);
  const certLeft = $derived(cert ? Math.floor(((secs(cert.notAfter) || 0) - ctx.now) / 86400) : null);

  // auth failures from the logs: Stalwart's API has none (no log tracer is readable over JMAP)
  const gl = $derived(ctx.via('graylog'));
  const glWeb = $derived(ctx.peer('graylog')?.cfg?.web || '');
  let fails = $state(null);
  let blockedHits = $state(null);
  $effect(() => {
    const g = gl;
    if (!mine || !g || g.can('GET', '/api/search/universal/relative') !== 'yes') return;
    const count = (q) => g.api.get('/api/search/universal/relative', { query: q, range: 86400, limit: 1, decorate: 'false' })
      .then((r) => r.total_results ?? null).catch(() => null);
    Promise.all([count(logQuery(ctx.settings.log_query, 'auth')), count(logQuery(ctx.settings.log_query, 'blocked'))])
      .then(([a, b]) => { fails = a; blockedHits = b; });
  });
  const glLink = (which) => (glWeb ? safeUrl(`${glWeb}/search?q=${encodeURIComponent(logQuery(ctx.settings.log_query, which))}&rangetype=relative&from=86400`) : null);
</script>

{#if mine && d}
  <Section title="mail server" src="stalwart">
    <Stats items={[
      { n: 'queued', v: d.counts.queue, s: d.counts.failing ? 'warn' : null },
      { n: 'failing', v: d.counts.failing, s: d.counts.failing ? 'warn' : null },
      { n: 'accounts', v: d.counts.accounts },
      { n: 'domains', v: d.counts.domains },
      { n: 'blocked IPs', v: d.counts.blocked },
      { n: 'new 24 h', v: blockedSince(d, day) },
      { n: 'allowed IPs', v: d.counts.allowed },
      { n: 'reports in', v: d.reports.dmarc + d.reports.tls + d.reports.arf },
    ]} cols={4} />
    {#if cert}
      <span class="mono dim s" class:warn={certLeft != null && certLeft < 14}>
        certificate {(cert.names || []).join(', ')} · valid until {when(secs(cert.notAfter))} ({certLeft} d) · {cert.issuer?.replace(/^.*CN=/, '')}
      </span>
    {/if}
    {#if d.tasks.length}
      <span class="mono dim s">next: {d.tasks.slice(0, 3).map((t) => `${t.type}${t.domain ? ' ' + t.domain : ''} ${rel(secs(t.due), ctx.now)}`).join(' · ')}</span>
    {/if}
    {#if gl}
      <span class="mono dim s">logs 24 h:
        {#if glLink('auth')}<a class="lnk" href={glLink('auth')} target="_blank" rel="noopener">{fails ?? '…'} auth failures</a>{:else}{fails ?? '…'} auth failures{/if}
        ·
        {#if glLink('blocked')}<a class="lnk" href={glLink('blocked')} target="_blank" rel="noopener">{blockedHits ?? '…'} hits from blocked IPs</a>{:else}{blockedHits ?? '…'} hits from blocked IPs{/if}
      </span>
    {/if}
    <div class="row">
      {#if ctx.canGo('stalwart')}<button class="btn" onclick={() => ctx.go('stalwart')}><Icon name="mail" size={12} />queue · accounts · reports</button>{/if}
      <ActionButton {ctx} path="/api/queue/pause" label="pause mail queue" icon="close" confirm="pause outgoing delivery? click again" small />
      <ActionButton {ctx} path="/api/queue/resume" label="resume mail queue" icon="play" small />
    </div>
  </Section>
{/if}

<style>
  .s { font-size: 10.5px; }
  .warn { color: var(--warn); }
  .row { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
