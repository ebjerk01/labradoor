<script>
  // The object's Guacamole connections: protocol, who's on it now (count), last use, and the terminal/console button
  // (owner; an admin with a grant, or "ask owner"). Below: who opened one here lately, and live admin grants (owner can
  // revoke). Only shown when the object has a connection.
  import Section from '$lab/Section.svelte';
  import Icon from '$lab/Icon.svelte';
  import { act, ago } from '$lab/sdk.js';
  import { connsFor, mode, openPath, grantPath, kindOf, isProtected, protectQuestion, show, preOpen, dropPre, grantFor } from './guac.js';
  let { object, data, ctx } = $props();
  const cs = $derived(connsFor(data, object, ctx));
  const ids = $derived(new Set(cs.map((c) => c.id)));
  const opened = $derived((data.sessions?.opened || []).filter((e) => ids.has(e.id)).slice(0, 4));
  const grants = $derived((data.sessions?.grants || []).filter((g) => ids.has(g.id) && g.until > ctx.now));
  let busy = $state('');

  async function open(c) {
    if (ctx.role === 'owner' && isProtected(c, object, ctx) && !confirm(protectQuestion(c, object))) return;
    const pre = preOpen(c);  // while the click is still a user gesture: no pop-up blocker
    busy = c.id;
    try {
      const r = await act(ctx, { path: openPath(c, object), label: `${kindOf(c)} on ${object.id}`, done: (res) => show(res, ctx, pre) });
      if (!r) dropPre(pre);
    } finally { busy = ''; }
  }

  const ask = (c) => act(ctx, { path: grantPath(c, object), label: `${kindOf(c)} on ${object.id} for ${data.sessions?.grant_minutes || 30} min`,
    reason: `${ctx.me?.username} asks for a ${kindOf(c)} (${c.protocol}) on ${object.id}` });

  const revoke = (g) => act(ctx, { path: '/api/sessions/revoke', body: { user: g.user, id: g.id }, label: `revoke ${g.user}'s terminal on ${object.id}`,
    ok: (r) => `revoked ${r.revoked}` });
  const hhmm = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
</script>

{#if cs.length}
  <Section title="console" src="guacamole">
    {#each cs as c (c.id)}
      {@const m = mode(data, c, object, ctx)}
      {@const g = grantFor(data, c, ctx)}
      <div class="r">
        <span class="mono" class:sig={c.active} class:faint={!c.active}>{c.active ? '●' : '○'}</span>
        <span class="mono n">{c.protocol} <span class="dim">· {c.name}</span></span>
        <span class="mono dim">{c.active ? `${c.active} now` : c.lastActive ? `${ago(c.lastActive)} ago` : ''}{g ? ` · yours till ${hhmm(g.until)}` : ''}</span>
        {#if m === 'open'}
          <button class="btn sm" disabled={busy === c.id} onclick={() => open(c)} title="opens in its own window; Guacamole signs you in with your own account">
            <Icon name="shell" size={11} />{kindOf(c)}</button>
        {:else if m === 'ask'}
          <button class="btn sm" onclick={() => ask(c)} title="the owner approves a {data.sessions?.grant_minutes || 30}-minute grant"><Icon name="lock" size={11} />ask owner</button>
        {:else}
          <span class="mono faint">owner only</span>
        {/if}
      </div>
    {/each}
    {#each grants as g (g.user + g.id)}
      <div class="r">
        <span class="mono warn">◆</span>
        <span class="mono n">grant <span class="dim">· {g.user} till {hhmm(g.until)} (by {g.by})</span></span>
        <span></span>
        {#if ctx.role === 'owner'}<button class="btn sm" onclick={() => revoke(g)}>revoke</button>{:else}<span></span>{/if}
      </div>
    {/each}
    {#if opened.length}
      <div class="h mono dim">opened from lab</div>
      {#each opened as e (e.ts + e.user + e.id)}
        <div class="o mono dim"><span>{e.user}</span><span class="n">{e.protocol} · {e.via}</span><span>{ago(e.ts)} ago</span></div>
      {/each}
    {/if}
  </Section>
{/if}

<style>
  .r { display: grid; grid-template-columns: 12px 1fr auto auto; gap: 8px; align-items: center; font-size: 11.5px; }
  .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sm { padding: 2px 7px; font-size: 11px; gap: 4px; text-decoration: none; }
  .h { font-size: 10.5px; margin-top: 6px; }
  .o { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; font-size: 11px; }
</style>
