<script>
  // [{n: label, v: value, s: status?}]
  import { statusVar } from './fmt.js';
  let { items = [], cols = 4 } = $props();
</script>

<div class="stats" style:grid-template-columns="repeat({cols}, minmax(0, 1fr))">
  {#each items as it}
    <div class="stat">
      <span class="mono v" style:color={it.s ? statusVar(it.s) : it.c || 'var(--ink)'}>{it.v}</span>
      <span class="cap">{it.n}</span>
    </div>
  {/each}
</div>

<style>
  .stats { display: grid; gap: 8px; }
  .stat { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .v { font-size: 19px; font-weight: 500; letter-spacing: -.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
