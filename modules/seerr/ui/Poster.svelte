<script>
  // TMDB poster through the connector (lab's CSP allows same-origin images only); a quiet block when there is none.
  let { src = null, alt = '', kind = '', w = null } = $props();
  let broken = $state(false);
</script>

<span class="p" style:width={w ? `${w}px` : null}>
  {#if src && !broken}<img {src} {alt} loading="lazy" decoding="async" onerror={() => (broken = true)} />
  {:else}<span class="mono none">{kind === 'tv' ? 'tv' : kind === 'person' ? '◦' : 'mv'}</span>{/if}
</span>

<style>
  .p { display: block; aspect-ratio: 2 / 3; background: var(--track); border-radius: 3px; overflow: hidden; flex: none; }
  img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .none { display: flex; height: 100%; align-items: center; justify-content: center; color: var(--faint); font-size: 11px; }
</style>
