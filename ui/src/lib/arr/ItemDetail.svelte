<script>
  // One series / movie: monitor, quality profile, search (the whole thing, a season, an episode), interactive search,
  // delete (owner; with or without files). Episodes load when a season is opened.
  import { lazy, bytes, day, ts } from '../sdk.js';
  import Lazy from '../Lazy.svelte';
  import Glyph from '../Glyph.svelte';
  import ActionButton from '../ActionButton.svelte';
  import Releases from './Releases.svelte';
  import { A, APPS, bySeason, releaseQuery } from './logic.js';
  let { ctx, item, profiles = [], onchange, onclose } = $props();
  const a = $derived(APPS[ctx.id]);
  const tv = $derived(ctx.id === 'sonarr');
  const eps = lazy(() => ctx, () => (tv ? `${A}/episode` : null), { query: () => ({ seriesId: item.id }), pick: bySeason });
  let openSeason = $state(null);
  let searching = $state(null); // the query of the interactive search that is open
  let profile = $state(item.qualityProfileId);
  const after = () => { onchange?.(); eps.reload?.(); };
  const edit = (patch) => ({ [tv ? 'seriesIds' : 'movieIds']: [item.id], ...patch });
  const same = (q) => JSON.stringify(searching) === JSON.stringify(q);
</script>

<div class="d">
  <div class="head">
    <span class="t">{item.title}{#if item.year}<span class="dim"> ({item.year})</span>{/if}</span>
    <button class="btn sm" onclick={() => onclose?.()} aria-label="close {item.title}">close</button>
  </div>
  <span class="mono dim s" title={item.path}>{item.path} · {bytes(item.size)}{item.status ? ` · ${item.status}` : ''}</span>

  <div class="acts">
    <ActionButton {ctx} method="PUT" path="{A}/{a.item}/editor" body={edit({ monitored: !item.monitored })}
      label="{item.monitored ? 'unmonitor' : 'monitor'} {item.title}" icon={item.monitored ? 'close' : 'check'} small done={after}>
      {item.monitored ? 'unmonitor' : 'monitor'}</ActionButton>
    <ActionButton {ctx} path="{A}/command" body={tv ? { name: 'SeriesSearch', seriesId: item.id } : { name: 'MoviesSearch', movieIds: [item.id] }}
      label="search {item.title}" icon="search" small confirm={tv ? `search every missing episode of ${item.title}?` : false}>search{tv ? ' series' : ''}</ActionButton>
    {#if !tv}
      <button class="btn sm" aria-pressed={same({ movieId: item.id })} onclick={() => (searching = same({ movieId: item.id }) ? null : { movieId: item.id })}>interactive search</button>
    {/if}
    <span class="prof">
      <select class="field" bind:value={profile} aria-label="quality profile">
        {#each profiles as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
      </select>
      <ActionButton {ctx} method="PUT" path="{A}/{a.item}/editor" body={() => edit({ qualityProfileId: Number(profile) })}
        label="set quality profile of {item.title}" small disabled={profile === item.qualityProfileId} done={after}>set profile</ActionButton>
    </span>
    <ActionButton {ctx} method="DELETE" path="{A}/{a.item}/{item.id}" query={{ deleteFiles: false, addImportListExclusion: false }}
      label="delete {item.title} (keep files)" icon="close" small confirm="delete {item.title}, keep files?"
      done={() => { onchange?.(); onclose?.(); }}>delete</ActionButton>
    <ActionButton {ctx} method="DELETE" path="{A}/{a.item}/{item.id}" query={{ deleteFiles: true, addImportListExclusion: false }}
      label="delete {item.title} and its files" icon="close" small confirm="delete {item.title} AND its files?"
      done={() => { onchange?.(); onclose?.(); }}>delete + files</ActionButton>
  </div>

  {#if searching && !tv}<Releases {ctx} query={searching} onclose={() => (searching = null)} />{/if}

  {#if tv}
    <Lazy of={eps} empty="no episodes">
      {#snippet children(seasons)}
        {#each seasons as s (s.n)}
          <div class="season">
            <button class="lnk mono" aria-expanded={openSeason === s.n} onclick={() => (openSeason = openSeason === s.n ? null : s.n)}>
              {openSeason === s.n ? '▾' : '▸'} {s.n === 0 ? 'specials' : `season ${s.n}`} · {s.have}/{s.eps.length}</button>
            {#if openSeason === s.n}
              <span class="acts">
                <ActionButton {ctx} path="{A}/command" body={{ name: 'SeasonSearch', seriesId: item.id, seasonNumber: s.n }}
                  label="search {item.title} season {s.n}" icon="search" small>search season</ActionButton>
                <button class="btn sm" aria-pressed={same({ seriesId: item.id, seasonNumber: s.n })}
                  onclick={() => (searching = same({ seriesId: item.id, seasonNumber: s.n }) ? null : { seriesId: item.id, seasonNumber: s.n })}>interactive search</button>
              </span>
            {/if}
          </div>
          {#if openSeason === s.n}
            {#each s.eps as e (e.id)}
              {@const q = { episodeId: e.id }}
              <div class="ep row">
                <Glyph status={e.hasFile ? 'ok' : e.monitored ? 'warn' : 'off'} size={10} />
                <span class="mono dim n">{String(e.n).padStart(2, '0')}</span>
                <span class="en" title={e.title}>{e.title || 'TBA'}</span>
                <span class="mono dim air">{e.air ? day(ts(e.air)) : ''}</span>
                <span class="acts">
                  <ActionButton {ctx} method="PUT" path="{A}/episode/monitor" body={{ episodeIds: [e.id], monitored: !e.monitored }}
                    label="{e.monitored ? 'unmonitor' : 'monitor'} {item.title} episode {s.n}x{e.n}" small done={after}>{e.monitored ? 'unmonitor' : 'monitor'}</ActionButton>
                  <ActionButton {ctx} path="{A}/command" body={{ name: 'EpisodesSearch', episodeIds: [e.id] }}
                    label="search {item.title} episode {s.n}x{e.n}" icon="search" small>search</ActionButton>
                  <button class="btn sm" aria-pressed={same(q)} onclick={() => (searching = same(q) ? null : q)}>interactive</button>
                </span>
              </div>
            {/each}
          {/if}
        {/each}
        {#if searching}<Releases {ctx} query={searching} onclose={() => (searching = null)} />{/if}
      {/snippet}
    </Lazy>
  {/if}
</div>

<style>
  .d { display: flex; flex-direction: column; gap: 8px; padding: 12px 0; }
  .head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
  .t { font-size: 15px; }
  .s { font-size: 10.5px; overflow-wrap: anywhere; }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .prof { display: inline-flex; gap: 6px; align-items: center; }
  .prof select { padding: 3px 6px; font-size: 11.5px; min-width: 0; }
  .season { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; padding-top: 6px; border-top: 1px solid var(--q); }
  .ep { display: grid; grid-template-columns: 14px 24px minmax(0, 1fr) auto auto; gap: 8px; align-items: center; padding: 2px 0 2px 12px; font-size: 12px; }
  .en { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .n, .air { font-size: 10.5px; }
  .btn.sm { padding: 3px 8px; font-size: 11px; }
  @media (max-width: 860px) { .ep { grid-template-columns: 14px 24px minmax(0, 1fr); } .ep .air { display: none; } .ep .acts { grid-column: 1 / -1; } }
</style>
