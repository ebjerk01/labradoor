<script>
  // ~/jellyfin-sessions — live sessions (now playing, direct/transcode + why) with message / pause / stop / sign out, the
  // devices Jellyfin knows (forget = signed out there), and the activity log. Nothing here is stored by lab. Writes: admin.
  import Icon from '$lab/Icon.svelte';
  import Bar from '$lab/Bar.svelte';
  import { ago, clock } from '$lab/fmt.js';
  import { playLabel } from './jf.js';
  import { lazy, qs } from '$lab/sdk.js';
  import { write, IID, remember } from './store.svelte.js';
  let { data, ctx } = $props();

  let tab = $state('sessions');
  let msgFor = $state(null);
  let msg = $state({ head: 'lab', text: '' });
  const can = $derived(ctx.can('POST', '/Sessions/x/Message') !== 'no');
  const canForget = $derived(ctx.can('DELETE', '/Devices') !== 'no');
  const sessions = $derived((data?.sessions || []).slice().sort((a, b) => !!b.playing - !!a.playing || (b.last || 0) - (a.last || 0)));

  const devices = lazy(() => ctx, () => (tab === 'devices' ? '/Devices' : null));
  let logStart = $state(0);
  let logFilter = $state('all');
  const LOGF = [['all', 'all'], ['auth', 'sign-ins'], ['problems', 'warnings + errors'], ['playback', 'playback'], ['admin', 'users, plugins, tasks']];
  const log = lazy(() => ctx, () => (tab === 'activity' ? '/System/ActivityLog/Entries' : null), { query: () => ({ startIndex: logStart, limit: 100 }) });
  const PLAY = /Playback|Session/;
  const shown = $derived((log.data?.Items || []).filter((a) => logFilter === 'all'
    || (logFilter === 'auth' && /^Authentication|UserLockedOut/.test(a.Type))
    || (logFilter === 'problems' && a.Severity !== 'Information')
    || (logFilter === 'playback' && PLAY.test(a.Type))
    || (logFilter === 'admin' && !PLAY.test(a.Type) && !/^Authentication/.test(a.Type))));
  const sev = (a) => (a.Severity === 'Error' || a.Severity === 'Critical' || a.Type === 'AuthenticationFailed' ? 'bad' : a.Severity === 'Warning' ? 'warn' : '');
  const uname = (id) => data?.users.find((u) => u.id.replace(/-/g, '') === String(id || '').replace(/-/g, ''))?.name;

  const cmd = (s, c) => write(ctx, [], { path: `/Sessions/${s.id}/Playing/${c}`, label: `jellyfin: ${c.toLowerCase()} ${s.user} on ${s.device}`, confirm: c === 'Stop' ? `Stop ${s.user}'s playback on ${s.device}?` : null });
  async function send(s) {
    const text = msg.text.trim();
    if (!text) return;
    if (await write(ctx, [], { path: `/Sessions/${s.id}/Message`, body: { Header: msg.head.trim() || 'lab', Text: text, TimeoutMs: 15000 }, label: `jellyfin: message ${s.user} on ${s.device}` })) {
      msg.text = '';
      msgFor = null;
    }
  }
  const forget = async (id, who, what) => {
    if (await write(ctx, [], { method: 'DELETE', path: `/Devices?${qs({ id })}`, label: `jellyfin: sign out ${who} on ${what}`, confirm: `Sign ${who} out on “${what}” and forget the device?\n\nPlayback there stops; they have to log in again on it.` })) devices.reload();
  };
</script>

