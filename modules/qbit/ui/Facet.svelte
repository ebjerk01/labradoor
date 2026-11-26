<script>
  // Facet on the qbittorrent service: speeds, states, categories, errored/stalled + what is moving now.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Icon from '$lab/Icon.svelte';
  import { bytes, bits } from '$lab/fmt.js';
  import { groupOf } from './qb.js';
  import TorrentRow from './TorrentRow.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  let { object, data, ctx } = $props();
  const d = $derived(data);
  const trouble = $derived(d ? d.torrents.filter((t) => ['error', 'stalled'].includes(groupOf(t))) : []);
  const moving = $derived(d ? d.torrents.filter((t) => t.dlspeed > 0 || t.upspeed > 0).sort((a, b) => b.dlspeed + b.upspeed - a.dlspeed - a.upspeed) : []);
  const errored = $derived(trouble.filter((t) => groupOf(t) === 'error'));
</script>

{#if object.id === 'qbittorrent' && d}
  <Section title="transfer" src="qbit · {d.version}">
    <Stats items={[
      { n: 'down', v: bits(d.transfer.dl_info_speed) },
      { n: 'up', v: bits(d.transfer.up_info_speed) },
      { n: 'active', v: d.counts.downloading, s: 'ok' },
      { n: 'queued', v: d.counts.queued },
      { n: 'stalled', v: d.counts.stalled, s: d.counts.stalled ? 'warn' : null },
      { n: 'error', v: d.counts.error, s: d.counts.error ? 'bad' : null },
    ]} cols={6} />
    <span class="mono dim s">{d.transfer.connection_status} · dht {d.transfer.dht_nodes} · session ↓{bytes(d.transfer.dl_info_data)} ↑{bytes(d.transfer.up_info_data)}
      · {Object.entries(d.cats).map(([c, x]) => `${c} ${x.n}${x.left ? ` (${bytes(x.left)} left)` : ''}`).join(' · ')}</span>
    <button class="btn" onclick={() => ctx.go('torrents')}><Icon name="download" size={12} />all torrents</button>
  </Section>
  {#if trouble.length}
    <Section title="errored · stalled" src="qbit">
      {#each trouble.slice(0, 10) as t (t.hash)}<TorrentRow {t} {ctx} />{/each}
      {#if errored.length}
        <ActionButton {ctx} path="/api/torrents/recheck" body={() => ({ hashes: errored.map((t) => t.hash) })} label="recheck {errored.length} errored" icon="restart" />
      {/if}
    </Section>
  {/if}
  <Section title="moving now" src="qbit">
    {#each moving.slice(0, 10) as t (t.hash)}<TorrentRow {t} {ctx} />{:else}<span class="mono dim s">idle</span>{/each}
  </Section>
{/if}

<style>
  .s { font-size: 10.5px; }
  .btn { align-self: flex-start; }
</style>
