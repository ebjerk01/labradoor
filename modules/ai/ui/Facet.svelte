<script>
  // The "ai" section on EVERY object: triage notes for this object's alerts (with their proposals), a triage button
  // for alerts not looked at yet, and "ask ai" (opens a chat about this object).
  import Section from '$lab/Section.svelte';
  import Icon from '$lab/Icon.svelte';
  import { act } from '$lab/sdk.js';
  import Md from './Md.svelte';
  import Proposal from './Proposal.svelte';
  import { askAbout } from './state.svelte.js';
  let { object, data, ctx } = $props();

  const alerts = $derived(ctx.alerts().filter((a) => a.object === object.id && a.module !== 'ai'));
  const keyOf = (a) => `${a.module}:${a.key}`;
  const triage = $derived((data?.triage || []).filter((t) => t.object === object.id || alerts.some((a) => keyOf(a) === t.key)));
  const untriaged = $derived(alerts.filter((a) => !triage.some((t) => t.key === keyOf(a))));
  let busy = $state('');
  async function triageNow(a) {
    busy = keyOf(a);
    const r = await act(ctx, { path: '/api/triage', body: { key: keyOf(a) }, label: 'ai: triage alert',
      ok: (x) => (x.queued ? 'triage started' : 'already triaged recently') });
    if (r) setTimeout(() => ctx.refresh(), 4000);
    busy = '';
  }
</script>

{#if data?.enabled}
  <Section title="ai" src="ai">
    {#each triage as t (t.key)}
      <div class="tr">
        <div class="mono hd">
          {#if ['queued', 'running'].includes(t.status)}<span class="spin"></span>{:else}<span class={t.alert?.status === 'bad' ? 'bad' : 'warn'}>{t.alert?.status === 'bad' ? '■' : '▲'}</span>{/if}
          <span class="dim">triage · {t.alert?.title}</span>
        </div>
        {#if t.text}<Md text={t.text} />{:else}<span class="mono dim">{t.status}…</span>{/if}
        {#each t.proposals || [] as p (p.id)}<Proposal {p} {ctx} after={() => ctx.refresh()} />{/each}
      </div>
    {/each}
    {#if untriaged.length && data.keyed}
      <div class="un">
        {#each untriaged as a (keyOf(a))}
          <button class="btn sm" disabled={busy === keyOf(a)} onclick={() => triageNow(a)}><Icon name="search" size={11} /><span class="lbl">triage: {a.title}</span></button>
        {/each}
      </div>
    {/if}
    <div><button class="btn sm" onclick={() => askAbout(object)}><Icon name="shell" size={11} />ask ai about {object.name}</button></div>
  </Section>
{/if}

<style>
  .tr { display: flex; flex-direction: column; gap: 6px; padding-bottom: 8px; border-bottom: 1px dashed var(--line); }
  .hd { font-size: 11px; display: flex; gap: 6px; align-items: baseline; }
  .un { display: flex; flex-wrap: wrap; gap: 6px; min-width: 0; max-width: 100%; }
  .lbl { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sm { padding: 4px 8px; font-size: 11px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
