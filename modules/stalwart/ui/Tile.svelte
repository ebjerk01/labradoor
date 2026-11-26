<script>
  // Wall tile: queue size (big), failing, blocked IPs (24 h), accounts.
  import Glyph from '$lab/Glyph.svelte';
  import { objId, blockedSince, statusOf } from './sw.js';
  let { data, ctx } = $props();
  const c = $derived(data.counts);
</script>

<button class="lnk v" onclick={() => ctx.open(objId(ctx.settings))}>
  <span class="mono big"><Glyph status={statusOf(data, ctx.settings)} size={11} /> {c.queue}</span>
  <span class="mono dim">queued{c.failing ? ` · ${c.failing} failing` : ''}</span>
</button>
<div class="st mono">
  <span>{c.accounts} accounts</span>
  <span>{c.blocked} blocked IPs (+{blockedSince(data, ctx.now - 86400)} 24 h)</span>
  <span>{data.reports.dmarc + data.reports.tls} reports in</span>
</div>

<style>
  .v { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-top: auto; }
  .big { font-size: 26px; font-weight: 500; letter-spacing: -.03em; }
  .v .dim { font-size: 11px; }
  .st { display: flex; flex-wrap: wrap; gap: 2px 12px; font-size: 11px; color: var(--dim); }
</style>
