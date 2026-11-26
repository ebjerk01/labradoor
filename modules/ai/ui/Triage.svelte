<script>
  // ~/ai triage: the morning summary, then one short investigation per new alert (last 7 days) with its proposals.
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago, clock, act } from '$lab/sdk.js';
  import Md from './Md.svelte';
  import Proposal from './Proposal.svelte';
  let { data, ctx } = $props();

  const keyOf = (a) => `${a.module}:${a.key}`;
  const open = $derived(ctx.alerts().filter((a) => a.module !== 'ai' && !(data?.triage || []).some((t) => t.key === keyOf(a))));
  let busy = $state('');
  async function triageNow(a) {
    busy = keyOf(a);
    const r = await act(ctx, { path: '/api/triage', body: { key: keyOf(a) }, label: 'ai: triage alert',
      ok: (x) => (x.queued ? 'triage started' : 'already triaged recently') });
    if (r) setTimeout(() => ctx.refresh(), 4000);
    busy = '';
  }
</script>

{#if !data}<p class="mono dim pad spin">loading</p>{:else}
<div class="tv fade">
  <div class="bar mono">
    <span><span class="sig">~/ai</span> triage</span>
    <span class="dim">{data.settings.triage ? `new ${data.settings.triage_warn ? '■ ▲' : '■'} alerts · max ${data.settings.triage_daily_max}/day` : 'auto-triage off'}</span>
    <span class="dim">summary {data.settings.summary ? `after ${data.settings.summary_time}` : 'off'}</span>
  </div>

  <section class="sec">
    <div class="sh"><span class="cap">~/summary</span>
      {#if data.summary}<span class="mono dim">{data.summary.day} · {clock(data.summary.created)}{data.summary.cost ? ` · $${data.summary.cost.toFixed(3)}` : ''}</span>{/if}</div>
    {#if data.summary?.text}<Md text={data.summary.text} />
    {:else if data.summary}<span class="mono dim" class:spin={['queued', 'running'].includes(data.summary.status)}>{data.summary.status}</span>
    {:else}<span class="mono dim">no summary yet — written the first time lab is open after {data.settings.summary_time}</span>{/if}
  </section>

  <section class="sec">
    <div class="sh"><span class="cap">~/triage</span><span class="mono dim">{data.triage.length} in 7 days</span></div>
    {#each data.triage as t (t.key)}
      <div class="tr">
        <div class="hd mono">
          {#if ['queued', 'running'].includes(t.status)}<span class="spin"></span>{:else}<Glyph status={t.alert?.status || 'warn'} />{/if}
          {#if t.object}<button class="lnk" onclick={() => ctx.open(t.object)}>{t.object}</button>{/if}
          <span>{t.alert?.title}</span>
          <span class="faint">{t.alert?.module} · {t.status} · {ago(t.updated, ctx.now)}{t.runs > 1 ? ` · ${t.runs} runs` : ''}</span>
        </div>
        {#if t.text}<Md text={t.text} />{/if}
        <div class="props">{#each t.proposals || [] as p (p.id)}<Proposal {p} {ctx} after={() => ctx.refresh()} />{/each}</div>
      </div>
    {:else}
      <p class="mono dim">nothing triaged yet</p>
    {/each}
  </section>

  {#if open.length && data.keyed}
    <section class="sec">
      <div class="sh"><span class="cap">~/alerts without triage</span></div>
      {#each open.slice(0, 30) as a (keyOf(a))}
        <div class="oa mono">
          <Glyph status={a.status} /><span class="ot">{a.title}</span><span class="faint">{a.module}</span>
          <button class="btn sm" disabled={busy === keyOf(a)} onclick={() => triageNow(a)}><Icon name="search" size={11} />triage</button>
        </div>
      {/each}
    </section>
  {/if}
</div>
{/if}

<style>
  .pad { padding: 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px 16px; padding: 10px 16px; border-bottom: 1px solid var(--line); font-size: 12px; }
  .sec { padding: 12px 16px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; max-width: 980px; }
  .sh { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; font-size: 11px; }
  .tr { display: flex; flex-direction: column; gap: 6px; padding-bottom: 10px; border-bottom: 1px dashed var(--line); }
  .hd { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; font-size: 12px; }
  .props { display: flex; flex-direction: column; gap: 6px; max-width: 620px; }
  .oa { display: flex; align-items: center; gap: 8px; font-size: 12px; }
  .ot { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sm { padding: 3px 8px; font-size: 11px; }
</style>
