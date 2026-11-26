<script>
  // A Proxmox node: storage, cluster/quorum, HA, recent tasks. (Metrics: drift; apt/reboot: manage.)
  import Section from '$lab/Section.svelte';
  import Lines from '$lab/Lines.svelte';
  import Bar from '$lab/Bar.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import { bytes, ago } from '$lab/fmt.js';
  import Tasks from './Tasks.svelte';
  import { lazy } from '$lab/sdk.js';
  import { nodeId, isGuest } from './pve.svelte.js';
  let { n, data, ctx } = $props();

  const st = lazy(() => ctx, () => `/nodes/${n.node}/storage`, { pick: (r) => r?.data ?? null });
  const ver = lazy(() => ctx, () => `/nodes/${n.node}/status`, { pick: (r) => r?.data ?? null });
  const guests = $derived(data.resources.filter((r) => isGuest(r) && r.node === n.node));
  const cl = $derived(data.cluster.find((x) => x.type === 'cluster'));
  const me = $derived(data.cluster.find((x) => x.type === 'node' && x.name === n.node));
  const ha = $derived((data.haStatus || []).filter((h) => h.node === n.node || h.type === 'quorum'));
  const lvl = (u) => (u >= 90 ? 'var(--bad)' : u >= 80 ? 'var(--warn)' : 'var(--sig)');
</script>

<Section title="proxmox node" src="proxmox · {n.node}">
  <span class="mono dim small">{n.status}{n.uptime ? ` · up ${ago(Date.now() / 1000 - n.uptime)}` : ''} · {guests.filter((g) => g.status === 'running').length}/{guests.length} guests{ver.data?.pveversion ? ` · ${ver.data.pveversion.split('/')[1]}` : ''}{ver.data?.kversion ? ` · ${ver.data.kversion.split(' ')[1]}` : ''}</span>
  <div class="stores">
    {#each (st.data || []).filter((s) => s.enabled !== 0).sort((a, b) => a.storage.localeCompare(b.storage)) as s (s.storage)}
      {@const u = s.total ? (100 * s.used) / s.total : 0}
      <div class="s" title="{s.storage}: {s.type} · {s.content}">
        <Glyph status={s.active ? 'ok' : 'bad'} />
        <span class="mono nm">{s.storage}</span>
        <Bar value={u} color={lvl(u)} />
        <span class="mono dim v">{s.total ? `${bytes(s.used, 0)}/${bytes(s.total, 0)}` : '–'}</span>
      </div>
    {:else}<span class="mono dim small {st.error ? 'bad' : 'spin'}">{st.error || 'storage '}</span>{/each}
  </div>
</Section>

<Section title="cluster {cl?.name || ''}" src="proxmox">
  <Lines items={[
    { p: cl?.quorate ? '●' : '■', s: cl?.quorate ? 'ok' : 'bad', t: `${cl?.quorate ? 'quorate' : 'NO QUORUM'} · ${data.cluster.filter((x) => x.type === 'node' && x.online).length}/${cl?.nodes ?? '?'} nodes · v${cl?.version ?? '?'}` },
    ...data.cluster.filter((x) => x.type === 'node').map((x) => ({ p: x.online ? '●' : '■', s: x.online ? 'ok' : 'bad',
      t: `${nodeId(x.name)} · ${x.ip} · id ${x.nodeid}${x.name === me?.name ? ' · this' : ''}` })),
    ...ha.filter((h) => h.type !== 'quorum').map((h) => ({ p: '◆', t: `${h.type} ${h.id}: ${h.status}` })),
  ]} />
</Section>

<Section title="tasks" src="proxmox · {n.node}">
  <Tasks {ctx} node={n.node} limit={15} />
</Section>

<style>
  .small { font-size: 11.5px; }
  .stores { display: flex; flex-direction: column; gap: 4px; }
  .s { display: grid; grid-template-columns: 12px 92px 1fr 104px; gap: 8px; align-items: center; font-size: 11.5px; }
  .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .v { text-align: right; font-size: 10.5px; }
</style>