{#if !data}<p class="mono dim pad spin">loading jellyfin</p>{:else}
<div class="sv fade">
  <div class="bar">
    <div class="seg" role="group" aria-label="session tabs">
      {#each [['sessions', `sessions · ${data.sessions.filter((s) => s.playing).length}▶`], ['devices', 'devices'], ['activity', 'activity log']] as [id, l]}
        <button aria-pressed={tab === id} onclick={() => (tab = id)}>{l}</button>
      {/each}
    </div>
    {#if tab === 'activity'}
      <select class="field" bind:value={logFilter} aria-label="Filter">{#each LOGF as [v, l]}<option value={v}>{l}</option>{/each}</select>
    {/if}
    <span class="mono dim note">live from Jellyfin · lab stores none of it</span>
  </div>

  {#if tab === 'sessions'}
    {#each sessions as s (s.id)}
      {@const tc = s.method === 'Transcode'}
      <div class="ses" class:play={s.playing}>
        <span class="mono g" class:sig={s.playing && !s.paused} class:dim={!s.playing || s.paused}>{s.playing ? (s.paused ? '❚❚' : '▶') : '·'}</span>
        <div class="m">
          {#if s.playing}<button class="lnk t" onclick={() => s.itemId && ctx.open(remember({ Id: s.itemId, Name: s.playing.name, Type: s.playing.type, SeriesName: s.playing.series, ParentIndexNumber: s.playing.s, IndexNumber: s.playing.e, ProductionYear: s.playing.year }))}>{playLabel(s.playing)}</button>
          {:else}<span class="t dim">idle · {ago(s.last, ctx.now)} ago</span>{/if}
          <span class="mono dim sub">{s.user} · {s.client} {s.version || ''} · {s.device}{s.remote ? ` · ${s.remote}` : ''}</span>
          {#if s.playing}
            <span class="mono sub" class:warn={tc}>{s.method || '–'}{#if s.transcode} · video {s.transcode.video} · audio {s.transcode.audio}{s.transcode.hw ? ` · hw ${s.transcode.hw}` : ' · software'}{s.transcode.fps ? ` · ${Math.round(s.transcode.fps)} fps` : ''}{s.transcode.bitrate ? ` · ${(s.transcode.bitrate / 1e6).toFixed(1)} Mbit/s` : ''}{/if}</span>
            {#if s.transcode?.reasons?.length}<span class="mono sub warn">why: {s.transcode.reasons.join(', ')}</span>{/if}
          {/if}
        </div>
        {#if s.playing?.pct != null}<span class="p"><Bar value={s.playing.pct} color="var(--sig)" /></span>{:else}<span class="p"></span>{/if}
        <div class="acts">
          {#if can && s.playing && s.control}
            {#if s.paused}<button class="btn x" title="resume" aria-label="resume" onclick={() => cmd(s, 'Unpause')}><Icon name="play" size={11} /></button>
            {:else}<button class="btn x mono" title="pause" aria-label="pause" onclick={() => cmd(s, 'Pause')}>❚❚</button>{/if}
            <button class="btn x mono" title="stop" aria-label="stop" onclick={() => cmd(s, 'Stop')}>■</button>
          {/if}
          {#if can && s.message}<button class="btn x" title="send a message" aria-label="message" aria-expanded={msgFor === s.id} onclick={() => (msgFor = msgFor === s.id ? null : s.id)}><Icon name="mail" size={11} /></button>{/if}
          {#if canForget && s.deviceId}<button class="btn x" title="sign out + forget device" aria-label="sign out" onclick={() => forget(s.deviceId, s.user, s.device)}><Icon name="logout" size={11} /></button>{/if}
        </div>
        {#if msgFor === s.id}
          <form class="msg" onsubmit={(e) => { e.preventDefault(); send(s); }}>
            <input class="field h" bind:value={msg.head} aria-label="Message title" />
            <input class="field grow" bind:value={msg.text} placeholder="shown on {s.device} for 15 s" aria-label="Message" />
            <button class="btn" disabled={!msg.text.trim()}>send</button>
          </form>
        {/if}
      </div>
    {:else}
      <span class="mono dim">nobody connected in the last 16 minutes</span>
    {/each}
  {:else if tab === 'devices'}
    {#if devices.error}<p class="mono bad s">{devices.error}</p>{/if}
    <div class="scroll-x"><div class="dt">
      <span class="h">device</span><span class="h">app</span><span class="h">last user</span><span class="h">seen</span><span class="h"></span>
      {#each (devices.data?.Items || []).slice().sort((a, b) => Date.parse(b.DateLastActivity) - Date.parse(a.DateLastActivity)) as d (d.Id)}
        <span class="ell">{d.CustomName || d.Name}</span>
        <span class="mono dim s ell">{d.AppName} {d.AppVersion}</span>
        <span class="mono s">{d.LastUserName || '–'}</span>
        <span class="mono dim s">{d.DateLastActivity ? ago(Date.parse(d.DateLastActivity) / 1000, ctx.now) : '–'}</span>
        {#if canForget}<button class="btn x" title="sign out + forget" aria-label="forget {d.Name}" onclick={() => forget(d.Id, d.LastUserName || 'whoever', d.CustomName || d.Name)}><Icon name="logout" size={11} /></button>{:else}<span></span>{/if}
      {/each}
    </div></div>
    <span class="mono dim s">{devices.data?.TotalRecordCount ?? '–'} devices · forgetting one ends its sign-in (its access token)</span>
  {:else}
    {#if log.error}<p class="mono bad s">{log.error}</p>{/if}
    <div class="log mono">
      {#each shown as a (a.Id)}
        {@const st = sev(a)}
        <span class="dim" title={new Date(a.Date).toLocaleString('nb-NO')}>{ago(Date.parse(a.Date) / 1000, ctx.now)} <span class="faint">{clock(Date.parse(a.Date) / 1000)}</span></span>
        <span class:bad={st === 'bad'} class:warn={st === 'warn'}>{st === 'bad' ? '■' : st === 'warn' ? '▲' : '·'}</span>
        <span class="ell" title={[a.Overview, a.ShortOverview].filter(Boolean).join('\n')}>
          {#if a.ItemId}<button class="lnk" onclick={() => ctx.open(IID(a.ItemId))}>{a.Name}</button>{:else}{a.Name}{/if}
          {#if a.ShortOverview}<span class="dim"> · {a.ShortOverview}</span>{/if}
        </span>
        <span class="dim ell r">{uname(a.UserId) || ''} {a.Type}</span>
      {:else}<span class="dim">{log.loading ? 'loading' : 'nothing'}</span>{/each}
    </div>
    <div class="pager mono">
      <button class="btn x" disabled={logStart === 0} onclick={() => (logStart = Math.max(0, logStart - 100))}>newer</button>
      <span class="dim s">{logStart + 1}–{logStart + (log.data?.Items?.length || 0)} of {log.data?.TotalRecordCount ?? '–'}</span>
      <button class="btn x" disabled={logStart + 100 >= (log.data?.TotalRecordCount || 0)} onclick={() => (logStart += 100)}>older</button>
    </div>
  {/if}
</div>
{/if}

<style>
  .sv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 10px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .note { font-size: 10.5px; flex: 1; text-align: right; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font-size: 12px; color: var(--ink); min-width: 0; }
  .ses { display: grid; grid-template-columns: 18px minmax(0, 1fr) 70px auto; gap: 4px 10px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--q); }
  .m { display: flex; flex-direction: column; min-width: 0; }
  .t, .sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: left; }
  .t { font-size: 12.5px; }
  .sub { font-size: 10.5px; }
  .g { font-size: 11px; }
  .p { display: flex; }
  .acts { display: flex; gap: 4px; }
  .x { padding: 3px 6px; font-size: 10px; }
  .msg { grid-column: 2 / -1; display: flex; gap: 6px; }
  .msg .h { width: 80px; }
  .grow { flex: 1; }
  .dt { display: grid; grid-template-columns: minmax(120px, 1.2fr) minmax(100px, 1fr) auto auto auto; gap: 4px 14px; align-items: center; font-size: 12.5px; min-width: 520px; }
  .h { font: 10px "Geist Mono Variable", monospace; color: var(--dim); }
  .ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .s { font-size: 10.5px; }
  .log { display: grid; grid-template-columns: 82px 10px minmax(0, 1fr) minmax(0, 200px); gap: 3px 8px; font-size: 11px; align-items: baseline; }
  .r { text-align: right; }
  .pager { display: flex; gap: 10px; align-items: center; }
  .bad { color: var(--bad); }
  .warn { color: var(--warn); }
  .pad { padding: 12px 16px; }
  @media (max-width: 640px) {
    .ses { grid-template-columns: 18px minmax(0, 1fr) auto; }
    .ses .p { display: none; }
    .log { grid-template-columns: 54px 10px minmax(0, 1fr); }
    .log .r, .log .faint { display: none; }
    .note { text-align: left; }
  }
</style>
