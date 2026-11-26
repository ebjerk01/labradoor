<script>
  // ~/ai chat: history per user (the owner also sees everyone's, read-only), a streaming answer (polled: the
  // gateway buffers responses), tool steps as compact lines with the |/-\ spinner, proposals as run/dismiss cards.
  import Icon from '$lab/Icon.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import { ago } from '$lab/sdk.js';
  import Md from './Md.svelte';
  import Proposal from './Proposal.svelte';
  import { ai, openConv, newChat, send, stop, remove } from './state.svelte.js';
  let { data, ctx } = $props();

  let histOpen = $state(false);
  let scroller = $state();
  let end = $state();
  let input = $state();
  const items = $derived([...ai.items, ...ai.live]);
  const mine = $derived(!ai.conv || ai.owner === ctx.me?.username);
  const m = $derived(data?.month);
  const SUGGEST = ['what is red right now, and why?', 'anything odd in the logs the last hour?', 'are the backups ok?', 'which machines need updates?'];

  $effect(() => { void items.length; void ai.live.at(-1)?.text?.length; queueMicrotask(() => { if (scroller && scroller.scrollHeight > scroller.clientHeight) scroller.scrollTop = scroller.scrollHeight; else end?.scrollIntoView({ block: 'nearest' }); }); });
  $effect(() => { void ai.focus; queueMicrotask(() => input?.focus()); });

  function key(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(); }
  }
  function go() {
    const t = ai.draft;
    ai.draft = '';
    send(t);
  }
  const reload = () => ai.conv && openConv(ai.conv);
  const kb = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);
</script>

