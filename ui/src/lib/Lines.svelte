<script>
  // Terminal-ish lines: [{p: prefix, t: text, s: status?, c: colour?}]
  import { statusVar } from './fmt.js';
  let { items = [], empty = '—' } = $props();
</script>

<div class="lines mono">
  {#each items as l}
    <div class="l"><span style:color={l.s ? statusVar(l.s) : l.c || 'var(--sig)'}>{l.p}</span> {l.t}</div>
  {:else}
    <div class="l dim">{empty}</div>
  {/each}
</div>

<style>
  .lines { font-size: 11.5px; line-height: 1.7; color: var(--dim); background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 8px 10px; }
  .l { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
