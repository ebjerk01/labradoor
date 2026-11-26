<script>
  // Scheduled tasks: state, last result (+ error), triggers (edit: daily / weekly / interval / at startup, max runtime),
  // run now / stop. Admin.
  import Icon from '$lab/Icon.svelte';
  import Bar from '$lab/Bar.svelte';
  import { ago } from '$lab/fmt.js';
  import { TICK } from './jf.js';
  import { write } from './store.svelte.js';
  let { data, ctx } = $props();

  const H = 3600 * TICK;
  const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const INTERVALS = [0.25, 0.5, 1, 2, 3, 4, 6, 8, 12, 24, 48, 72, 120, 168];
  const canRun = $derived(ctx.can('POST', '/ScheduledTasks/Running/x') !== 'no');
  const canEdit = $derived(ctx.can('POST', '/ScheduledTasks/x/Triggers') !== 'no');
  const groups = $derived.by(() => {
    const g = {};
    for (const t of data.tasks) (g[t.category || 'other'] ||= []).push(t);
    return Object.entries(g).sort();
  });
  let open = $state(null);
  let trig = $state([]);
  let nt = $state({ Type: 'DailyTrigger', time: '03:00', day: 'Sunday', hours: 24, max: '' });

  const hhmm = (ticks) => { const m = Math.round((ticks || 0) / TICK / 60); return `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`; };
  const hours = (ticks) => { const h = ticks / H; return h < 1 ? `${Math.round(h * 60)}m` : `${+h.toFixed(1)}h`; };
  function text(t) {
    const max = t.MaxRuntimeTicks ? ` · max ${hours(t.MaxRuntimeTicks)}` : '';
    if (t.Type === 'DailyTrigger') return `daily ${hhmm(t.TimeOfDayTicks)}${max}`;
    if (t.Type === 'WeeklyTrigger') return `${(t.DayOfWeek || '').slice(0, 3).toLowerCase()} ${hhmm(t.TimeOfDayTicks)}${max}`;
    if (t.Type === 'IntervalTrigger') return `every ${hours(t.IntervalTicks)}${max}`;
    if (t.Type === 'StartupTrigger') return `at startup${max}`;
    return t.Type;
  }
  function edit(t) {
    if (open === t.id) { open = null; return; }
    open = t.id;
    trig = t.triggers.map((x) => ({ ...x }));
  }
  function addTrig() {
    const [h, m] = nt.time.split(':').map(Number);
    const tod = ((h || 0) * 60 + (m || 0)) * 60 * TICK;
    const x = { Type: nt.Type };
    if (nt.Type === 'DailyTrigger' || nt.Type === 'WeeklyTrigger') x.TimeOfDayTicks = tod;
    if (nt.Type === 'WeeklyTrigger') x.DayOfWeek = nt.day;
    if (nt.Type === 'IntervalTrigger') x.IntervalTicks = Math.round(Number(nt.hours) * H);
    if (Number(nt.max) > 0) x.MaxRuntimeTicks = Math.round(Number(nt.max) * H);
    trig = [...trig, x];
  }
  const KEYS = ['Type', 'TimeOfDayTicks', 'IntervalTicks', 'DayOfWeek', 'MaxRuntimeTicks'];
  async function save(t) {
    const body = trig.map((x) => Object.fromEntries(KEYS.filter((k) => x[k] != null).map((k) => [k, x[k]])));
    if (await write(ctx, ['tasks'], { path: `/ScheduledTasks/${t.id}/Triggers`, body, label: `jellyfin: triggers · ${t.name}` })) open = null;
  }
  const run = (t) => write(ctx, ['tasks'], { path: `/ScheduledTasks/Running/${t.id}`, label: `jellyfin: run ${t.name}` });
  const stop = (t) => write(ctx, ['tasks'], { method: 'DELETE', path: `/ScheduledTasks/Running/${t.id}`, label: `jellyfin: stop ${t.name}` });
  const dur = (l) => (l?.start && l?.end ? Math.max(0, Math.round(l.end - l.start)) : null);
</script>

