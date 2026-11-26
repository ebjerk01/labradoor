<script>
  // ~/series or ~/movies: the whole library with a filter; a row opens its detail (search, interactive search, edit,
  // delete). The list loads when the view opens (it is large), not with the 15 s refresh.
  import { lazy, bytes, sortRows } from '../sdk.js';
  import Table from '../Table.svelte';
  import Section from '../Section.svelte';
  import ItemDetail from './ItemDetail.svelte';
  import { A, APPS, slimLibrary, libStatus } from './logic.js';
  let { data, ctx } = $props();
  const app = $derived(APPS[ctx.id]);
  const tv = $derived(ctx.id === 'sonarr');
  const lib = lazy(() => ctx, () => app.lib, { pick: (r) => slimLibrary(ctx.id, r), keep: true });
  const profiles = lazy(() => ctx, () => `${A}/qualityprofile`, { pick: (r) => (r || []).map((p) => ({ id: p.id, name: p.name })) });
  let q = $state('');
  let sel = $state(null);
  let sort = $state({ key: 'title', dir: 1 });
  const rows = $derived.by(() => {
    const t = q.trim().toLowerCase();
    const all = lib.data || [];
    return t ? all.filter((x) => x.title.toLowerCase().includes(t) || String(x.year || '').includes(t)) : all;
  });
  const item = $derived(sel != null ? (lib.data || []).find((x) => x.id === sel) : null);
  const profName = (id) => (profiles.data || []).find((p) => p.id === id)?.name || '';
  const columns = $derived([
    { key: 'title', label: 'title' },
    { key: 'year', label: 'year', dim: true, phone: false },
    ...(tv ? [{ key: 'have', label: 'episodes', align: 'right', desc: true, get: (x) => x.have, format: (v, x) => `${x.have}/${x.total}` }]
      : [{ key: 'quality', label: 'file', dim: true, phone: false, format: (v, x) => (x.hasFile ? v || 'yes' : 'missing') }]),
    { key: 'qualityProfileId', label: 'profile', dim: true, phone: false, get: (x) => profName(x.qualityProfileId) },
    { key: 'size', label: 'size', align: 'right', desc: true, format: (v) => (v ? bytes(v) : '–') },
  ]);
</script>

<div class="lv fade">
  <Section title="{app.viewLabel.toLowerCase()} · {(lib.data || []).length}" src={ctx.id}>
    <input class="field" bind:value={q} placeholder="$ grep {app.viewLabel.toLowerCase()}…" aria-label="filter {app.viewLabel.toLowerCase()}" />
    {#if item}
      <ItemDetail {ctx} {item} profiles={profiles.data || []} onchange={() => lib.reload()} onclose={() => (sel = null)} />
    {/if}
    <Table {rows} key="id" {columns} bind:sort status={(x) => libStatus(ctx.id, x)} muted={(x) => !x.monitored}
      loading={lib.loading} error={lib.error} empty="nothing in the library" label={app.viewLabel.toLowerCase()} minWidth={420}
      onrow={(x) => (sel = x.id)} />
  </Section>
</div>

<style>
  .lv { min-width: 0; }
  .field { max-width: 360px; }
</style>
