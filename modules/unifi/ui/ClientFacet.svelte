<script>
  // a UniFi client: address, network, reservation (edit inline). block/unblock/remove live in the panel's actions.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { ago, bytes } from '$lab/sdk.js';
  import { mismatch, label } from './uf.js';
  let { object, data, ctx, client = null } = $props();

  const c = $derived(client || data.clients.find((x) => `client:${x.mac}` === object.id));
  let ip = $state('');
  let editing = $state(false);
  const path = $derived(c?.reserved ? `/api/reservations/${c.mac}` : '/api/reservations');
</script>

{#if c}
  <Section title="network" src="unifi">
    <Stats items={[
      { n: 'ip', v: c.ip || '–', s: mismatch(c) ? 'warn' : null },
      { n: 'reserved', v: c.reserved ? c.fixedIp : 'no', c: c.reserved ? 'var(--sig)' : null },
      { n: 'network', v: `${c.network || '–'}${c.vlan ? ' · ' + c.vlan : ''}` },
      c.blocked ? { n: 'state', v: 'blocked', s: 'bad' }
        : { n: c.online ? 'up' : 'seen', v: c.online ? ago(ctx.now - (c.uptime || 0), ctx.now) : ago(c.lastSeen, ctx.now), s: c.online ? 'ok' : 'off' },
    ]} />
    <span class="mono dim t">{c.mac} · {c.vendor || '?'} · {c.wired ? `wired ${c.uplink || ''}${c.swPort ? ' port ' + c.swPort : ''}` : `${c.essid || 'wifi'} ${c.signal ?? ''}dBm`}{c.rxBytes ? ` · ↓${bytes(c.rxBytes)} ↑${bytes(c.txBytes)}` : ''}{c.hostname ? ` · ${c.hostname}` : ''}</span>
    {#if editing}
      <div class="row">
        <input class="field mono" bind:value={ip} aria-label="Reserved IP" />
        <ActionButton {ctx} method={c.reserved ? 'PUT' : 'POST'} {path} body={() => (c.reserved ? { ip: ip.trim() } : { mac: c.mac, ip: ip.trim() })}
          label={c.reserved ? `change reservation of ${label(c)}` : `reserve ${ip} for ${label(c)}`} done={() => { editing = false; }} primary small>save</ActionButton>
        <button class="btn sm" onclick={() => (editing = false)}>cancel</button>
      </div>
    {:else if ctx.can(c.reserved ? 'PUT' : 'POST', c.reserved ? '/api/reservations/x' : '/api/reservations') !== 'no'}
      <div class="row"><button class="btn sm" onclick={() => { ip = c.fixedIp || c.ip || ''; editing = true; }}>{c.reserved ? 'edit reservation' : 'pick an IP'}</button></div>
    {/if}
  </Section>
{/if}

<style>
  .t { font-size: 11px; overflow-wrap: anywhere; }
  .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .row .field { max-width: 160px; padding: 5px 8px; font-size: 12px; }
  .sm { padding: 3px 8px; font-size: 11px; }
</style>
