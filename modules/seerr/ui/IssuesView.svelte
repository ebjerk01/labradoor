<script>
  // ~/seerr-issues — problems people reported in Seerr (bad video / audio / subtitles): read, comment, resolve, reopen.
  import { untrack } from 'svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago } from '$lab/fmt.js';
  import { act, ts } from '$lab/sdk.js';
  import Poster from './Poster.svelte';
  import { name } from './sr.js';
  let { data, ctx } = $props();

  let filter = $state('open');
  let res = $state(null);
  let err = $state('');
  let open = $state(null);
  let thread = $state(null);
  let msg = $state('');

  async function load() {
    try { res = await ctx.api.get('/api/issues', { filter, take: 50 }); err = ''; } catch (e) { err = e.body?.error || e.message; }
  }
  $effect(() => { filter; untrack(load); });
  $effect(() => { data?.issues?.open; untrack(load); });

  async function expand(i) {
    if (open === i.id) { open = null; return; }
    open = i.id;
    thread = null;
    msg = '';
    try { thread = await ctx.api.get(`/api/issues/${i.id}`); } catch (e) { ctx.notify(e.message, 'bad'); }
  }
  async function comment(i, e) {
    e.preventDefault();
    if (!msg.trim()) return;
    if (await act(ctx, { path: `/api/issues/${i.id}/comment`, body: { message: msg.trim() }, label: `seerr: comment on issue #${i.id}` })) {
      msg = '';
      thread = await ctx.api.get(`/api/issues/${i.id}`);
      load();
    }
  }
  async function setState(i, v) {
    if (await act(ctx, { path: `/api/issues/${i.id}/${v}`, label: `seerr: ${v} issue #${i.id} (${name(i)})` })) { load(); if (open === i.id) thread = await ctx.api.get(`/api/issues/${i.id}`); }
  }
  const where = (i) => (i.season ? `S${i.season}${i.episode ? 'E' + i.episode : ''}` : '');
</script>

<div class="iv fade">
  <div class="bar">
    <span class="cap">~/seerr-issues{res ? ` · ${res.counts.open} open · ${res.counts.closed} resolved` : ''}</span>
    <div class="seg" role="group" aria-label="Filter">
      {#each ['open', 'resolved', 'all'] as f (f)}<button aria-pressed={filter === f} onclick={() => (filter = f)}>{f}</button>{/each}
    </div>
    {#if res}<span class="mono dim s">{['video', 'audio', 'subtitles', 'others'].map((k) => `${k} ${res.counts[k]}`).join(' · ')}</span>{/if}
  </div>
  {#if err}<p class="mono bad">■ {err}</p>{/if}
  {#if !res && !err}<p class="mono dim spin">loading </p>{/if}
  <div class="list">
    {#each res?.results || [] as i (i.id)}
      <div class="r">
        <Glyph status={i.status === 'open' ? 'warn' : 'ok'} size={10} />
        <Poster src={i.poster} kind={i.mediaType} w={28} />
        <div class="m">
          <span class="t"><button class="lnk" onclick={() => ctx.open(i.object)}>{name(i)}</button><span class="mono dim"> {where(i)}</span></span>
          <span class="mono dim sub">#{i.id} · {i.type} · {i.status} · {i.by} · {ago(ts(i.created), ctx.now)} ago · {i.comments} comment{i.comments === 1 ? '' : 's'}</span>
        </div>
        <span class="acts">
          {#if i.status === 'open' && ctx.can('POST', `/api/issues/${i.id}/resolve`) !== 'no'}<button class="btn x" title="resolve" aria-label="resolve issue {i.id}" onclick={() => setState(i, 'resolve')}><Icon name="check" size={11} /></button>
          {:else if i.status !== 'open' && ctx.can('POST', `/api/issues/${i.id}/reopen`) !== 'no'}<button class="btn x" title="reopen" aria-label="reopen issue {i.id}" onclick={() => setState(i, 'reopen')}><Icon name="restart" size={11} /></button>{/if}
          <button class="btn x" aria-expanded={open === i.id} aria-label="comments on issue {i.id}" onclick={() => expand(i)}><Icon name="mail" size={11} /></button>
        </span>
        {#if open === i.id}
          <div class="th">
            {#if !thread}<span class="mono dim spin s">loading </span>
            {:else}
              {#each thread.thread as c (c.id)}<div class="c"><span class="mono dim s">{c.by} · {ago(ts(c.at), ctx.now)} ago</span><p>{c.message}</p></div>{/each}
            {/if}
            {#if ctx.can('POST', `/api/issues/${i.id}/comment`) !== 'no'}
              <form class="add" onsubmit={(e) => comment(i, e)}>
                <textarea class="field" rows="2" maxlength="4000" placeholder="comment (posted as {data?.me?.name || 'Seerr owner'})" bind:value={msg} aria-label="Comment"></textarea>
                <button class="btn primary" disabled={!msg.trim()}>post</button>
              </form>
            {/if}
          </div>
        {/if}
      </div>
    {:else}
      {#if res}<span class="mono dim s">no {filter === 'all' ? '' : filter} issues</span>{/if}
    {/each}
  </div>
</div>

<style>
  .iv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 10px; }
  .bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .s { font-size: 11px; }
  .list { display: flex; flex-direction: column; }
  .r { display: grid; grid-template-columns: 12px 28px minmax(0, 1fr) auto; gap: 4px 10px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--q); }
  .m { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .t { font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 10.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .acts { display: flex; gap: 4px; }
  .x { padding: 3px 6px; }
  .th { grid-column: 3 / -1; display: flex; flex-direction: column; gap: 8px; padding: 4px 0 8px; }
  .c p { margin: 2px 0 0; font-size: 12.5px; white-space: pre-wrap; }
  .add { display: flex; gap: 8px; align-items: flex-end; }
  textarea.field { flex: 1; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 12.5px; resize: vertical; }
  @media (max-width: 520px) { .th { grid-column: 1 / -1; } }
</style>
