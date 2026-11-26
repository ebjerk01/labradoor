<script>
  // The AD side of a machine (joined computer account) — on the merged machine object (WINSRV → winsrv) or on an
  // AD-only adcomputer:<name>. Renders nothing for machines that aren't in the domain. Read-only (svc-lab only reads).
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import { ago } from '$lab/sdk.js';
  import { ouPath, ouName } from './ad.js';
  let { object, data, ctx } = $props();
  const c = $derived(object.adComputer ? data.computers.find((x) => x.name === object.adComputer) : null);
</script>

{#if c}
  <Section title="domain" src="active directory">
    <Stats items={[
      { n: 'account', v: c.enabled ? 'on' : 'off', s: c.enabled ? 'ok' : 'off' },
      { n: 'role', v: c.dc ? 'DC' : 'member' },
      { n: 'last logon', v: c.lastLogon ? ago(c.lastLogon, ctx.now) : 'never', s: c.lastLogon && Date.now() / 1000 - c.lastLogon > 30 * 86400 ? 'warn' : null },
      { n: 'machine pw', v: c.pwdLastSet ? ago(c.pwdLastSet, ctx.now) : '–', s: c.pwdLastSet && Date.now() / 1000 - c.pwdLastSet > 60 * 86400 ? 'warn' : null },
    ]} />
    <span class="mono dim s">{c.dns || c.name} · {c.os || 'no OS reported'} {c.osVersion} · {ouPath(c.ou, data.base)} · joined {c.created ? ago(c.created, ctx.now) + ' ago' : '–'}{c.description ? ' · ' + c.description : ''}</span>
    {#if !c.inHomelab && !c.dc}<span class="mono warn s">▲ outside {ouName(data.managedOu)}{ctx.settings.computers_ou ? ` (new joins go to ${ouName(ctx.settings.computers_ou)} via redircmp)` : ''} — moved or joined with an explicit OU.</span>{/if}
  </Section>
{/if}

<style>
  .s { font-size: 11px; line-height: 1.5; }
  .warn { color: var(--warn); }
</style>
