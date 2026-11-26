<script>
  // Cluster tasks: running first (◌), then the latest finished (● ok / ■ failed). Click → the guest or node.
  import { ago } from '$lab/fmt.js';
  import { nodeId, taskOk, taskObject } from './pve.svelte.js';
  let { data, ctx } = $props();
  const running = $derived(data.tasks.filter((t) => !t.endtime));
  const done = $derived(data.tasks.filter((t) => t.endtime).slice(0, 14 - Math.min(running.length, 6)));
  const failed = $derived(data.tasks.filter((t) => t.endtime && !taskOk(t) && t.endtime > ctx.now - 86400).length);
</script>

<div class="v"><span class="mono big">{running.length}</span><span class="mono dim">running{failed ? '' : ' · 24h clean'}</span>{#if failed}<span class="mono bad">■ {failed} failed 24h</span>{/if}</div>
<div class="rows">
  {#each [...running.slice(0, 6), ...done] as t (t.upid)}
    <button class="r" onclick={() => ctx.open(taskObject(data, t))} title={t.status || 'running'}>
      <span class="mono" class:sig={!t.endtime} class:ok={t.endtime && taskOk(t)} class:bad={t.endtime && !taskOk(t)}>{!t.endtime ? '◌' : taskOk(t) ? '●' : '■'}</span>
      <span class="mono n">{t.type} {t.id || ''}</span>
      <span class="mono dim">{nodeId(t.node)}</span>
      <span class="mono dim a">{ago(t.endtime || t.starttime, ctx.now)}</span>
    </button>
  {/each}
</div>

<style>
  .v { display: flex; align-items: baseline; gap: 8px; font-size: 11px; }
  .big { font-size: 24px; font-weight: 500; }
  .rows { display: flex; flex-direction: column; overflow: hidden; }
  .r { display: grid; grid-template-columns: 12px 1fr auto 30px; gap: 8px; border: none; background: none; padding: 1px 0; font-size: 11px; text-align: left; }
  .r:hover { background: var(--raise); }
  .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .a { text-align: right; }
</style>
