<script>
  // Facet on the bazarr service: wanted subtitles, providers, tasks (run = admin), health.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { forget } from '$lab/sdk.js';
  let { object, data, ctx } = $props();
  const d = $derived(data);
  const SHOWN = ['wanted_search_missing_subtitles_series', 'wanted_search_missing_subtitles_movies', 'update_series', 'update_movies', 'check_health'];
  const tasks = $derived(d ? d.tasks.filter((t) => SHOWN.includes(t.job_id)) : []);
  const fresh = () => { forget(`${ctx.id}:tasks`); forget(`${ctx.id}:providers`); };
</script>

{#if object.id === 'bazarr' && d}
  <Section title="subtitles wanted" src="bazarr {d.version ? 'v' + d.version : ''}">
    <Stats items={[
      { n: 'episodes', v: d.wantedEps.total ?? '–' },
      { n: 'movies', v: d.wantedMovies.total ?? '–' },
      { n: 'throttled', v: d.badges.providers ?? 0, s: d.badges.providers ? 'warn' : null },
      { n: 'sonarr · radarr', v: `${d.badges.sonarr_signalr === 'LIVE' ? '●' : '▲'} ${d.badges.radarr_signalr === 'LIVE' ? '●' : '▲'}`, s: d.badges.sonarr_signalr === 'LIVE' && d.badges.radarr_signalr === 'LIVE' ? 'ok' : 'warn' },
    ]} />
    <Lines items={[
      ...d.wantedEps.items.slice(0, 4).map((e) => ({ p: '○', c: 'var(--dim)', t: `${e.seriesTitle} ${e.episode_number} · ${(e.missing_subtitles || []).map((l) => l.code2).join(' ')}` })),
      ...d.wantedMovies.items.slice(0, 3).map((m) => ({ p: '○', c: 'var(--dim)', t: `${m.title} · ${(m.missing_subtitles || []).map((l) => l.code2).join(' ')}` })),
    ]} empty="nothing wanted" />
  </Section>
  <Section title="providers" src="bazarr">
    <Lines items={d.providers.map((p) => ({ p: p.status === 'Good' ? '●' : '▲', s: p.status === 'Good' ? 'ok' : 'warn', t: `${p.name} · ${p.status}${p.retry && p.retry !== '-' ? ' · retry ' + p.retry : ''}` }))} empty="no providers" />
    {#if d.badges.providers}
      <div><ActionButton {ctx} path="/api/providers" query={{ action: 'reset' }} label="reset throttled providers" icon="restart" small done={fresh}>reset throttled providers</ActionButton></div>
    {/if}
  </Section>
  <Section title="tasks" src="bazarr">
    {#each tasks as t (t.job_id)}
      <div class="task">
        <span class="mono" class:sig={t.job_running}>{t.job_running ? '◐' : '·'}</span>
        <span class="n">{t.name}</span>
        <span class="mono dim w">{t.job_running ? 'running' : t.next_run_in}</span>
        <ActionButton {ctx} path="/api/system/tasks" query={{ taskid: t.job_id }} label="run {t.name}" icon="play" small disabled={t.job_running}
          confirm={t.job_id.startsWith('wanted_') ? `run? it asks every subtitle provider for every wanted item` : false} done={fresh}>run</ActionButton>
      </div>
    {/each}
  </Section>
  {#if d.health.length}
    <Section title="health" src="bazarr">
      <Lines items={d.health.map((h) => ({ p: '▲', s: 'warn', t: `${h.object || ''} ${h.issue || ''}`.trim() }))} />
    </Section>
  {/if}
{/if}

<style>
  .task { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto auto; gap: 8px; align-items: center; font-size: 12.5px; }
  .n { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .w { font-size: 10.5px; }
</style>
