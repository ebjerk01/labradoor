<script>
  // Facet on the jellyfin service: counts, libraries (scan), sessions, tasks (run), recent additions.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import Icon from '$lab/Icon.svelte';
  import Bar from '$lab/Bar.svelte';
  import { ago } from '$lab/fmt.js';
  import Sessions from './Sessions.svelte';
  import { act } from '$lab/sdk.js';
  let { object, data, ctx } = $props();
  const d = $derived(data);
  const IMPORTANT = ['RefreshLibrary', 'RefreshChapterImages', 'RefreshTrickplayImages', 'KeyframeExtraction', 'DeleteTranscodeFiles', 'OptimizeDatabaseTask', 'TaskExtractMediaSegments'];
  const tasks = $derived(d ? d.tasks.filter((t) => t.state !== 'Idle' || t.last?.status === 'Failed' || IMPORTANT.includes(t.key)) : []);
  const scanQ = 'metadataRefreshMode=Default&imageRefreshMode=Default&replaceAllMetadata=false&replaceAllImages=false&regenerateTrickplay=false';
  const scanLib = (l) => act(ctx, { path: `/Items/${l.id}/Refresh?${scanQ}`, label: `jellyfin: scan ${l.name}` });
  const runTask = (t) => act(ctx, { path: `/ScheduledTasks/Running/${t.id}`, label: `jellyfin: run ${t.name}` });
  const stopTask = (t) => act(ctx, { method: 'DELETE', path: `/ScheduledTasks/Running/${t.id}`, label: `jellyfin: stop ${t.name}` });
  const canScan = $derived(ctx.can('POST', '/Items/x/Refresh') !== 'no');
  const canRun = $derived(ctx.can('POST', '/ScheduledTasks/Running/x') !== 'no');
</script>

{#if object.id === 'jellyfin' && d}
  <Section title="library" src="jellyfin {d.version ? 'v' + d.version : ''}">
    <Stats items={[
      { n: 'movies', v: d.counts.MovieCount ?? '–' },
      { n: 'series', v: d.counts.SeriesCount ?? '–' },
      { n: 'episodes', v: d.counts.EpisodeCount ?? '–' },
      { n: 'playing', v: d.sessions.filter((s) => s.playing).length, s: 'ok' },
    ]} />
    {#each d.libs as l (l.id)}
      <div class="lib">
        <span class="n">{l.name}</span>
        <span class="mono dim p" title={l.paths.join(', ')}>{l.type} · {l.paths.join(', ')}</span>
        {#if l.refresh && l.refresh !== 'Idle'}<span class="pb"><Bar value={l.progress || 0} color="var(--sig)" /></span>{:else}<span></span>{/if}
        {#if canScan && !l.id.startsWith('new:')}<button class="btn x" title="scan for new files" aria-label="scan {l.name}" onclick={() => scanLib(l)}><Icon name="restart" size={11} /></button>{/if}
      </div>
    {/each}
    {#if d.restart}<span class="mono warn s">▲ Jellyfin needs a restart</span>{/if}
    <div class="go">
      {#each [['jellyfin-libraries', 'libraries'], ['jellyfin-items', 'items'], ['jellyfin-sessions', 'sessions'], ['jellyfin-users', 'users'], ['jellyfin-server', 'server']] as [v, l]}
        <button class="btn x" onclick={() => ctx.go(v)}>{l} →</button>
      {/each}
    </div>
  </Section>
  <Section title="sessions" src="live · not stored">
    <Sessions sessions={d.sessions} />
  </Section>
  <Section title="tasks" src="jellyfin">
    {#each tasks as t (t.id)}
      <div class="task">
        <span class="mono" class:sig={t.state === 'Running'} class:bad={t.last?.status === 'Failed'}>{t.state === 'Running' ? '◐' : t.last?.status === 'Failed' ? '■' : '·'}</span>
        <span class="n" title={t.last?.error || ''}>{t.name}</span>
        <span class="mono dim w">{t.state === 'Running' ? `${Math.round(t.progress || 0)}%` : t.last ? `${t.last.status} ${ago(t.last.end, ctx.now)} ago` : 'never'}</span>
        {#if canRun}
          {#if t.state === 'Running'}<button class="btn x" title="stop" aria-label="stop {t.name}" onclick={() => stopTask(t)}><Icon name="close" size={11} /></button>
          {:else}<button class="btn x" title="run now" aria-label="run {t.name}" onclick={() => runTask(t)}><Icon name="play" size={11} /></button>{/if}
        {/if}
      </div>
    {/each}
  </Section>
  <Section title="recently added" src="jellyfin">
    <Lines items={d.recent.slice(0, 10).map((it) => ({ p: it.type === 'Episode' ? 'tv' : 'mv', c: 'var(--dim)', t: `${it.label}${it.type === 'Episode' ? ' ' + it.name : ''} · ${ago(it.added, ctx.now)}` }))} empty="nothing new" />
  </Section>
{/if}

<style>
  .lib, .task { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.4fr) 60px auto; gap: 8px; align-items: center; font-size: 12.5px; }
  .task { grid-template-columns: 14px minmax(0, 1fr) auto auto; }
  .n, .p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .p, .w, .s { font-size: 10.5px; }
  .pb { display: flex; }
  .x { padding: 3px 6px; }
  .go { display: flex; flex-wrap: wrap; gap: 4px; }
</style>
