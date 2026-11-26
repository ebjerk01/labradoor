<script>
  // Facet on a requested movie / series (object seerr:<type>:<tmdb>): library state per season, requests, downloads and
  // links to Jellyfin, Seerr and the Sonarr/Radarr entry (+ the lab sonarr/radarr object). Actions sit in the panel.
  import { untrack } from 'svelte';
  import Section from '$lab/Section.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Bar from '$lab/Bar.svelte';
  import { ts } from '$lab/sdk.js';
  import { ago, safeUrl } from '$lab/fmt.js';
  import Poster from './Poster.svelte';
  import { mediaState } from './sr.js';
  let { object, ctx } = $props();
  let d = $state(null);
  let err = $state('');
  const oid = $derived(String(object.id));  // a string: the panel's object is rebuilt every refresh, the id is not
  const parts = $derived(oid.split(':'));
  const isMedia = $derived(object.type === 'seerr-media');
  $effect(() => {
    const [, type, tmdb] = oid.split(':');
    if (!isMedia) return;
    untrack(async () => {
      d = null;
      try { d = await ctx.api.get(`/api/${type}/${tmdb}`); err = ''; } catch (e) { err = e.body?.error || e.message; }
    });
  });
  const app = $derived(parts[1] === 'tv' ? 'sonarr' : 'radarr');
  const st = $derived(mediaState(d?.media?.status));
</script>

{#if object.type === 'seerr-media'}
  <Section title="seerr" src="seerr{d?.media?.id ? ` · media #${d.media.id}` : ''}">
    {#if err}<span class="mono bad s">■ {err}</span>
    {:else if !d}<span class="mono dim s spin">loading </span>
    {:else}
      <div class="top">
        <Poster src={d.poster} kind={d.type} w={64} />
        <div class="i">
          <span class="mono s"><Glyph status={st.s} size={10} /> {st.t || 'not in the library'}{d.media.status4k !== 'unknown' ? ` · 4K ${mediaState(d.media.status4k).t}` : ''}</span>
          <span class="mono dim s">{d.type === 'tv' ? 'series' : 'movie'}{d.year ? ` · ${d.year}` : ''}{d.genres.length ? ` · ${d.genres.slice(0, 3).join(', ')}` : ''}{d.media.added ? ` · added ${ago(ts(d.media.added), ctx.now)} ago` : ''}</span>
          <span class="links mono s">
            {#if d.media.jellyfin}<a href={safeUrl(d.media.jellyfin)} target="_blank" rel="noopener">jellyfin ↗</a>{/if}
            <a href={safeUrl(d.seerr)} target="_blank" rel="noopener">seerr ↗</a>
            {#if d.media.service}<a href={safeUrl(d.media.service)} target="_blank" rel="noopener">{app} ↗</a>{/if}
            {#if ctx.object(app) && ctx.role !== 'guest'}<button class="lnk" onclick={() => ctx.open(app)}>{app} →</button>{/if}
          </span>
        </div>
      </div>
      {#if d.seasons?.length}
        <div class="seas mono s">
          {#each d.seasons as s (s.n)}{@const ms = mediaState(s.status)}<span title="{s.name} · {s.episodes} episodes · {ms.t || 'not requested'}"><Glyph status={ms.s} size={9} />S{s.n}</span>{/each}
        </div>
      {/if}
      {#each d.media.requests as r (r.id)}
        <span class="mono s">#{r.id} · {r.status}{r.is4k ? ' · 4K' : ''}{r.seasons.length ? ` · S${r.seasons.join(',')}` : ''} · {r.by} · {ago(ts(r.created), ctx.now)} ago</span>
      {/each}
      {#each d.media.downloads as dl, i (i)}
        <div class="dl"><span class="mono dim s ell">{dl.title}</span>{#if dl.progress != null}<Bar value={dl.progress * 100} color="var(--sig)" height={3} label="{Math.round(dl.progress * 100)}%" />{/if}</div>
      {/each}
      {#if d.media.issues}<span class="mono warn s">▲ {d.media.issues} issue{d.media.issues > 1 ? 's' : ''} — see ~/seerr-issues</span>{/if}
    {/if}
  </Section>
{/if}

<style>
  .top { display: flex; gap: 10px; }
  .i { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .s { font-size: 11px; }
  .links { display: flex; gap: 10px; flex-wrap: wrap; }
  .seas { display: flex; flex-wrap: wrap; gap: 3px 10px; }
  .seas span { display: inline-flex; gap: 3px; align-items: center; }
  .dl { display: grid; grid-template-columns: minmax(0, 1fr) 80px; gap: 8px; align-items: center; }
  .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
