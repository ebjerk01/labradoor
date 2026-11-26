<script>
  // A Proxmox guest: state line + tabs config · snapshots · tasks · move (migrate / grow disk).
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import { ago, bytes } from '$lab/fmt.js';
  import Act from './Act.svelte';
  import Tasks from './Tasks.svelte';
  import { lazy } from '$lab/sdk.js';
  import { gpath, kindOf, nodeId, disks, nets, jobsFor, watching, vmidOfTask, ui, SNAP_RE, stamp } from './pve.svelte.js';
  let { g, data, ctx } = $props();

  const p = $derived(gpath(g));
  const run = $derived(g.status === 'running');
  const lxc = $derived(g.type === 'lxc');
  const cfg = lazy(() => ctx, () => `${p}/config`, { pick: (r) => r?.data ?? null });
  const ifs = lazy(() => ctx, () => (lxc && run && ui.tab === 'cfg' ? `${p}/interfaces` : null), { pick: (r) => r?.data ?? null });
  const snaps = lazy(() => ctx, () => (ui.tab === 'snap' ? `${p}/snapshot` : null), { pick: (r) => r?.data ?? null });
  const c = $derived(cfg.data || {});
  const dk = $derived(disks(c));
  const nt = $derived(nets(c));
  const jobs = $derived(jobsFor(data.jobs, g.vmid));
  const ha = $derived((data.ha || []).find((h) => h.sid === `${lxc ? 'ct' : 'vm'}:${g.vmid}`));
  const repl = $derived((data.repl || []).filter((r) => String(r.guest) === String(g.vmid)));
  const mine = $derived(watching.list.filter((t) => t.module === 'proxmox' && vmidOfTask(t) === String(g.vmid)));
  const ips = $derived((ifs.data || []).filter((i) => i.name !== 'lo').flatMap((i) => (i['ip-addresses'] || [])
    .filter((a) => a['ip-address-type'] === 'inet').map((a) => `${i.name} ${a['ip-address']}/${a.prefix}`)));

  // --- config edit (cores / memory / onboot) ---
  let cores = $state(null);
  let mem = $state(null);
  let onboot = $state(null);
  $effect(() => {
    if (cfg.data) { cores = Number(cfg.data.cores || 1); mem = Number(cfg.data.memory || 512); onboot = !!Number(cfg.data.onboot || 0); }
  });
  const changes = $derived.by(() => {
    if (!cfg.data || cores == null || mem == null) return null;
    const o = {};
    if (cores !== Number(c.cores || 1)) o.cores = cores;
    if (mem !== Number(c.memory || 512)) o.memory = mem;
    if (onboot !== !!Number(c.onboot || 0)) o.onboot = onboot ? 1 : 0;
    return Object.keys(o).length ? { ...o, digest: c.digest } : null;
  });

  // --- snapshots ---
  let snapName = $state(`lab-${stamp()}`);
  let snapRam = $state(false);
  const snapList = $derived((snaps.data || []).filter((s) => s.name !== 'current').sort((a, b) => (b.snaptime || 0) - (a.snaptime || 0)));

  // --- move ---
  const targets = $derived(data.resources.filter((r) => r.type === 'node' && r.status === 'online' && r.node !== g.node).map((r) => r.node));
  let target = $state('');
  let tstore = $state('');
  $effect(() => { if (!targets.includes(target)) target = targets[0] || ''; });
  const pre = lazy(() => ctx, () => (ui.tab === 'move' && !lxc ? `${p}/migrate` : null), { query: () => (target ? { target } : undefined), pick: (r) => r?.data ?? null });
  const stores = lazy(() => ctx, () => (ui.tab === 'move' && target ? `/nodes/${target}/storage` : null), { query: () => ({ content: lxc ? 'rootdir' : 'images', enabled: 1 }), pick: (r) => r?.data ?? null });
  const blocked = $derived((pre.data?.not_allowed_nodes || {})[target]);
  let disk = $state('');
  let grow = $state(8);
  $effect(() => { if (!dk.find((x) => x.key === disk)) disk = dk[0]?.key || ''; });
  const migBody = () => (lxc
    ? { target, ...(run ? { restart: 1, timeout: 120 } : {}), ...(tstore ? { 'target-storage': tstore } : {}) }
    : { target, ...(run ? { online: 1 } : {}), 'with-local-disks': 1, ...(tstore ? { targetstorage: tstore } : {}) });

  const TABS = [['cfg', 'config'], ['snap', 'snapshots'], ['task', 'tasks'], ['move', 'move']];
