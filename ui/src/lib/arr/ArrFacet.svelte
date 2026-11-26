<script>
  // Facet on the service object: queue, stuck downloads (+ manual import), health, upcoming, disks.
  import Section from '../Section.svelte';
  import Stats from '../Stats.svelte';
  import Lines from '../Lines.svelte';
  import Bar from '../Bar.svelte';
  import { bytes, ago } from '../sdk.js';
  import Problems from './Problems.svelte';
  import Upcoming from './Upcoming.svelte';
  import { APPS, healthLine } from './logic.js';
  let { object, data, ctx } = $props();
  const d = $derived(data);
  const used = (x) => 100 * (1 - x.free / x.total);
  const imports = $derived((d?.queue.imports || []).filter((g) => !g.level));
</script>

{#if object.id === ctx.id && d}
  <Section title="queue" src="{ctx.id} {d.version ? 'v' + d.version : ''}">
    <Stats items={[
      { n: 'queued', v: d.queue.total },
      { n: 'failed', v: d.queue.bad, s: d.queue.bad ? 'bad' : null },
      { n: 'blocked', v: d.queue.blocked, s: d.queue.blocked ? 'warn' : null },
      { n: 'missing', v: d.missing ?? '–' },
      { n: 'cutoff unmet', v: d.cutoff ?? '–' },
    ]} cols={5} />
    {#if d.running.length}
      <span class="mono s"><span class="sig spin"></span> {d.running.map((c) => c.name + (c.started ? ` (${ago(c.started, ctx.now)})` : '')).join(' · ')}</span>
    {/if}
    <button class="lnk mono s" onclick={() => ctx.go(APPS[ctx.id].view)}>browse the library →</button>
  </Section>
  {#if d.queue.problems.length}
    <Section title="stuck · failed" src="queue">
      <Problems groups={d.queue.problems} {ctx} limit={10} />
    </Section>
  {/if}
  {#if imports.length}
    <Section title="waiting for import" src="queue">
      <Problems groups={imports} {ctx} limit={10} />
    </Section>
  {/if}
  <Section title="health" src={ctx.id}>
    <Lines items={d.health.map((h) => healthLine(h))} empty="● all checks pass" />
  </Section>
  <Section title="upcoming" src="calendar">
    <Upcoming items={d.upcoming} limit={14} {ctx} />
  </Section>
  {#if d.disks.length}
    <Section title="disks" src={ctx.id}>
      {#each d.disks as x (x.path)}
        <div class="disk"><span class="mono dim p" title={x.path}>{x.path}</span><Bar value={used(x)} color={used(x) > 90 ? 'var(--bad)' : used(x) > 80 ? 'var(--warn)' : 'var(--sig)'} />
          <span class="mono dim f">{bytes(x.free)} free</span></div>
      {/each}
    </Section>
  {/if}
{/if}

<style>
  .s { font-size: 11px; color: var(--dim); }
  .lnk.s { align-self: flex-start; color: var(--sig); }
  .disk { display: grid; grid-template-columns: 110px 1fr 80px; gap: 8px; align-items: center; }
  .p, .f { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .f { text-align: right; }
</style>
