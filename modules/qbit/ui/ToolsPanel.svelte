<script>
  // Admin tools: add a torrent by magnet link or URL, global speed limits + alternative speed, categories.
  // Every write goes through ActionButton (the manifest's verdict decides who sees it); nothing here talks to qBittorrent directly.
  import Section from '$lab/Section.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import Lazy from '$lab/Lazy.svelte';
  import { lazy, rate } from '$lab/sdk.js';
  let { data, ctx } = $props();

  let urls = $state('');
  let category = $state('');
  let paused = $state(false);
  const lines = $derived(urls.split(/\r?\n/).map((x) => x.trim()).filter(Boolean));

  // limits are typed in MiB/s (0 = unlimited) and sent as bytes per second
  let dl = $state('');
  let up = $state('');
  const toBytes = (v) => (v === '' || !Number.isFinite(Number(v)) || Number(v) < 0 ? null : Math.round(Number(v) * 1048576));
  const limitBody = $derived({ ...(toBytes(dl) != null ? { dl: toBytes(dl) } : {}), ...(toBytes(up) != null ? { up: toBytes(up) } : {}) });
  const limitText = (b) => (b ? rate(b) : 'unlimited');
  const alt = $derived(data.alt_speed || {});
  const kib = (v) => (v ? rate(v * 1024) : 'unlimited');

  const cats = lazy(() => ctx, () => '/api/categories', { pick: (r) => r.categories });
  let cname = $state('');
  let cpath = $state('');
  const used = $derived(data.cats || {});
</script>

<div class="tools">
  <Section title="add torrent" src="qbit">
    <textarea class="field" rows="3" bind:value={urls} aria-label="Magnet links or URLs, one per line"
      placeholder="magnet:?xt=urn:btih:…  or  https://…/file.torrent  (one per line)"></textarea>
    <div class="line">
      <select class="field" bind:value={category} aria-label="Category">
        <option value="">no category</option>
        {#each data.categories || [] as c (c)}<option value={c}>{c}</option>{/each}
      </select>
      <label class="mono dim chk"><input type="checkbox" bind:checked={paused} /> add stopped</label>
      <ActionButton {ctx} path="/api/torrents/add" label="add {lines.length} torrent{lines.length === 1 ? '' : 's'}" icon="download" primary
        disabled={!lines.length}
        body={() => ({ urls: lines.join('\n'), ...(category ? { category } : {}), paused })}
        ok={(r) => `added ${r.count} torrent${r.count === 1 ? '' : 's'} ✓`}
        done={() => { urls = ''; }} />
    </div>
  </Section>

  <Section title="speed" src="qbit">
    <div class="mono s">
      limit ↓ {limitText(data.transfer.dl_rate_limit)} · ↑ {limitText(data.transfer.up_rate_limit)}
      <span class="dim"> · alternative {alt.enabled ? 'ON' : 'off'} (↓ {kib(alt.dl)} · ↑ {kib(alt.up)})</span>
    </div>
    <div class="line">
      <input class="field n" inputmode="decimal" placeholder="↓ MiB/s" bind:value={dl} aria-label="Download limit in MiB per second" />
      <input class="field n" inputmode="decimal" placeholder="↑ MiB/s" bind:value={up} aria-label="Upload limit in MiB per second" />
      <ActionButton {ctx} path="/api/limits" label="set speed limits" icon="activity" disabled={!Object.keys(limitBody).length}
        body={() => limitBody} done={() => { dl = ''; up = ''; }} />
      <ActionButton {ctx} path="/api/alt-speed" label={alt.enabled ? 'alternative speed off' : 'alternative speed on'} icon="restart"
        body={() => ({ enabled: !alt.enabled })} />
    </div>
    <span class="mono dim s">0 = unlimited. Empty field = leave as is.</span>
  </Section>

  <Section title="categories" src="qbit">
    <Lazy of={cats} empty="no categories">
      {#snippet children(list)}
        {#each list as c (c.name)}
          <div class="mono s crow"><span>{c.name}</span><span class="dim">{used[c.name]?.n ?? 0} torrents</span><span class="dim p">{c.save_path || 'default path'}</span>
            <button class="lnk" onclick={() => { cname = c.name; cpath = c.save_path; }}>edit</button></div>
        {/each}
      {/snippet}
    </Lazy>
    <div class="line">
      <input class="field" bind:value={cname} placeholder="name" aria-label="Category name" />
      <input class="field w" bind:value={cpath} placeholder="save path (absolute, optional)" aria-label="Save path" />
      <ActionButton {ctx} path="/api/categories" label="set category {cname}" icon="check" disabled={!cname.trim()}
        body={() => ({ name: cname.trim(), ...(cpath.trim() ? { save_path: cpath.trim() } : {}) })}
        done={() => { cats.reload(); cname = ''; cpath = ''; }} />
    </div>
  </Section>
</div>

<style>
  .tools { display: flex; flex-direction: column; gap: 10px; padding: 8px 16px 12px; border-bottom: 1px solid var(--line); }
  .line { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px; font-size: 12px; min-width: 0; }
  textarea.field { width: 100%; resize: vertical; font-family: inherit; }
  .n { width: 96px; }
  .w { flex: 1 1 220px; }
  .s { font-size: 11px; }
  .chk { display: flex; gap: 4px; align-items: center; font-size: 11px; }
  .crow { display: grid; grid-template-columns: minmax(80px, 160px) 90px minmax(0, 1fr) auto; gap: 8px; padding: 2px 0; border-bottom: 1px solid var(--q); }
  .p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