{#each groups as [cat, tasks] (cat)}
  <h3 class="cap h">~/{cat.toLowerCase()}</h3>
  {#each tasks as t (t.id)}
    {@const failed = t.last?.status === 'Failed'}
    <div class="t" class:on={open === t.id}>
      <span class="mono" class:sig={t.state === 'Running'} class:bad={failed} class:dim={!failed && t.state !== 'Running'}>{t.state === 'Running' ? '◐' : failed ? '■' : t.last ? '●' : '○'}</span>
      <span class="n" title={t.description}>{t.name}</span>
      <span class="mono dim w trg">{t.triggers.length ? t.triggers.map(text).join(' · ') : 'manual only'}</span>
      {#if t.state === 'Running'}<span class="pb last"><Bar value={t.progress || 0} color="var(--sig)" /></span>
      {:else}<span class="mono w last" class:bad={failed} class:dim={!failed} title={t.last?.error || ''}>{t.last ? `${t.last.status.toLowerCase()} ${ago(t.last.end, ctx.now)} ago${dur(t.last) != null ? ` · ${dur(t.last) < 60 ? dur(t.last) + 's' : Math.round(dur(t.last) / 60) + 'm'}` : ''}` : 'never ran'}</span>{/if}
      <span class="acts">
        {#if canRun}
          {#if t.state === 'Running'}<button class="btn x" title="stop" aria-label="stop {t.name}" onclick={() => stop(t)}><Icon name="close" size={11} /></button>
          {:else}<button class="btn x" title="run now" aria-label="run {t.name}" onclick={() => run(t)}><Icon name="play" size={11} /></button>{/if}
        {/if}
        {#if canEdit}<button class="btn x" title="triggers" aria-label="triggers of {t.name}" aria-expanded={open === t.id} onclick={() => edit(t)}><Icon name="wrench" size={11} /></button>{/if}
      </span>
      {#if failed && t.last.error}<span class="mono bad err">{t.last.error}</span>{/if}
      {#if open === t.id}
        <div class="ed">
          {#each trig as x, i (i)}
            <div class="tr"><span class="mono">{text(x)}</span><button class="btn x" aria-label="remove trigger" onclick={() => (trig = trig.filter((_, j) => j !== i))}><Icon name="close" size={10} /></button></div>
          {:else}<span class="mono dim s">no triggers: runs only when started by hand</span>{/each}
          <div class="add">
            <select class="field" bind:value={nt.Type} aria-label="Trigger type">
              <option value="DailyTrigger">daily</option><option value="WeeklyTrigger">weekly</option><option value="IntervalTrigger">every</option><option value="StartupTrigger">at startup</option>
            </select>
            {#if nt.Type === 'WeeklyTrigger'}<select class="field" bind:value={nt.day} aria-label="Day">{#each DAYS as d}<option value={d}>{d.slice(0, 3).toLowerCase()}</option>{/each}</select>{/if}
            {#if nt.Type === 'DailyTrigger' || nt.Type === 'WeeklyTrigger'}<input class="field" type="time" bind:value={nt.time} aria-label="Time" />{/if}
            {#if nt.Type === 'IntervalTrigger'}<select class="field" bind:value={nt.hours} aria-label="Interval">{#each INTERVALS as h}<option value={h}>{hours(h * H)}</option>{/each}</select>{/if}
            <label class="mono s">max h <input class="field n" type="number" min="0" max="72" step="0.5" bind:value={nt.max} /></label>
            <button class="btn x" onclick={addTrig}>+ add</button>
          </div>
          <div class="add">
            <button class="btn primary" onclick={() => save(t)}>save triggers</button>
            <button class="btn" onclick={() => (open = null)}>cancel</button>
          </div>
        </div>
      {/if}
    </div>
  {/each}
{/each}

<style>
  .h { margin: 10px 0 2px; font-weight: 400; }
  .t { display: grid; grid-template-columns: 14px minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1fr) auto; gap: 4px 10px; align-items: center; font-size: 12.5px; padding: 4px 0; border-bottom: 1px solid var(--q); }
  .t.on { background: var(--panel); }
  .n, .w { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .w, .s { font-size: 10.5px; }
  .pb { display: flex; }
  .acts { display: flex; gap: 4px; }
  .x { padding: 3px 6px; }
  .err { grid-column: 2 / -1; font-size: 10.5px; white-space: pre-wrap; }
  .ed { grid-column: 2 / -1; display: flex; flex-direction: column; gap: 6px; padding: 6px 0 10px; }
  .tr { display: flex; gap: 8px; align-items: center; font-size: 11.5px; }
  .add { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .add label { display: flex; gap: 4px; align-items: center; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 4px 7px; font-size: 12px; color: var(--ink); }
  .n { width: 56px; }
  .bad { color: var(--bad); }
  @media (max-width: 640px) {
    .t { grid-template-columns: 14px minmax(0, 1fr) auto; }
    .trg { display: none; }
    .last { grid-column: 2 / -1; grid-row: 2; }
  }
</style>
