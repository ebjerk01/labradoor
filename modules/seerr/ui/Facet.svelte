<script>
  // Facet on the seerr service (or CT 115 "seerr" when drift's machine object wins the merge): counts, users, requests.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import RequestRow from './RequestRow.svelte';
  let { object, data, ctx } = $props();
  const d = $derived(data);
</script>

{#if object.id === 'seerr' && d?.counts}
  <Section title="requests" src="seerr {d.version ? 'v' + d.version : ''}{d.updateAvailable ? ' · update available' : ''}">
    <Stats items={[
      { n: 'pending', v: d.counts.pending, s: d.counts.pending ? 'warn' : null },
      { n: 'processing', v: d.counts.processing },
      { n: 'done', v: d.counts.available + d.counts.completed, s: 'ok' },
      { n: 'failed', v: d.failed?.length || 0, s: d.failed?.length ? 'warn' : null },
      { n: 'issues', v: d.issues?.open || 0, s: d.issues?.open ? 'warn' : null },
    ]} cols={5} />
    {#if d.updateAvailable}<span class="mono warn s">▲ update available ({d.commitsBehind} behind){d.restartRequired ? ' · restart needed' : ''}</span>{/if}
    <span class="mono s go">{#each [['seerr-discover', 'discover'], ['seerr-requests', 'requests'], ['seerr-issues', 'issues'], ['seerr-users', 'users'], ['seerr-settings', 'settings']] as [v, l] (v)}{#if ctx.canGo(v)}<button class="lnk" onclick={() => ctx.go(v)}>~/{l}</button>{/if}{/each}</span>
    <span class="mono dim s">{d.users.map((u) => `${u.name} ${u.requests}`).join(' · ')}</span>
  </Section>
  <Section title="latest" src="seerr">
    {#each [...d.pending, ...d.all.filter((r) => r.status !== 'pending')].slice(0, 15) as r (r.id)}<RequestRow {r} {ctx} by manage />{/each}
  </Section>
{/if}

<style>.s { font-size: 10.5px; } .go { display: flex; gap: 12px; flex-wrap: wrap; }</style>
