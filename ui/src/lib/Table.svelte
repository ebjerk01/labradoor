<script>
  // A module's list view: sortable columns, a row opens a lab object (ctx.open) or calls onrow, loading / error / empty
  // states, columns that hide on a phone. Reference: docs/sdk.md.
  //   columns: [{key, label, get?: (row) => value, format?: (value, row) => text, render?: snippet(row),
  //              sort?: false | (row) => value, desc?: true (first click sorts high → low), align?: 'right',
  //              dim?: true, phone?: false (hidden on narrow screens), title?: (row) => text}]
  //   rows, key ('id' or (row) => key), status?: (row) => 'ok'|'warn'|'bad'|'off' (a glyph column),
  //   object?: (row) => lab object id + ctx (row click opens it), onrow?: (row) => void, muted?: (row) => bool,
  //   sort (bindable {key, dir: 1|-1}), loading, error, empty, label (aria-label), minWidth (px, before it scrolls)
  import Glyph from './Glyph.svelte';
  import { sortRows } from './sdk-core.js';

  let { rows = [], columns = [], key = 'id', status = null, object = null, ctx = null, onrow = null, muted = null,
    sort = $bindable(null), loading = false, error = null, empty = 'nothing here', label = '', minWidth = 0 } = $props();

  const keyOf = (r, i) => (typeof key === 'function' ? key(r) : r?.[key] ?? i);
  const valueOf = (c, r) => (c.get ? c.get(r) : r?.[c.key]);
  const sortable = (c) => c.sort !== false;
  const shown = $derived.by(() => {
    const c = sort && columns.find((x) => x.key === sort.key);
    if (!c) return rows || [];
    return sortRows(rows, typeof c.sort === 'function' ? c.sort : (r) => valueOf(c, r), sort.dir || 1);
  });
  const clickable = $derived(!!(onrow || (object && ctx)));
  const span = $derived(columns.length + (status ? 1 : 0));

  function by(c) {
    if (!sortable(c)) return;
    sort = sort?.key === c.key ? { key: c.key, dir: -(sort.dir || 1) } : { key: c.key, dir: c.desc ? -1 : 1 };
  }
  function pick(r) {
    if (onrow) return onrow(r);
    const id = object?.(r);
    if (id && ctx) ctx.open(id);
  }
  function key_(e, r) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(r); }
  }
</script>

<div class="wrap">
  <table class="mono" aria-label={label || undefined} aria-busy={loading} style:min-width={minWidth ? `${minWidth}px` : undefined}>
    <thead><tr>
      {#if status}<th class="g" aria-label="status"></th>{/if}
      {#each columns as c (c.key)}
        <th class:r={c.align === 'right'} class:ph={c.phone === false}
          aria-sort={sort?.key === c.key ? (sort.dir > 0 ? 'ascending' : 'descending') : sortable(c) ? 'none' : undefined}>
          {#if sortable(c)}
            <button class="lnk cap" class:on={sort?.key === c.key} onclick={() => by(c)}>{c.label ?? c.key}<span class="arr" aria-hidden="true">{sort?.key === c.key ? (sort.dir > 0 ? '↑' : '↓') : '↕'}</span></button>
          {:else}<span class="cap">{c.label ?? c.key}</span>{/if}
        </th>
      {/each}
    </tr></thead>
    <tbody>
      {#if error}
        <tr><td colspan={span} class="msg bad">{error}</td></tr>
      {:else if loading && !rows?.length}
        <tr><td colspan={span} class="msg dim"><span class="spin"></span> loading</td></tr>
      {:else}
        {#each shown as r, i (keyOf(r, i))}
          <tr class:row={clickable} class:muted={muted?.(r)} tabindex={clickable ? 0 : undefined}
            onclick={clickable ? () => pick(r) : undefined} onkeydown={clickable ? (e) => key_(e, r) : undefined}>
            {#if status}<td class="g"><Glyph status={status(r)} size={10} /></td>{/if}
            {#each columns as c (c.key)}
              <td class:r={c.align === 'right'} class:dim={c.dim} class:ph={c.phone === false} title={c.title?.(r)}>
                {#if c.render}{@render c.render(r)}{:else}{c.format ? c.format(valueOf(c, r), r) : (valueOf(c, r) ?? '–')}{/if}
              </td>
            {/each}
          </tr>
        {:else}
          <tr><td colspan={span} class="msg dim">{empty}</td></tr>
        {/each}
      {/if}
    </tbody>
  </table>
</div>

<style>
  .wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
  th { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; font-weight: normal; }
  td { padding: 5px 10px; border-top: 1px solid var(--q); white-space: nowrap; color: var(--ink); }
  th:first-child, td:first-child { padding-left: 20px; }
  th:last-child, td:last-child { padding-right: 20px; }
  .g { width: 14px; }
  .r { text-align: right; }
  .r button { margin-left: auto; }
  th button { display: inline-flex; gap: 4px; align-items: baseline; }
  th button.on { color: var(--sig); }
  .arr { opacity: .6; }
  tr.row { cursor: pointer; }
  tr.row:hover { background: var(--raise); }
  tr.row:focus-visible { outline: 1px solid var(--sig); outline-offset: -1px; }
  tr.muted td { color: var(--dim); }
  td.dim { color: var(--dim); }
  .msg { padding: 14px 20px; white-space: normal; }
  @media (max-width: 640px) {
    .ph { display: none; }
    th:first-child, td:first-child { padding-left: 16px; }
    th:last-child, td:last-child { padding-right: 16px; }
  }
</style>
