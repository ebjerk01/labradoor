<script>
  // wall tile + overview section: today's morning summary (written by the assistant after the set time)
  import Md from './Md.svelte';
  let { data, ctx, section = false } = $props();
  const s = $derived(data?.summary);
</script>

{#if section}
  {#if s?.text}
    <section class="ov">
      <div class="sh"><span class="cap">~/ai/summary</span><button class="lnk mono dim" onclick={() => ctx.go('ai-triage')}>{s.day} ›</button></div>
      <Md text={s.text} />
    </section>
  {/if}
{:else}
  <div class="tile">
    {#if s?.text}<Md text={s.text} />{:else}<span class="mono dim">{s ? s.status : `after ${data?.settings?.summary_time || '07:30'}`}</span>{/if}
  </div>
{/if}

<style>
  .ov { padding: 14px 20px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px; }
  .sh { display: flex; justify-content: space-between; align-items: baseline; }
  .lnk { font-size: 11px; }
  .tile { overflow: hidden; font-size: 12px; mask-image: linear-gradient(to bottom, #000 80%, transparent); }
</style>
