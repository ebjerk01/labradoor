<script>
  // ~/media — the whole stack on one page: what is stuck, what is moving, what is coming, what is broken, who asked.
  // Reads the media modules' data through ctx.peer (each optional) and acts through ctx.via(<module>), so every
  // action is checked against THAT module's manifest.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Bar from '$lab/Bar.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { bits, rate, ago, safeUrl, ts } from '$lab/sdk.js';
  import Problems from '$lab/arr/Problems.svelte';
  import Upcoming from '$lab/arr/Upcoming.svelte';
  import { MEDIA, get, upcoming, healthLines, groupOf, torrentStatus, requestState, requestName, playLabel } from './media.js';
  let { ctx } = $props();

  const S = $derived(get(ctx, 'sonarr')), R = $derived(get(ctx, 'radarr')), Q = $derived(get(ctx, 'qbit')), P = $derived(get(ctx, 'prowlarr'));
  const B = $derived(get(ctx, 'bazarr')), J = $derived(get(ctx, 'jellyfin')), SR = $derived(get(ctx, 'seerr'));
  const moving = $derived(Q ? Q.torrents.filter((t) => t.dlspeed > 0 || groupOf(t) === 'downloading').sort((a, b) => b.dlspeed - a.dlspeed) : []);
  const trouble = $derived(Q ? Q.torrents.filter((t) => ['error', 'stalled'].includes(groupOf(t))) : []);
  const backedOff = $derived(P ? P.indexers.filter((x) => x.status === 'bad') : []);
  const health = $derived([...healthLines(ctx), ...backedOff.map((x) => ({ p: '■', s: 'bad', t: `prowlarr · ${x.name} backed off` }))]);
  const stuck = $derived((S?.queue.problems.length || 0) + (R?.queue.problems.length || 0));
  const reqs = $derived(SR?.counts ? [...(SR.pending || []), ...(SR.all || []).filter((r) => r.status !== 'pending')].slice(0, 6) : []);
  const playing = $derived(J ? J.sessions.filter((s) => s.playing) : []);

  const stats = $derived([
    Q && { n: 'down', v: bits(Q.transfer.dl_info_speed) },
    Q && { n: 'downloading', v: Q.counts.downloading, s: 'ok' },
    S && { n: 'tv queue', v: S.queue.total },
    R && { n: 'movie queue', v: R.queue.total },
    (S || R) && { n: 'stuck', v: stuck, s: stuck ? 'warn' : null },
    S && { n: 'tv missing', v: S.missing ?? '–' },
    R && { n: 'movies missing', v: R.missing ?? '–' },
    B && { n: 'subs wanted', v: (B.wantedEps.total ?? 0) + (B.wantedMovies.total ?? 0) },
    SR?.counts && { n: 'requests', v: SR.counts.pending, s: SR.counts.pending ? 'warn' : null },
    J && { n: 'playing', v: playing.length },
  ].filter(Boolean));

  // header buttons: [module, route, body, label, confirm]. ActionButton hides the ones this user may not run.
  const tools = $derived([
    S && ['sonarr', '/api/v3/command', { name: 'MissingEpisodeSearch' }, 'search missing tv', `search every missing episode (${S.missing ?? '?'})? This hits the indexers hard.`],
    R && ['radarr', '/api/v3/command', { name: 'MissingMoviesSearch' }, 'search missing movies', `search every missing movie (${R.missing ?? '?'})?`],
    S && ['sonarr', '/api/v3/command', { name: 'RefreshMonitoredDownloads' }, 'rescan tv downloads'],
    R && ['radarr', '/api/v3/command', { name: 'RefreshMonitoredDownloads' }, 'rescan movie downloads'],
    P && ['prowlarr', '/api/v1/indexer/testall', {}, 'test indexers'],
    J && ['jellyfin', '/Library/Refresh', {}, 'scan libraries'],
  ].filter(Boolean).map(([id, path, body, label, confirm]) => ({ id, path, body, label, confirm, via: ctx.via(id) })).filter((t) => t.via));
  const missing = $derived(MEDIA.filter((id) => !ctx.peer(id)));
  const torrentsView = $derived(['torrents', 'qbit-torrents'].find((v) => ctx.canGo(v)));
</script>

