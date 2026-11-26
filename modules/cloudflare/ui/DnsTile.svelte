<script>
  import { staleA } from './cf.js';
  let { data } = $props();
  const addr = $derived(data.records.filter((r) => ['A', 'AAAA', 'CNAME'].includes(r.type)));
  const prox = $derived(addr.filter((r) => r.proxied).length);
  const stale = $derived(staleA(data.records).length);
</script>

<div class="t">
  <span class="mono big">{prox}<span class="dim">/{addr.length}</span></span>
  <span class="cap">proxied · {data.apps.length} access{#if stale} · <span class="warn">▲ {stale} stale A</span>{/if}</span>
</div>

<style>
  .t { display: flex; flex-direction: column; margin-top: auto; gap: 2px; }
  .big { font-size: 30px; font-weight: 500; letter-spacing: -.02em; }
  .big .dim { font-size: 18px; }
</style>
