<script>
  // Torrents view (admin): filter by state group / category / text, select, then stop/start/recheck/reannounce/delete.
  import { bits } from '$lab/sdk.js';
  import { GROUPS, groupOf } from './qb.js';
  import TorrentRow from './TorrentRow.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import ToolsPanel from './ToolsPanel.svelte';
  let { data, ctx } = $props();
  let group = $state('all');
  let cat = $state('');
  let q = $state('');
  let sel = $state({});
  let sort = $state('added');
  let showTools = $state(false);

  const SORTS = { added: (a, b) => b.added_on - a.added_on, progress: (a, b) => b.progress - a.progress,
    speed: (a, b) => b.dlspeed + b.upspeed - a.dlspeed - a.upspeed, size: (a, b) => b.size - a.size, name: (a, b) => a.name.localeCompare(b.name) };
  const list = $derived.by(() => {
    if (!data) return [];
    const ql = q.trim().toLowerCase();
    return data.torrents.filter((t) => (group === 'all' || groupOf(t) === group) && (!cat || (t.category || '—') === cat)
      && (!ql || t.name.toLowerCase().includes(ql))).sort(SORTS[sort]);
  });
  const chosen = $derived(list.filter((t) => sel[t.hash]));
  const allOn = $derived(list.length > 0 && chosen.length === list.length);
  function all() {
    const on = !allOn;
    const next = { ...sel };
    for (const t of list) next[t.hash] = on;
    sel = next;
  }

  const VERBS = [
    { v: 'stop', icon: 'close', label: 'stop' },
    { v: 'start', icon: 'play', label: 'start' },
    { v: 'recheck', icon: 'restart', label: 'recheck' },
    { v: 'reannounce', icon: 'proxy', label: 'reannounce' },
    { v: 'delete', icon: 'archive', label: 'delete (keep files)', confirm: true },
    { v: 'delete-data', icon: 'close', label: 'delete + files', confirm: true, danger: true },
  ];
  const askText = (x, hs) => {
    const names = chosen.slice(0, 5).map((t) => '· ' + t.name).join('\n') + (hs.length > 5 ? `\n… and ${hs.length - 5} more` : '');
    return `${x.danger ? 'DELETE the files of' : 'Remove'} ${hs.length} torrent${hs.length > 1 ? 's' : ''}${x.danger ? ' — this cannot be undone' : ' (files stay on disk)'}?\n\n${names}`;
  };
</script>

{#if data}
  <div class="top">
    <span class="cap">~/torrents · {list.length}/{data.torrents.length} · ↓ {bits(data.transfer.dl_info_speed)} ↑ {bits(data.transfer.up_info_speed)}</span>
    <div class="seg" role="group" aria-label="State">
      {#each ['all', ...Object.keys(GROUPS)] as g (g)}
        {@const n = g === 'all' ? data.torrents.length : data.counts[g]}
        {#if g === 'all' || n}<button aria-pressed={group === g} onclick={() => (group = g)}>{g} {n}</button>{/if}
      {/each}
    </div>
  </div>
  <div class="tools">
    <input class="field q" placeholder="filter name" bind:value={q} aria-label="Filter by name" />
    <select class="field s" bind:value={cat} aria-label="Category">
      <option value="">all categories</option>
      {#each Object.keys(data.cats).sort() as c (c)}<option value={c}>{c} ({data.cats[c].n})</option>{/each}
    </select>
    <select class="field s" bind:value={sort} aria-label="Sort">
      {#each Object.keys(SORTS) as s (s)}<option value={s}>sort: {s}</option>{/each}
    </select>
    <label class="mono dim all"><input type="checkbox" checked={allOn} onchange={all} /> all shown</label>
    {#if ctx.can('POST', '/api/torrents/stop') !== 'no'}
      <div class="acts">
        {#each VERBS as x (x.v)}
          <span class:danger={x.danger}>
            <ActionButton {ctx} path={`/api/torrents/${x.v}`} icon={x.icon} disabled={!chosen.length}
              label="{x.label} {chosen.length}" confirm={x.confirm ? `${x.label} ${chosen.length}? click again` : false}
              title={x.confirm ? askText(x, chosen) : x.label}
              body={() => ({ hashes: chosen.map((t) => t.hash) })} done={() => { if (x.v.startsWith('delete')) sel = {}; }} />
          </span>
        {/each}
        <span class="mono dim">{chosen.length} selected</span>
        <button class="btn" aria-pressed={showTools} onclick={() => (showTools = !showTools)}>add · speed · categories</button>
      </div>
    {/if}
  </div>
  {#if showTools}<ToolsPanel {data} {ctx} />{/if}
  <div class="rows">
    {#each list.slice(0, 400) as t (t.hash)}
      <TorrentRow {t} {ctx} select bind:selected={sel[t.hash]} />
    {:else}
      <p class="mono dim pad">no torrents match</p>
    {/each}
    {#if list.length > 400}<p class="mono dim pad">showing 400 of {list.length} — narrow the filter</p>{/if}
  </div>
{:else}
  <p class="mono dim pad spin">loading torrents</p>
{/if}

<style>
  .top { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; padding: 12px 16px 0; }
  .seg button { padding: 5px 9px; font-size: 11px; }
  .tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 10px 16px; border-bottom: 1px solid var(--line); }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 12px; }
  .q { width: 220px; }
  .all { font-size: 11px; display: flex; gap: 4px; align-items: center; }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 11px; }
  .danger :global(.btn:not(:disabled)) { color: var(--bad); border-color: var(--bad); }
  .rows { padding: 4px 16px 16px; }
  .pad { padding: 12px 0; }
</style>