<div class="mv fade">
  <div class="top">
    <span class="cap">~/media</span>
    {#if missing.length}<span class="mono dim note">not loaded: {missing.join(' · ')}</span>{/if}
    <div class="tools">
      {#each tools as t (t.id + t.label)}<ActionButton ctx={t.via} path={t.path} body={t.body} label="{t.id}: {t.label}" icon="play" small confirm={t.confirm ?? false}>{t.label}</ActionButton>{/each}
    </div>
  </div>
  {#if stats.length}<div class="stats"><Stats items={stats} cols={Math.min(stats.length, 10)} /></div>{/if}

  <div class="cols">
    <div class="col">
      {#if S || R}
        <Section title="stuck · failed" src="sonarr + radarr queue">
          <Problems groups={[...(S ? S.queue.problems.map((g) => ({ ...g, app: 'sonarr' })) : []).slice(0, 12), ...(R ? R.queue.problems.map((g) => ({ ...g, app: 'radarr' })) : []).slice(0, 8)]} {ctx} limit={20} empty="" imports={false} />
          {#if !stuck}<span class="mono dim s">● nothing stuck</span>{/if}
        </Section>
      {/if}
      {#if Q}
        {#if trouble.length}
          <Section title="torrents in trouble" src="qbit">
            {#each trouble.slice(0, 8) as t (t.hash)}
              <div class="t row"><Glyph status={torrentStatus(t)} size={10} /><span class="n" title="{t.name} · {t.state}">{t.name}</span><span class="mono dim c">{t.state}</span></div>
            {/each}
          </Section>
        {/if}
        <Section title="downloading · {moving.length}" src="qbit · ↓ {bits(Q.transfer.dl_info_speed)}">
          {#each moving.slice(0, 14) as t (t.hash)}
            {@const pct = Math.floor((t.progress || 0) * 100)}
            <div class="t row dl">
              <Glyph status={torrentStatus(t)} size={10} />
              <span class="n" title={t.name}>{t.name}</span>
              <span class="pb"><Bar value={pct} color="var(--sig)" label="{pct}%" /></span>
              <span class="mono c">{pct}%{t.dlspeed ? ` ↓${rate(t.dlspeed)}` : ''}</span>
            </div>
          {:else}<span class="mono dim s">idle</span>{/each}
          {#if torrentsView}<button class="btn more" onclick={() => ctx.go(torrentsView)}>all {Q.torrents.length} torrents</button>{/if}
        </Section>
      {/if}
    </div>
    <div class="col">
      <Section title="health" src="sonarr radarr prowlarr bazarr">
        <Lines items={health} empty="● every check passes" />
      </Section>
      {#if SR?.counts}
        <Section title="requests" src="seerr">
          {#each reqs as r (r.id)}
            {@const st = requestState(r)}
            {@const seerr = ctx.via('seerr')}
            <div class="q row">
              <Glyph status={st.s} size={10} />
              <div class="m">
                <a class="n" href={safeUrl(r.url)} target="_blank" rel="noopener">{requestName(r)}</a>
                <span class="mono dim c">{r.type === 'tv' ? 'series' : 'movie'} · {st.t}{r.by ? ` · ${r.by}` : ''} · {ago(ts(r.created), ctx.now)} ago</span>
              </div>
              {#if seerr && r.status === 'pending'}
                <span class="acts">
                  <ActionButton ctx={seerr} path="/api/requests/{r.id}/approve" label="approve {requestName(r)}" icon="check" small>approve</ActionButton>
                  <ActionButton ctx={seerr} path="/api/requests/{r.id}/decline" label="decline {requestName(r)}" icon="close" small confirm="decline {requestName(r)}?">decline</ActionButton>
                </span>
              {:else if seerr && r.status === 'failed'}
                <ActionButton ctx={seerr} path="/api/requests/{r.id}/retry" label="retry {requestName(r)}" icon="restart" small>retry</ActionButton>
              {/if}
            </div>
          {:else}<span class="mono dim s">no requests</span>{/each}
        </Section>
      {/if}
      {#if S || R}
        <Section title="upcoming" src="calendar">
          <Upcoming items={upcoming(ctx)} limit={16} {ctx} />
        </Section>
      {/if}
      {#if J}
        <Section title="watching now" src="jellyfin · live">
          {#each playing as s (s.id)}
            <div class="w">
              <span class="mono g" class:sig={!s.paused} class:dim={s.paused}>{s.paused ? '❚❚' : '▶'}</span>
              <div class="m">
                <span class="n">{playLabel(s.playing)}</span>
                <span class="mono dim c">{s.user} · {s.client} · {s.device} · {s.method || '–'}</span>
              </div>
              {#if s.playing.pct != null}<span class="pb"><Bar value={s.playing.pct} color="var(--sig)" /></span>{/if}
            </div>
          {:else}<span class="mono dim s">nobody is watching</span>{/each}
        </Section>
      {/if}
    </div>
  </div>
</div>

<style>
  .top { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 16px 0; }
  .note { font-size: 11px; }
  .tools { display: flex; flex-wrap: wrap; gap: 6px; margin-left: auto; }
  .stats { padding: 12px 20px; border-bottom: 1px solid var(--line); }
  .stats :global(.stats) { grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)) !important; }
  .cols { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); }
  .col { min-width: 0; border-right: 1px solid var(--line); }
  .col:last-child { border-right: none; }
  .s { font-size: 11px; }
  .more { align-self: flex-start; }
  .t { display: grid; grid-template-columns: 12px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 3px 0; border-bottom: 1px solid var(--q); font-size: 12px; }
  .t.dl { grid-template-columns: 12px minmax(0, 1fr) 70px 90px; }
  .n { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12.5px; color: var(--ink); text-decoration: none; }
  a.n:hover { color: var(--sig); }
  .c { font-size: 10.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: right; }
  .q { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--q); }
  .m { display: flex; flex-direction: column; min-width: 0; }
  .m .c { text-align: left; }
  .acts { display: flex; gap: 6px; }
  .w { display: grid; grid-template-columns: 18px minmax(0, 1fr) 64px; gap: 8px; align-items: center; }
  .pb { display: flex; }
  .g { font-size: 11px; }
  @media (max-width: 1100px) { .cols { grid-template-columns: minmax(0, 1fr); } .col { border-right: none; } }
  @media (max-width: 860px) { .t.dl { grid-template-columns: 12px minmax(0, 1fr) 90px; } .t.dl .pb { display: none; } }
</style>
