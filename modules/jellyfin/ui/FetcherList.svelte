<script>
  // Provider list: on/off + order (Jellyfin keeps an "enabled" list and an "order" list per kind; `inverted` = a "disabled" list).
  let { title, all = [], enabled = $bindable([]), order = $bindable(null), inverted = false, disabled = false } = $props();
  const sorted = $derived.by(() => {
    const o = order || [];
    return [...all].sort((a, b) => (o.indexOf(a) < 0 ? 1e3 : o.indexOf(a)) - (o.indexOf(b) < 0 ? 1e3 : o.indexOf(b)));
  });
  const on = (n) => (inverted ? !enabled.includes(n) : enabled.includes(n));
  function toggle(n) {
    const has = enabled.includes(n);
    enabled = has ? enabled.filter((x) => x !== n) : [...enabled, n];
  }
  function move(n, by) {
    const o = [...sorted];
    const i = o.indexOf(n), j = i + by;
    if (j < 0 || j >= o.length) return;
    [o[i], o[j]] = [o[j], o[i]];
    order = o;
  }
</script>

{#if all.length}
  <div class="fl">
    <span class="cap">{title}</span>
    {#each sorted as n, i (n)}
      <div class="f">
        <label class="mono"><input type="checkbox" checked={on(n)} {disabled} onchange={() => toggle(n)} /> {n}</label>
        {#if order && all.length > 1}
          <button class="lnk mono a" type="button" disabled={disabled || i === 0} aria-label="move {n} up" onclick={() => move(n, -1)}>↑</button>
          <button class="lnk mono a" type="button" disabled={disabled || i === sorted.length - 1} aria-label="move {n} down" onclick={() => move(n, 1)}>↓</button>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .fl { display: flex; flex-direction: column; gap: 2px; min-width: 180px; flex: 1; }
  .f { display: flex; align-items: center; gap: 6px; }
  .f label { flex: 1; font-size: 11.5px; display: flex; gap: 5px; align-items: center; min-width: 0; }
  .a { font-size: 11px; padding: 0 3px; color: var(--dim); }
  .a:disabled { opacity: .3; }
</style>
