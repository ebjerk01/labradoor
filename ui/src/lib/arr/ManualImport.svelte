<script>
  // Manual import of one stuck download: the files the app found for it, what it would import them as, the ones it
  // cannot place (nothing matched / rejected), and one button that sends the ManualImport command for the chosen ones.
  import { lazy, forget, bytes } from '../sdk.js';
  import Lazy from '../Lazy.svelte';
  import Glyph from '../Glyph.svelte';
  import ActionButton from '../ActionButton.svelte';
  import { A, importable, importPayload, targetOf, fileName } from './logic.js';
  let { ctx, downloadId, onclose } = $props();
  const cands = lazy(() => ctx, () => `${A}/manualimport`, { query: () => ({ downloadId, filterExistingFiles: 'true' }) });
  let off = $state({}); // path → true when unticked
  const chosen = (list) => (list || []).filter((c) => importable(ctx.id, c) && !off[c.path]);
</script>

<div class="mi">
  <Lazy of={cands} empty="the app finds nothing to import for this download">
    {#snippet children(list)}
      {#each list as c (c.path)}
        {@const ok = importable(ctx.id, c)}
        <label class="f" class:no={!ok}>
          <input type="checkbox" disabled={!ok} checked={ok && !off[c.path]} onchange={(e) => (off[c.path] = !e.currentTarget.checked)} aria-label="import {fileName(c.path)}" />
          <Glyph status={!ok ? 'bad' : c.rejections?.length ? 'warn' : 'ok'} size={10} />
          <span class="n" title={c.path}>{fileName(c.path)}</span>
          <span class="mono dim t" title={c.rejections?.map((r) => r.reason ?? r).join(' · ') || ''}>{ok ? targetOf(ctx.id, c) : 'not matched'}</span>
          <span class="mono dim q">{c.quality?.quality?.name || ''} · {bytes(c.size)}</span>
          {#if c.rejections?.length}<span class="mono dim why">{c.rejections.map((r) => r.reason ?? r).join(' · ')}</span>{/if}
        </label>
      {/each}
      <div class="bar">
        <ActionButton {ctx} path="{A}/command" label="import {chosen(list).length} file{chosen(list).length === 1 ? '' : 's'}" icon="download" primary small
          disabled={!chosen(list).length} confirm body={() => importPayload(ctx.id, chosen(list))}
          ok="import queued" done={() => { forget(`${ctx.id}:problems`); onclose?.(); }} />
        <button class="btn sm" onclick={() => onclose?.()}>close</button>
        <span class="mono dim s">files the app cannot place need fixing in {ctx.id} itself</span>
      </div>
    {/snippet}
  </Lazy>
</div>

<style>
  .mi { display: flex; flex-direction: column; gap: 4px; padding: 6px 0 8px 22px; border-bottom: 1px solid var(--q); }
  .f { display: grid; grid-template-columns: 16px 12px minmax(0, 1fr) auto; gap: 4px 8px; align-items: center; font-size: 12px; }
  .f.no { opacity: .7; }
  .n { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .t, .q { font-size: 10.5px; white-space: nowrap; }
  .t { max-width: 22ch; overflow: hidden; text-overflow: ellipsis; }
  .why { grid-column: 3 / -1; font-size: 10.5px; overflow-wrap: anywhere; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 4px; }
  .s { font-size: 10.5px; }
  .btn.sm { padding: 3px 8px; font-size: 11px; }
  @media (max-width: 860px) { .q { display: none; } }
</style>
