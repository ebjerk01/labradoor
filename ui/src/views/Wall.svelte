<script>
  // ~/wall — every module's tiles. Worst first (■ bad, ▲ warn, then the rest), each band in the user's own order
  // (edit mode shows and moves the plain user order). A tile is as tall as its content, up to its declared height.
  import { lab } from '$lab/lab.svelte.js';
  import Icon from '$lab/Icon.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import { worst, RANK } from '$lab/fmt.js';

  let edit = $state(false);
  const hidden = $derived(lab.prefs['wall.hidden'] || []);
  // a tile's severity = its module's: backend down → bad, load error → warn, else its worst open alert
  const sev = $derived.by(() => {
    const out = {};
    for (const a of lab.alerts) out[a.module] = worst(out[a.module], a.status);
    for (const m of lab.active) {
      if (lab.registry?.health?.[m.id]?.up === false) out[m.id] = 'bad';
      else if (lab.errors[m.id]) out[m.id] = worst(out[m.id], 'warn');
    }
    return out;
  });
  const band = (t) => { const s = sev[t.module]; return s === 'bad' ? 2 : s === 'warn' ? 1 : 0; };
  const shown = $derived.by(() => {
    const list = lab.tiles.filter((t) => edit || !hidden.includes(t.key)).map((t, i) => ({ t, i }));
    if (!edit) list.sort((a, b) => band(b.t) - band(a.t) || a.i - b.i);
    return list.map((x) => x.t);
  });

  function toggle(key) {
    lab.savePref('wall.hidden', hidden.includes(key) ? hidden.filter((k) => k !== key) : [...hidden, key]);
  }
  function move(key, d) {
    const keys = lab.tiles.map((t) => t.key);
    const i = keys.indexOf(key), j = i + d;
    if (j < 0 || j >= keys.length) return;
    [keys[i], keys[j]] = [keys[j], keys[i]];
    lab.savePref('wall.order', keys);
  }

  // grid rows are 4px; a tile spans ceil((height + gap) / 4) of them. Its height is its content's natural height,
  // capped at the declared h × 136px; content that needs the full height (scrolling lists) keeps it.
  const UNIT = 4, GAP = 10, ROW = 136;
  const maxPx = (t) => (t.h || 1) * ROW + ((t.h || 1) - 1) * GAP;
  let spans = $state({});
  let full = $state({});
  function fit(node, t) {
    let key = t.key, cap = maxPx(t);
    const art = node.closest('.tile');
    const measure = () => {
      if (full[key]) return;
      const chrome = art.offsetHeight - art.querySelector('.body').offsetHeight;  // header + padding + border
      const want = Math.ceil(node.offsetHeight + chrome);
      if (want >= cap) { full[key] = true; spans[key] = Math.ceil((cap + GAP) / UNIT); return; }
      spans[key] = Math.ceil((Math.max(want, 56) + GAP) / UNIT);
    };
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return {
      update(nt) { if (nt.key !== key || maxPx(nt) !== cap) { key = nt.key; cap = maxPx(nt); delete full[key]; measure(); } },
      destroy() { ro.disconnect(); },
    };
  }
  const span = (t) => spans[t.key] || Math.ceil((maxPx(t) + GAP) / UNIT);
</script>

<div class="bar">
  <span class="cap">~/wall · {shown.length} tiles{#if !edit} · worst first{/if}</span>
  <button class="btn" class:primary={edit} onclick={() => (edit = !edit)}><Icon name="wall" size={13} />{edit ? 'done' : 'edit'}</button>
</div>
<section class="wall fade" aria-label="Wall">
  {#each shown as t (t.key)}
    {@const C = t.component}
    {@const s = sev[t.module]}
    <article class="tile" class:off={hidden.includes(t.key)} class:bad={s === 'bad'} class:warn={s === 'warn'}
      style:grid-column="span {t.w || 2}" style:grid-row="span {span(t)}" style:max-height="{maxPx(t)}px">
      <div class="th"><span class="cap">{#if RANK[s] >= RANK.warn}<Glyph status={s} size={10} /> {/if}<span class="faint">~/</span>{t.label}</span>
        {#if edit}
          <span class="ed">
            <button class="btn" aria-label="Move left" onclick={() => move(t.key, -1)}>‹</button>
            <button class="btn" aria-label="Move right" onclick={() => move(t.key, 1)}>›</button>
            <button class="btn" onclick={() => toggle(t.key)}>{hidden.includes(t.key) ? 'show' : 'hide'}</button>
          </span>
        {:else}<span class="mono faint src">{t.module}</span>{/if}
      </div>
      <div class="body">
        <div class="fit" class:full={full[t.key]} use:fit={t}>
          {#if lab.data[t.module] != null}
            <C data={lab.data[t.module]} ctx={lab.ctx(t.module)} {...(t.props || {})} />
          {:else if lab.denied[t.module]}<div class="mono dim wait">○ no access · no account in {t.module}</div>
          {:else if lab.errors[t.module]}<div class="mono dim wait"><span class="bad">■</span> {lab.errors[t.module]}</div>
          {:else}<div class="mono dim spin wait">loading</div>{/if}
        </div>
      </div>
    </article>
  {:else}
    <p class="mono dim">no tiles — none of your modules has any yet</p>
  {/each}
</section>

<style>
  .bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px 0; }
  .wall { padding: 12px 16px 6px; display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); grid-auto-rows: 4px; column-gap: 10px;
    row-gap: 0; grid-auto-flow: dense; align-items: start; }
  .tile { background: var(--panel); border: 1px solid var(--line); border-radius: 4px; padding: 12px 14px; display: flex; flex-direction: column;
    gap: 8px; min-width: 0; overflow: hidden; margin-bottom: 10px; height: calc(100% - 10px); }
  .tile:hover { border-color: var(--faint); }
  .tile.warn { border-top: 2px solid var(--warn); }
  .tile.bad { border-top: 2px solid var(--bad); }
  .tile.off { opacity: .4; border-style: dashed; }
  .th { display: flex; justify-content: space-between; align-items: center; gap: 6px; flex: none; }
  .src { font-size: 10px; }
  .ed { display: flex; gap: 4px; }
  .ed .btn { padding: 2px 7px; }
  .body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  /* natural height while measuring; tiles whose content wants the whole box get the old flex behaviour back */
  .fit { display: flex; flex-direction: column; flex: none; min-height: 0; }
  .fit.full { flex: 1; }
  .wait { display: inline-flex; flex-direction: row-reverse; justify-content: flex-end; gap: 6px; font-size: 12px; }
  @media (max-width: 900px) { .wall { grid-template-columns: repeat(4, minmax(0, 1fr)); } .tile { grid-column: span 4 !important; } }
</style>
