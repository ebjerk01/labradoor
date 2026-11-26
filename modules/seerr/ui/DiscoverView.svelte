<script>
  // ~/seerr-discover — search + trending / popular / upcoming with posters; pick one to see it and request it.
  // Everyone with a linked Seerr account (guests too: they request as themselves).
  import { untrack } from 'svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import Poster from './Poster.svelte';
  import Detail from './Detail.svelte';
  import { mediaState, quotaText } from './sr.js';
  let { data, ctx } = $props();

  const LISTS = [['trending', 'trending'], ['movies', 'movies'], ['tv', 'series'], ['upcoming', 'upcoming'], ['upcoming-tv', 'new tv']];
  let list = $state('trending');
  let q = $state('');
  let items = $state([]);
  let page = $state(1);
  let pages = $state(0);
  let loading = $state(false);
  let err = $state('');
  let sel = $state(null);      // {type, tmdb}
  let person = $state(null);   // person detail
  let timer;
  const me = $derived(data?.me || {});
  const blocked = $derived(data && !me.linked && ctx.role === 'guest');

  async function fetchPage(p) {
    loading = true;
    err = '';
    try {
      const term = q.trim();
      const r = term.length >= 2 ? await ctx.api.get('/api/search', { q: term, page: p }) : await ctx.api.get(`/api/discover/${list}`, { page: p });
      items = p === 1 ? r.results : [...items, ...r.results];
      page = r.page || p;
      pages = r.pages || 0;
    } catch (e) { err = e.body?.error || e.message; }
    loading = false;
  }
  $effect(() => { list; if (!blocked) untrack(() => { person = null; fetchPage(1); }); });
  function typed() {
    clearTimeout(timer);
    timer = setTimeout(() => { person = null; fetchPage(1); }, 350);
  }
  async function pick(it) {
    if (it.type === 'person') {
      sel = null;
      try { person = await ctx.api.get(`/api/person/${it.id}`); } catch (e) { ctx.notify(e.message, 'bad'); }
      return;
    }
    sel = { type: it.type, tmdb: it.tmdb };
    requestAnimationFrame(() => document.getElementById('sr-detail')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
  }
  const shown = $derived(person ? person.credits : items);
</script>

<div class="dv fade">
  <div class="bar">
    <span class="cap">~/seerr-discover</span>
    <input class="field mono q" type="search" placeholder="search movies, series, people" bind:value={q} oninput={typed} aria-label="Search" disabled={blocked} />
    <div class="seg" role="group" aria-label="Lists">
      {#each LISTS as [id, label] (id)}<button aria-pressed={list === id && !q.trim()} onclick={() => { q = ''; list = id; }}>{label}</button>{/each}
    </div>
    {#if me.linked && me.quota}<span class="mono dim s">{me.name} · quota {quotaText(me.quota)}</span>{/if}
  </div>

  {#if blocked}<p class="mono dim">○ no Seerr account is linked to you yet — ask owner.</p>{/if}
  {#if sel}<div id="sr-detail"><Detail type={sel.type} tmdb={sel.tmdb} {ctx} {data} onclose={() => (sel = null)} /></div>{/if}
  {#if person}
    <div class="person">
      <Poster src={person.poster} kind="person" w={56} />
      <div><span class="t">{person.name}</span><span class="mono dim s"> {person.dept || ''}{person.born ? ` · ${person.born.slice(0, 4)}` : ''} · {person.credits.length} titles</span>
        <button class="btn x" aria-label="back" onclick={() => (person = null)}><Icon name="close" size={11} /></button></div>
    </div>
  {/if}
  {#if err}<p class="mono bad">■ {err}</p>{/if}

  <div class="grid">
    {#each shown as it, i (it.type + (it.tmdb ?? it.id) + ':' + i)}
      {@const ms = mediaState(it.status)}
      <button class="card" class:on={sel && sel.tmdb === it.tmdb && sel.type === it.type} onclick={() => pick(it)} title={it.title}>
        <span class="pw"><Poster src={it.poster} kind={it.type} />{#if ms.t}<span class="badge"><Glyph status={ms.s} size={9} /></span>{/if}</span>
        <span class="ct">{it.title}</span>
        <span class="mono dim cs">{it.type === 'person' ? it.dept || 'person' : `${it.type === 'tv' ? 'tv' : 'mv'}${it.year ? ' ' + it.year : ''}${it.rating ? ' ★' + it.rating : ''}`}{it.role && person ? ` · ${it.role}` : ''}</span>
      </button>
    {:else}
      {#if !loading && !blocked}<span class="mono dim s">nothing found</span>{/if}
    {/each}
  </div>
  {#if loading}<p class="mono dim spin">loading </p>
  {:else if !person && page < pages && shown.length}<button class="btn more" onclick={() => fetchPage(page + 1)}>more</button>{/if}
</div>

<style>
  .dv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 12px; }
  .bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .q { max-width: 340px; flex: 1 1 200px; padding: 6px 9px; font-size: 12.5px; }
  .seg { flex-wrap: wrap; }
  .s { font-size: 11px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 12px 10px; }
  .card { display: flex; flex-direction: column; gap: 3px; border: none; background: none; padding: 0; text-align: left; min-width: 0; color: var(--ink); }
  .card:hover .ct, .card.on .ct { color: var(--sig); }
  .card.on .pw { outline: 2px solid var(--sig); outline-offset: 1px; }
  .pw { position: relative; display: block; border-radius: 3px; }
  .badge { position: absolute; top: 4px; left: 4px; background: var(--bg); border-radius: 2px; padding: 0 3px; line-height: 14px; }
  .ct { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cs { font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .person { display: flex; gap: 10px; align-items: center; }
  .person .t { font-size: 14px; font-weight: 500; }
  .x { padding: 2px 5px; margin-left: 6px; }
  .more { align-self: center; }
</style>
