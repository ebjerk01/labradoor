<script>
  // Wall tile for everyone with a Seerr account: what became watchable lately (links open Jellyfin).
  import { ts } from '$lab/sdk.js';
  import { ago, safeUrl } from '$lab/fmt.js';
  let { data, ctx } = $props();
</script>

<div class="l">
  {#each (data.recent || []).slice(0, 9) as m (m.type + m.tmdb)}
    <a class="r" href={safeUrl(m.url)} target="_blank" rel="noopener">
      <span class="mono k">{m.type === 'tv' ? 'tv' : 'mv'}</span>
      <span class="t">{m.title}{m.year ? ` (${m.year})` : ''}</span>
      <span class="mono dim a">{m.status === 'partial' ? 'some · ' : ''}{ago(ts(m.added), ctx.now)}</span>
    </a>
  {:else}
    <span class="mono dim s">{data.me?.linked === false ? '○ no Seerr account linked to you yet' : 'nothing new'}</span>
  {/each}
</div>

<style>
  .l { display: flex; flex-direction: column; overflow: hidden; }
  .r { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 8px; align-items: baseline; padding: 3px 0; border-bottom: 1px solid var(--q);
    color: var(--ink); text-decoration: none; font-size: 12.5px; }
  .r:hover { color: var(--sig); }
  .k { font-size: 10px; color: var(--sig); }
  .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .a, .s { font-size: 10.5px; }
</style>
