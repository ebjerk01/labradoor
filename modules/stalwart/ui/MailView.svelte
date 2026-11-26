<script>
  // ~/mail — the Stalwart mail server: queue, reports, domains, accounts, IPs. Reading: admin. Retry: admin.
  // Cancel delivery, queue pause, accounts and unblocking: owner (admin → ask owner).
  import QueueTab from './QueueTab.svelte';
  import ReportsTab from './ReportsTab.svelte';
  import DomainsTab from './DomainsTab.svelte';
  import AccountsTab from './AccountsTab.svelte';
  import IpsTab from './IpsTab.svelte';
  import { untrack } from 'svelte';
  import { ago } from '$lab/sdk.js';
  let { data, ctx } = $props();
  let tab = $state(untrack(() => ctx.prefs.get('tab', 'queue')));
  const pick = (t) => { tab = t; ctx.prefs.set('tab', t); };
  const TABS = $derived(data ? [
    ['queue', data.counts.queue], ['reports', data.reports.dmarc + data.reports.tls + data.reports.arf],
    ['domains', data.counts.domains], ['accounts', data.counts.accounts], ['ips', data.counts.blocked],
  ] : []);
</script>

{#if !data}<p class="mono dim pad"><span class="spin"></span> loading stalwart</p>{:else}
<div class="mv fade">
  <div class="bar">
    <span class="cap">~/mail</span>
    <div class="seg" role="group" aria-label="Section">
      {#each TABS as [t, n] (t)}
        <button aria-pressed={tab === t} onclick={() => pick(t)}>{t} <span class="faint">{n}</span></button>
      {/each}
    </div>
    <span class="mono dim note">stalwart · fetched {ago(data.fetched, ctx.now)}{ctx.role === 'owner' ? '' : ' · owner-only changes ask the owner'}</span>
  </div>
  {#if tab === 'queue'}<QueueTab {data} {ctx} />
  {:else if tab === 'reports'}<ReportsTab {data} {ctx} />
  {:else if tab === 'domains'}<DomainsTab {data} {ctx} />
  {:else if tab === 'accounts'}<AccountsTab {data} {ctx} />
  {:else}<IpsTab {data} {ctx} />{/if}
</div>
{/if}

<style>
  .mv { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 12px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .seg button { padding: 5px 9px; font-size: 11px; }
  .note { font-size: 11px; margin-left: auto; }
  .pad { padding: 16px; }
</style>
