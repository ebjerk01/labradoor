<script>
  // ~/__ID__: a page of its own. lazy() loads when the view opens (not on every shell refresh); Lazy shows its
  // loading / error / empty states; Table sorts and is phone-friendly. ctx.prefs remembers the sort per user.
  import Lazy from '$lab/Lazy.svelte';
  import Table from '$lab/Table.svelte';
  import { untrack } from 'svelte';
  import { lazy, ago, clip } from '$lab/sdk.js';
  let { ctx } = $props();

  const items = lazy(() => ctx, () => '/api/items');
  let sort = $state(untrack(() => ctx.prefs.get('sort', { key: 'name', dir: 1 })));  // the saved sort, once
  let picked = $state(null);
  const columns = [
    { key: 'name', label: 'name' },
    { key: 'kind', label: 'kind', dim: true, phone: false },
    { key: 'note', label: 'note', dim: true, phone: false, format: (v) => clip(v, 60) },
    { key: 'updated', label: 'updated', align: 'right', desc: true, format: (v) => (v ? ago(v, ctx.now) : '–') },
  ];
  const remember = (s) => ctx.prefs.set('sort', s);
</script>

<div class="view">
  <div class="bar">
    <span class="cap">~/__ID__</span>
    <button class="btn" onclick={items.reload} disabled={items.loading}>{#if items.loading}<span class="spin"></span>{/if}reload</button>
  </div>
  <Lazy of={items} empty="no items yet">
    {#snippet children(list)}
      <Table rows={list} {columns} bind:sort label="__NAME__ items" status={(r) => (r.ok === false ? 'warn' : 'ok')}
        onrow={(r) => { picked = r; remember(sort); }} />
    {/snippet}
  </Lazy>
  {#if picked}<p class="mono dim pick">{picked.name}: {picked.note || '—'}</p>{/if}
</div>

<style>
  .bar { display: flex; gap: 10px; align-items: center; justify-content: space-between; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .pick { padding: 10px 20px; font-size: 12px; margin: 0; }
</style>
