<script>
  // The switch's section in the object panel: system numbers and the ports that need a look.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import { level, dur, rate } from '$lab/sdk.js';
  import { speedText, poeOn } from './mikrotik.js';
  let { object, data, ctx } = $props();
  const up = $derived((data?.ports ?? []).filter((p) => p.running));
  const show = $derived((data?.ports ?? []).filter((p) => p.running || p.comment));
  const stat = (p) => (p.running ? (p.speed < 1000 && !p.name.startsWith('sfp') ? 'warn' : 'ok') : 'off');
</script>

{#if data && (object.type === 'switch' || object.id === (ctx.settings.object_id || data.identity))}
  <Section title="switch · {data.identity}" src="mikrotik · {data.sys.version}">
    <Stats items={[
      { n: 'ports up', v: `${up.length}/${data.ports.length}` },
      { n: 'poe', v: data.health.poeW != null ? `${data.health.poeW} W` : '–' },
      { n: 'cpu', v: `${data.sys.cpu}%`, s: level(data.sys.cpu, 70, 90) },
      { n: 'temp', v: data.health.temp != null ? `${data.health.temp}°` : '–' },
    ]} />
    <span class="mono dim t">up {dur(data.sys.uptime)} · {data.sys.board}</span>
  </Section>
  <Section title="ports" src="mikrotik">
    <Lines items={show.map((p) => ({ p: p.running ? '●' : '○', s: stat(p),
      t: `${p.name}${p.comment ? ' ' + p.comment : ''} · ${p.running ? `${speedText(p.speed)} · ↓${rate(p.rxRate)} ↑${rate(p.txRate)}` : 'down'}${poeOn(p) ? ` · poe ${p.poe.watts.toFixed(1)} W` : ''}${p.fcs ? ` · ${p.fcs} crc` : ''}` }))} empty="no ports up" />
    {#if ctx.canGo('mikrotik')}<button class="btn" onclick={() => ctx.go('mikrotik')}>open switch view</button>{/if}
  </Section>
{/if}

<style>
  .t { font-size: 11px; }
</style>
