<script>
  // ~/jellyfin-server — the server itself: version, restart (admin) / shut down (owner), updates, storage + paths, and tabs for
  // scheduled tasks, plugins, transcoding, logs and API keys.
  import Icon from '$lab/Icon.svelte';
  import Bar from '$lab/Bar.svelte';
  import { bytes } from '$lab/fmt.js';
  import { lazy } from '$lab/sdk.js';
  import { write } from './store.svelte.js';
  import TasksPanel from './TasksPanel.svelte';
  import PluginsPanel from './PluginsPanel.svelte';
  import EncodingPanel from './EncodingPanel.svelte';
  import LogsPanel from './LogsPanel.svelte';
  import KeysPanel from './KeysPanel.svelte';
  let { data, ctx } = $props();

  const TABS = [['server', 'server'], ['tasks', 'tasks'], ['plugins', 'plugins'], ['transcoding', 'transcoding'], ['logs', 'logs'], ['keys', 'api keys']];
  let tab = $state('server');
  const storage = lazy(() => ctx, () => (tab === 'server' ? '/System/Info/Storage' : null));
  const canRestart = $derived(ctx.can('POST', '/System/Restart') !== 'no');
  const shutVerdict = $derived(ctx.can('POST', '/System/Shutdown'));
  const playing = $derived((data?.sessions || []).filter((s) => s.playing));
  const failed = $derived((data?.tasks || []).filter((t) => t.last?.status === 'Failed').length);

  const host = $derived(ctx.settings?.host || 'the server');
  const who = () => (playing.length ? `\n\n${playing.length} playing right now (${[...new Set(playing.map((s) => s.user))].join(', ')}): their streams stop.` : '\n\nNobody is playing.');
  const restart = () => write(ctx, ['info'], { path: '/System/Restart', label: 'jellyfin: restart', confirm: `Restart Jellyfin on ${host}? It is gone for ~30 s.${who()}` });
  const shutdown = () => write(ctx, ['info'], { path: '/System/Shutdown', label: 'jellyfin: shut down', confirm: `SHUT DOWN Jellyfin? It stays off until someone runs “systemctl start jellyfin” on ${host}.${who()}` });
  const folders = $derived(storage.data ? [
    ['data', storage.data.ProgramDataFolder], ['metadata', storage.data.InternalMetadataFolder], ['cache', storage.data.CacheFolder],
    ['images', storage.data.ImageCacheFolder], ['transcodes', storage.data.TranscodingTempFolder], ['logs', storage.data.LogFolder], ['web', storage.data.WebFolder],
    ...(storage.data.Libraries || []).flatMap((l) => (l.Folders || []).map((f) => [`lib ${l.Name}`, f])),
  ].filter(([, f]) => f) : []);
  const pct = (f) => (f.UsedSpace + f.FreeSpace ? (100 * f.UsedSpace) / (f.UsedSpace + f.FreeSpace) : 0);
</script>

{#if !data}<p class="mono dim pad spin">loading jellyfin</p>{:else}
<div class="xv fade">
  <div class="bar">
    <div class="seg tabs" role="group" aria-label="server tabs">
      {#each TABS as [id, l]}<button aria-pressed={tab === id} onclick={() => (tab = id)}>{l}{#if id === 'tasks' && failed}<span class="bad"> ■{failed}</span>{/if}</button>{/each}
    </div>
  </div>

  {#if tab === 'server'}
    <div class="srv">
      <div class="facts mono">
        <span class="dim">server</span><span>{data.server || '–'} · v{data.version || '–'}</span>
        <span class="dim">state</span><span class:warn={data.restart}>{#if data.restart}▲ restart pending{:else}<span class="ok">●</span> running{/if} · {playing.length} playing · {data.sessions.length} connected</span>
        <span class="dim">updates</span><span>{data.update ? '▲ update available · ' : ''}apt on {host} (jellyfin + jellyfin-ffmpeg){#if ctx.settings?.host && ctx.object(ctx.settings.host)} <button class="lnk sig" onclick={() => ctx.open(ctx.settings.host)}>{host} →</button>{/if}</span>
      </div>
      <div class="row">
        {#if canRestart}<button class="btn" class:primary={data.restart} onclick={restart}><Icon name="restart" size={12} />restart{playing.length ? ` (${playing.length} playing)` : ''}</button>{/if}
        {#if shutVerdict !== 'no'}<button class="btn danger" onclick={shutdown}><Icon name={shutVerdict === 'ask' ? 'lock' : 'close'} size={12} />shut down{shutVerdict === 'ask' ? ' · ask' : ''}</button>{/if}
      </div>
    </div>
    <h3 class="cap h">~/storage</h3>
    {#if storage.error}<p class="mono bad s">{storage.error}</p>{/if}
    <div class="st">
      {#each folders as [n, f] (n + f.Path)}
        <span class="mono dim s">{n}</span>
        <span class="mono s ell" title={f.Path}>{f.Path}</span>
        <span class="b"><Bar value={pct(f)} color={pct(f) > 90 ? 'var(--bad)' : pct(f) > 80 ? 'var(--warn)' : 'var(--sig)'} /></span>
        <span class="mono s r">{bytes(f.FreeSpace)} free</span>
      {/each}
    </div>
  {:else if tab === 'tasks'}
    <TasksPanel {data} {ctx} />
  {:else if tab === 'plugins'}
    <PluginsPanel {data} {ctx} />
  {:else if tab === 'transcoding'}
    <EncodingPanel {ctx} />
  {:else if tab === 'logs'}
    <LogsPanel {ctx} />
  {:else}
    <KeysPanel {ctx} />
  {/if}
</div>
{/if}

<style>
  .xv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 10px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .tabs { flex-wrap: wrap; }
  .srv { display: flex; flex-direction: column; gap: 10px; }
  .facts { display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 4px 12px; font-size: 12px; }
  .row { display: flex; gap: 6px; flex-wrap: wrap; }
  .h { margin: 8px 0 0; font-weight: 400; }
  .st { display: grid; grid-template-columns: 90px minmax(0, 1.4fr) minmax(60px, 1fr) 80px; gap: 4px 10px; align-items: center; }
  .b { display: flex; }
  .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .r { text-align: right; }
  .s { font-size: 10.5px; }
  .danger:not(:disabled) { color: var(--bad); border-color: var(--bad); }
  .bad { color: var(--bad); }
  .warn { color: var(--warn); }
  .ok { color: var(--ok); }
  .pad { padding: 12px 16px; }
  @media (max-width: 640px) { .st { grid-template-columns: 70px minmax(0, 1fr) 70px; } .st .ell { display: none; } }
</style>
