<script>
  import { rows } from './rows.js';
  let { ctx } = $props();
  const all = $derived(rows(ctx));
  const ok = $derived(all.filter((r) => r.status === 'ok').length);
  const clean = $derived(all.filter((r) => r.dead || r.dnsOnly).length);
</script>

<div class="t">
  <span class="mono big">{ok}<span class="dim">/{all.length}</span></span>
  <span class="cap">names ok{#if clean} · <span class="warn">▲ {clean} cleanup</span>{/if} · {all.filter((r) => r.dns.proxied).length} proxied</span>
</div>

<style>
  .t { display: flex; flex-direction: column; margin-top: auto; gap: 2px; }
  .big { font-size: 30px; font-weight: 500; letter-spacing: -.02em; }
  .big .dim { font-size: 18px; }
</style>
