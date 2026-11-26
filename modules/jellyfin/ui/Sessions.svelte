<script>
  // Live sessions (read each refresh, never stored): who · what · how (direct / transcode + why).
  import Bar from '$lab/Bar.svelte';
  import { ago } from '$lab/fmt.js';
  import { playLabel } from './jf.js';
  let { sessions = [], idle = true, ctx = null } = $props();
  const now = $derived(ctx ? ctx.now : Date.now() / 1000);
  const shown = $derived(sessions.filter((s) => s.playing || idle).sort((a, b) => !!b.playing - !!a.playing || (b.last || 0) - (a.last || 0)));
</script>

<div class="ss">
  {#each shown as s (s.id)}
    <div class="s">
      <span class="mono g" class:sig={s.playing && !s.paused} class:dim={!s.playing || s.paused}>{s.playing ? (s.paused ? '❚❚' : '▶') : '·'}</span>
      <div class="m">
        <span class="t">{#if s.playing}{playLabel(s.playing)}{:else}<span class="dim">idle</span>{/if}</span>
        <span class="mono dim sub">{s.user} · {s.client} · {s.device}{s.playing ? '' : ` · ${ago(s.last, now)} ago`}</span>
        {#if s.playing}
          <span class="mono sub" class:warn={s.method === 'Transcode'} title={s.transcode?.reasons?.join(', ') || ''}>
            {s.method || '–'}{#if s.transcode} · v {s.transcode.video} a {s.transcode.audio}{s.transcode.hw ? ` · ${s.transcode.hw}` : ''}{s.transcode.reasons.length ? ` · ${s.transcode.reasons.join(' ')}` : ''}{/if}
          </span>
        {/if}
      </div>
      {#if s.playing?.pct != null}<span class="p"><Bar value={s.playing.pct} color="var(--sig)" /></span>{/if}
    </div>
  {:else}
    <span class="mono dim e">nobody is watching</span>
  {/each}
</div>

<style>
  .ss { display: flex; flex-direction: column; gap: 6px; }
  .s { display: grid; grid-template-columns: 18px minmax(0, 1fr) 64px; gap: 8px; align-items: center; }
  .m { display: flex; flex-direction: column; min-width: 0; }
  .t, .sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .t { font-size: 12.5px; }
  .sub, .e { font-size: 10.5px; }
  .p { display: flex; }
  .g { font-size: 11px; }
</style>
