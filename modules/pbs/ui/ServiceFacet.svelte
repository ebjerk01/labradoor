<script>
  // The pbs object: datastores (usage, trend, estimate, dedup), jobs with "run now", last day's tasks with logs.
  import Section from '$lab/Section.svelte';
  import Bar from '$lab/Bar.svelte';
  import Spark from '$lab/Spark.svelte';
  import Lines from '$lab/Lines.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { ago, bytes, errText, watching } from '$lab/sdk.js';
  import { dsOf, jobsOf, jobOk, usageLevel, watchUpid, taskOk as ok } from './pbs.svelte.js';
  let { object, data, ctx } = $props();
  const STORE = $derived(data?.store);
  const running = $derived(watching.list.filter((w) => w.module === ctx.id));

  const jobs = $derived(jobsOf(data));
  const stores = $derived([...data.usage].sort((a, b) => (a.store === data.store ? -1 : b.store === data.store ? 1 : a.store.localeCompare(b.store))));
  const tasks = $derived(data.tasks.filter((t) => t.worker_type !== 'logrotate' && t.worker_type !== 'aptupdate').slice(0, 20));
  const col = (u) => ({ ok: 'var(--sig)', warn: 'var(--warn)', bad: 'var(--bad)' }[usageLevel(u)]);
  const runPath = (j) => (j.kind === 'gc' ? `${dsOf(data.store)}/gc` : `/admin/${j.kind}/${encodeURIComponent(j.id)}/run`);

  let open = $state(null);
  let log = $state(null);
  async function show(upid) {
    if (open === upid) { open = null; return; }
    open = upid;
    log = null;
    try {
      const r = await ctx.api.get(`/nodes/localhost/tasks/${encodeURIComponent(upid)}/log`, { start: 0, limit: 5000 });
      log = (r.data || []).map((l) => l.t).filter(Boolean).slice(-40);
    } catch (e) { log = [errText(e)]; }
  }
</script>

{#if data && object.id === 'pbs'}
  <Section title="datastores" src="pbs">
    {#each stores as s (s.store)}
      {@const u = s.total ? s.used / s.total : 0}
      {@const gc = s['gc-status'] || {}}
      <div class="ds">
        <div class="l"><span class="mono">{s.store}</span><span class="mono dim">{bytes(s.used, 0)}/{bytes(s.total, 0)} · {Math.round(u * 100)}%</span></div>
        <Bar value={u * 100} color={col(u)} height={5} />
        {#if s.store === data.store}
          <Spark values={(s.history || []).filter((x) => x != null).map((x) => x * 100)} color="var(--sig)" height={22} area />
          <span class="mono dim small">
            {s['estimated-full-date'] > 0 ? `full ~${Math.max(0, Math.round((s['estimated-full-date'] - data.at) / 86400))} d · ` : ''}{gc['disk-bytes'] ? `dedup ${(gc['index-data-bytes'] / gc['disk-bytes']).toFixed(1)}× · ` : ''}{gc['pending-bytes'] ? `${bytes(gc['pending-bytes'], 0)} pending gc · ` : ''}{data.groups.length} groups
          </span>
        {/if}
      </div>
    {/each}
  </Section>

  <Section title="jobs" src="pbs">
    <div class="jobs">
      {#each jobs as j (j.id)}
        <div class="j">
          <Glyph status={!j.state ? 'unknown' : jobOk(j.raw) ? 'ok' : j.kind === 'sync' && !j.schedule ? 'off' : 'warn'} />
          <button class="lnk mono nm" onclick={() => j.upid && show(j.upid)} title={j.state}>{j.kind} <span class="dim">{j.kind === 'sync' ? `${j.dir} → ${j.remote}` : j.store}</span></button>
          <span class="mono dim w">{j.last ? `${ago(j.last)} ago` : '–'} · {j.schedule || 'manual'}</span>
          {#if j.kind === 'sync'}
            <ActionButton {ctx} small path={runPath(j)} label="run sync job {j.id}" confirm done={watchUpid(`sync ${j.id}`)}>run</ActionButton>
          {:else if j.store === STORE}
            <ActionButton {ctx} small path={runPath(j)} label="run {j.kind} {j.id}" done={watchUpid(`${j.kind} ${j.id}`)}>run</ActionButton>
          {/if}
        </div>
        {#if j.state && !jobOk(j.raw)}<span class="mono small {j.kind === 'sync' && !j.schedule ? 'dim' : 'warn'}">  {j.state}</span>{/if}
        {#if open === j.upid}<Lines items={(log || ['…']).map((t) => ({ p: '>', t }))} empty="no log" />{/if}
      {/each}
    </div>
    {#each running as t (t.id)}<span class="mono sig small spin">{t.label} </span>{/each}
  </Section>

  <Section title="tasks · 24h" src="pbs">
    <div class="list">
      {#each tasks as t (t.upid)}
        <button class="lnk r" onclick={() => show(t.upid)}>
          <span class="mono" class:sig={!t.endtime} class:ok={t.endtime && ok(t)} class:bad={t.endtime && !ok(t)}>{!t.endtime ? '◌' : ok(t) ? '●' : '■'}</span>
          <span class="mono n">{t.worker_type} {t.worker_id || ''}</span>
          <span class="mono dim">{ago(t.endtime || t.starttime)}</span>
        </button>
        {#if open === t.upid}
          {#if !ok(t)}<span class="mono bad small">{t.status}</span>{/if}
          <Lines items={(log || ['…']).map((x) => ({ p: '>', t: x }))} empty="no log" />
        {/if}
      {:else}<span class="mono dim small">no tasks in 24 h</span>{/each}
    </div>
  </Section>
{/if}

<style>
  .small { font-size: 11px; }
  .ds { display: flex; flex-direction: column; gap: 4px; }
  .ds + .ds { margin-top: 6px; }
  .l { display: flex; justify-content: space-between; font-size: 12px; }
  .jobs { display: flex; flex-direction: column; gap: 3px; }
  .j { display: grid; grid-template-columns: 12px 1fr auto auto; gap: 8px; align-items: center; font-size: 11.5px; }
  .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .w { font-size: 10.5px; white-space: nowrap; }
  .list { display: flex; flex-direction: column; max-height: 300px; overflow-y: auto; }
  .r { display: grid; grid-template-columns: 12px 1fr auto; gap: 8px; padding: 2px 0; font-size: 11.5px; border-bottom: 1px solid var(--q); }
  .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
