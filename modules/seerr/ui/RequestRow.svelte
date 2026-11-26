<script>
  // One request: state glyph, title, seasons, state word, download bar; admins get approve/decline/retry.
  import Glyph from '$lab/Glyph.svelte';
  import Bar from '$lab/Bar.svelte';
  import Icon from '$lab/Icon.svelte';
  import { ago, safeUrl } from '$lab/fmt.js';
  import { act, ts } from '$lab/sdk.js';
  import { stateOf, progress, name, seasons } from './sr.js';
  let { r, ctx, by = false, manage = false } = $props();
  const st = $derived(stateOf(r));
  const dl = $derived(progress(r));
  const verb = (v, c) => act(ctx, { path: `/api/requests/${r.id}/${v}`, label: `seerr: ${v} ${name(r)}`, confirm: c });
</script>

<div class="r">
  <Glyph status={st.s} size={10} />
  <div class="m">
    <a class="t" href={safeUrl(r.url)} target="_blank" rel="noopener" title="open in {r.media === 'available' || r.media === 'partial' ? 'Jellyfin' : 'Seerr'}">{name(r)}{#if seasons(r)}<span class="mono dim"> {seasons(r)}</span>{/if}</a>
    <span class="mono dim sub">{r.type === 'tv' ? 'series' : 'movie'} · {st.t}{dl?.eta ? ` · ready ~${new Date(dl.eta * 1000).toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' })}` : ''}{by && r.by ? ` · ${r.by}` : ''} · {ago(ts(r.created), ctx.now)} ago</span>
    {#if dl?.pct != null}<Bar value={dl.pct} color="var(--sig)" height={3} label="{dl.pct}% of {dl.n} download(s)" />{/if}
  </div>
  {#if manage && r.status === 'pending' && ctx.can('POST', `/api/requests/${r.id}/approve`) !== 'no'}
    <span class="acts">
      <button class="btn x" title="approve" aria-label="approve {name(r)}" onclick={() => verb('approve')}><Icon name="check" size={11} /></button>
      <button class="btn x" title="decline" aria-label="decline {name(r)}" onclick={() => verb('decline', `Decline ${name(r)} requested by ${r.by}?`)}><Icon name="close" size={11} /></button>
    </span>
  {:else if manage && r.status === 'failed' && ctx.can('POST', `/api/requests/${r.id}/retry`) !== 'no'}
    <button class="btn x" title="retry" aria-label="retry {name(r)}" onclick={() => verb('retry')}><Icon name="restart" size={11} /></button>
  {/if}
</div>

<style>
  .r { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--q); }
  .m { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .t { color: var(--ink); text-decoration: none; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .t:hover { color: var(--sig); }
  .sub { font-size: 10.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .acts { display: flex; gap: 4px; }
  .x { padding: 3px 6px; }
</style>