{#if !data}<p class="mono dim pad spin">loading</p>
{:else if !data.enabled}<p class="mono dim pad">the owner has switched the assistant off for admins</p>
{:else}
<div class="chat fade">
  <aside class="hist" class:open={histOpen}>
    <div class="hh"><span class="cap">~/ai/history</span>
      <button class="btn sm" onclick={() => { newChat(); histOpen = false; }}><Icon name="play" size={11} />new</button></div>
    <ul>
      {#each data.conversations as c (c.id)}
        <li class:on={c.id === ai.conv}>
          <button class="lnk row" onclick={() => { openConv(c.id); histOpen = false; }}>
            <span class="t">{c.title || 'new chat'}</span>
            <span class="mono dim meta">{#if c.running}<span class="spin"></span>{/if}{c.owner !== ctx.me?.username ? `${c.owner} · ` : ''}{ago(c.updated, ctx.now)}</span>
          </button>
          {#if c.owner === ctx.me?.username || ctx.role === 'owner'}
            <button class="x mono faint" aria-label="Delete chat" title="delete" onclick={() => confirm('Delete this chat?') && remove(c.id)}>×</button>
          {/if}
        </li>
      {:else}
        <li class="mono dim empty">no chats yet</li>
      {/each}
    </ul>
    <div class="mono faint keep">kept {data.settings.retention_days} days</div>
  </aside>

  <section class="thread">
    <div class="bar">
      <button class="btn sm hb" onclick={() => (histOpen = !histOpen)} aria-expanded={histOpen}>☰</button>
      <span class="mono ttl"><span class="sig">~/ai</span> {ai.title || 'new chat'}{#if !mine}<span class="dim"> · {ai.owner} (read-only)</span>{/if}</span>
      {#if m}<span class="mono dim spend" title="this month: you ${m.mine.toFixed(2)} of ${m.myCap.toFixed(0)} · all ${m.spent.toFixed(2)} of ${m.cap}">
        ${m.spent.toFixed(2)}<span class="faint">/{m.cap}</span></span>{/if}
      {#if ai.running}<button class="btn sm" onclick={stop}><Icon name="close" size={11} />stop</button>{/if}
      <button class="btn sm" onclick={() => newChat()}><Icon name="play" size={11} />new</button>
    </div>
    {#if ai.context?.object}
      <div class="ctx mono"><span class="dim">about</span> <Glyph status={ai.context.object.status} /> {ai.context.object.name}
        <span class="faint">{ai.context.object.kind || ai.context.object.type}</span>
        <button class="x faint" aria-label="Drop context" onclick={() => (ai.context = null)}>×</button></div>
    {/if}

    <div class="msgs" bind:this={scroller}>
      {#if !items.length}
        <div class="hello">
          <p class="mono dim">ask about the lab. it reads as <span class="sig">{ctx.me?.username}</span> ({ctx.role}), never secrets;
            changes come back as cards you run yourself.</p>
          <div class="sugg">{#each SUGGEST as s}<button class="btn" onclick={() => send(s)}>{s}</button>{/each}</div>
          {#if !data.keyed}<p class="mono bad">■ no Claude API key on the lab CT</p>{/if}
        </div>
      {/if}
      {#each items as it, n (n)}
        {#if it.t === 'q'}<div class="q mono"><span class="sig">$</span> {it.text}</div>
        {:else if it.t === 'a'}<div class="a"><Md text={it.text} /></div>
        {:else if it.t === 'note'}<div class="note">{it.text}</div>
        {:else if it.t === 'sys'}<div class="sys mono"># {it.text}</div>
        {:else if it.t === 'tool'}
          <div class="step mono" title={it.err || ''}>
            {#if it.running}<span class="spin"></span>{:else if it.ok === false}<span class="bad">■</span>{:else}<span class="ok">●</span>{/if}
            <span class="tn">{it.name}</span> <span class="dim">{it.args}</span>{#if it.size}<span class="faint"> · {kb(it.size)}</span>{/if}
          </div>
        {:else if it.t === 'proposal'}<div class="prop"><Proposal p={it.p} {ctx} after={reload} /></div>
        {/if}
      {/each}
      {#if ai.running && !ai.live.some((x) => x.t === 'a')}<div class="mono dim think"><span class="spin"></span> thinking</div>{/if}
      <div bind:this={end}></div>
    </div>

    {#if ai.error}<div class="err mono"><span class="bad">■</span> {ai.error}</div>{/if}
    {#if mine}
      <form class="in" onsubmit={(e) => { e.preventDefault(); go(); }}>
        <span class="mono sig pr">$</span>
        <textarea bind:this={input} bind:value={ai.draft} onkeydown={key} rows="2" maxlength="8000"
          placeholder={ai.running ? 'answering…' : 'ask about the lab · enter sends · shift+enter new line'} aria-label="Question"></textarea>
        <button class="btn primary" disabled={ai.running || !ai.draft.trim()} aria-label="Send"><Icon name="play" size={12} /></button>
      </form>
    {/if}
  </section>
</div>
{/if}

<style>
  .pad { padding: 20px; }
  .chat { display: flex; height: calc(100vh - 92px); min-height: 420px; }
  .hist { flex: 0 0 230px; width: 230px; min-width: 0; overflow: hidden; border-right: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; background: var(--panel); }
  .hh { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-bottom: 1px solid var(--line); }
  ul { list-style: none; margin: 0; padding: 4px; overflow-y: auto; flex: 1; }
  li { display: flex; align-items: center; border-radius: 4px; }
  li.on { background: var(--raise); box-shadow: inset 2px 0 0 var(--sig); }
  .row { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; padding: 6px 8px; }
  .t { font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meta { font-size: 10.5px; display: flex; gap: 4px; }
  .x { border: none; background: none; padding: 2px 8px; font-size: 14px; }
  .x:hover { color: var(--bad); }
  .empty, .keep { padding: 10px; font-size: 11px; }
  .thread { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
  .bar { display: flex; align-items: center; gap: 8px; padding: 8px 14px; border-bottom: 1px solid var(--line); }
  .ttl { flex: 1; min-width: 0; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .spend { font-size: 11.5px; }
  .sm { padding: 4px 8px; font-size: 11px; }
  .hb { display: none; }
  .ctx { font-size: 11.5px; padding: 6px 14px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 6px; }
  .msgs { flex: 1; overflow-y: auto; padding: 14px 18px; display: flex; flex-direction: column; gap: 8px; min-height: 0; }
  .hello { display: flex; flex-direction: column; gap: 10px; max-width: 620px; font-size: 12px; }
  .sugg { display: flex; flex-wrap: wrap; gap: 6px; }
  .q { font-size: 13px; padding: 6px 10px; background: var(--raise); border-radius: 4px; align-self: flex-start; max-width: 100%; white-space: pre-wrap; overflow-wrap: anywhere; margin-top: 6px; }
  .a { max-width: 760px; }
  .note { font-size: 12px; color: var(--dim); font-style: italic; padding-left: 10px; border-left: 1px solid var(--line); white-space: pre-wrap; }
  .sys { font-size: 11px; color: var(--dim); }
  .step { font-size: 11.5px; display: flex; gap: 6px; align-items: baseline; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--dim); }
  .step .tn { color: var(--ink); }
  .step > span:last-child { overflow: hidden; text-overflow: ellipsis; }
  .prop { max-width: 620px; }
  .think { font-size: 11.5px; display: flex; gap: 6px; }
  .err { font-size: 12px; padding: 6px 14px; border-top: 1px solid var(--line); }
  .in { display: flex; gap: 8px; align-items: flex-end; padding: 10px 14px; border-top: 1px solid var(--line); }
  .pr { padding-bottom: 8px; }
  textarea { flex: 1; resize: none; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 7px 10px; font-size: 13px; min-height: 38px; max-height: 30vh; }
  textarea:focus { border-color: var(--sig); outline: none; }
  @media (max-width: 860px) {
    /* phone: the page scrolls (the top bar is tall here); the question box stays at the bottom */
    .chat { height: auto; min-height: 60vh; position: relative; }
    .thread { min-height: 60vh; }
    .msgs { overflow: visible; flex: 1 0 auto; }
    .in { position: sticky; bottom: 0; background: var(--bg); z-index: 3; }
    .hist { display: none; }
    .hist.open { display: flex; position: absolute; z-index: 5; inset: 0 auto 0 0; width: min(300px, 85vw); box-shadow: 0 10px 30px rgba(0, 0, 0, .3); }
    .hb { display: inline-flex; }
    .bar { padding: 6px 10px; }
    .msgs { padding: 10px 12px; }
    .in { padding: 8px 10px; }
    .spend { display: none; }
  }
</style>