</script>

<Section title="proxmox · {kindOf(g)}" src="proxmox · {nodeId(g.node)}">
  <div class="top">
    <span class="mono dim st">{g.status}{run ? ` · up ${ago(Date.now() / 1000 - g.uptime)}` : ''}{g.lock ? ` · locked: ${g.lock}` : ''}{ha ? ` · ha ${ha.state}` : ''}</span>
    {#if run}<Act {ctx} path="{p}/status/stop" label="stop {g.name} (hard)" text="stop" confirm />{/if}
  </div>
  {#each mine as t (t.id)}<span class="mono sig small spin">{t.label} </span>{/each}

  <div class="seg" role="group" aria-label="Proxmox">
    {#each TABS as [id, l]}<button aria-pressed={ui.tab === id} onclick={() => (ui.tab = id)}>{l}</button>{/each}
  </div>

  {#if ui.tab === 'cfg'}
    {#if cfg.error}<span class="mono bad small">{cfg.error}</span>
    {:else if !cfg.data}<span class="mono dim small spin">config </span>
    {:else}
      <Stats cols={4} items={[
        { n: 'cores', v: `${c.sockets && c.sockets > 1 ? `${c.sockets}×` : ''}${c.cores || 1}` },
        { n: 'memory', v: bytes(Number(c.memory || 0) * 1048576, 0) },
        { n: 'disks', v: bytes(dk.reduce((s, x) => s + (parseFloat(x.size) || 0) * ({ T: 1024 ** 4, G: 1024 ** 3, M: 1024 ** 2, K: 1024 }[x.size.slice(-1)] || 1), 0), 0) },
        { n: 'onboot', v: Number(c.onboot) ? 'yes' : 'no', s: Number(c.onboot) ? null : 'off' },
      ]} />
      <Lines items={[
        ...dk.map((x) => ({ p: '▤', t: `${x.key} ${x.vol} ${x.size}${x.mp ? ` → ${x.mp}` : ''}` })),
        ...nt.map((n) => ({ p: '⇄', t: `${n.key} ${n.bridge}${n.tag ? `.${n.tag}` : ''} ${n.ip || ''} ${n.mac}`.replace(/\s+/g, ' ') })),
        ...ips.map((t) => ({ p: '@', t })),
        ...jobs.map((j) => ({ p: '↺', t: `${j.id} · ${j.schedule} → ${j.storage}` })),
        ...repl.map((r) => ({ p: '⇉', t: `replication ${r.id} → ${r.target} · ${r.schedule || '*/15'}` })),
        ...(c.tags ? [{ p: '#', t: String(c.tags).replaceAll(';', ' ') }] : []),
        ...(!jobs.length ? [{ p: '▲', s: 'warn', t: 'in no backup job' }] : []),
      ]} />
      {#if ctx.can('PUT', `${p}/config`) !== 'no'}
        <div class="edit">
          <label class="mono dim">cores <input class="field n" type="number" min="1" max="64" bind:value={cores} /></label>
          <label class="mono dim">MiB <input class="field m" type="number" min="64" step="256" bind:value={mem} /></label>
          <label class="mono dim"><input type="checkbox" bind:checked={onboot} /> onboot</label>
          <Act {ctx} method="PUT" path="{p}/config" body={() => changes} label="change {g.name} config" text="save" disabled={!changes}
            done={() => cfg.reload()} />
        </div>
        {#if changes && run && (changes.cores || changes.memory)}<span class="mono faint small">running: may apply on next boot (hotplug)</span>{/if}
      {/if}
    {/if}

  {:else if ui.tab === 'snap'}
    {#if snaps.error}<span class="mono bad small">{snaps.error}</span>
    {:else if !snaps.data}<span class="mono dim small spin">snapshots </span>
    {:else}
      <div class="list">
        {#each snapList as s (s.name)}
          <div class="r">
            <span class="mono nm">{s.name}<span class="dim"> · {s.snaptime ? ago(s.snaptime) : '?'}{s.vmstate ? ' · ram' : ''}</span>
              {#if s.description}<span class="faint d">{s.description.trim()}</span>{/if}</span>
            <span class="b">
              <Act {ctx} path="{p}/snapshot/{encodeURIComponent(s.name)}/rollback" label="roll back {g.name} to {s.name}" text="rollback" confirm done={() => snaps.reload()} />
              <Act {ctx} method="DELETE" path="{p}/snapshot/{encodeURIComponent(s.name)}" label="delete snapshot {s.name} of {g.name}" text="delete" confirm done={() => snaps.reload()} />
            </span>
          </div>
        {:else}<span class="mono dim small">no snapshots</span>{/each}
      </div>
      <div class="edit">
        <input class="field grow" aria-label="Snapshot name" bind:value={snapName} />
        {#if !lxc && run}<label class="mono dim"><input type="checkbox" bind:checked={snapRam} /> ram</label>{/if}
        <Act {ctx} path="{p}/snapshot" label="snapshot {g.name}: {snapName}" text="snapshot" disabled={!SNAP_RE.test(snapName)}
          body={() => ({ snapname: snapName, description: `lab · ${ctx.me?.username || '?'}`, ...(!lxc && run && snapRam ? { vmstate: 1 } : {}) })}
          done={() => { snapName = `lab-${stamp()}`; snaps.reload(); }} />
      </div>
    {/if}

  {:else if ui.tab === 'task'}
    <Tasks {ctx} node={g.node} vmid={g.vmid} />

  {:else if ui.tab === 'move'}
    <span class="cap">migrate</span>
    <div class="edit">
      <select class="sel" aria-label="Target node" bind:value={target}>{#each targets as t}<option value={t}>{nodeId(t)}</option>{/each}</select>
      <select class="sel" aria-label="Target storage" bind:value={tstore}>
        <option value="">same storage</option>
        {#each (stores.data || []).filter((s) => s.active) as s}<option value={s.storage}>{s.storage} · {bytes(s.avail, 0)} free</option>{/each}
      </select>
      <Act {ctx} path="{p}/migrate" label="migrate {g.name} to {nodeId(target)}" text={run ? (lxc ? 'migrate (restart)' : 'migrate (live)') : 'migrate'}
        body={migBody} confirm disabled={!target || !!blocked} />
    </div>
    {#if blocked}<span class="mono warn small">▲ {nodeId(target)}: {JSON.stringify(blocked).slice(0, 160)}</span>{/if}
    {#if pre.data?.local_resources?.length}<span class="mono warn small">▲ local resources: {pre.data.local_resources.join(', ')}</span>{/if}

    <span class="cap">grow disk</span>
    <div class="edit">
      <select class="sel" aria-label="Disk" bind:value={disk}>{#each dk as x}<option value={x.key}>{x.key} · {x.size}</option>{/each}</select>
      <label class="mono dim">+<input class="field n" type="number" min="1" max="2048" bind:value={grow} />G</label>
      <Act {ctx} method="PUT" path="{p}/resize" label="grow {g.name} {disk} by {grow}G" text="grow" confirm
        body={() => ({ disk, size: `+${grow}G` })} disabled={!disk || !(grow > 0)} done={() => cfg.reload()} />
    </div>
    <span class="mono faint small">grow only — shrinking is not possible</span>
  {/if}
</Section>

<style>
  .small { font-size: 11.5px; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .st { font-size: 11.5px; }
  .edit { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 11.5px; }
  .edit label { display: flex; align-items: center; gap: 4px; }
  .field { padding: 3px 7px; font-size: 11.5px; }
  .field.n { width: 62px; }
  .field.m { width: 80px; }
  .grow { flex: 1 1 160px; }
  .sel { padding: 3px 6px; font-size: 11.5px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; max-width: 100%; }
  .list { display: flex; flex-direction: column; max-height: 320px; overflow-y: auto; }
  .r { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 0; border-bottom: 1px solid var(--q); }
  .nm { display: flex; flex-direction: column; min-width: 0; font-size: 11.5px; }
  .d { font-size: 10.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .b { display: flex; gap: 4px; flex: none; }
</style>
