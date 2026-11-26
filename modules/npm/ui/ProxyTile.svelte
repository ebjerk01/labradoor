<script>
  import { days, dayTxt, certLevel } from './net.js';
  let { data } = $props();
  const on = $derived(data.hosts.filter((h) => h.enabled && h.online !== false).length);
  const min = $derived(Math.min(...data.certs.map((c) => days(c.expires))));
</script>

<div class="t">
  <span class="mono big" class:bad={on < data.hosts.filter((h) => h.enabled).length}>{on}<span class="dim">/{data.hosts.length}</span></span>
  <span class="cap">hosts · cert <span class={certLevel(min)}>{dayTxt(min)}</span> · {data.hosts.filter((h) => h.originLock).length} cf-only</span>
</div>

<style>
  .t { display: flex; flex-direction: column; margin-top: auto; gap: 2px; }
  .big { font-size: 30px; font-weight: 500; letter-spacing: -.02em; }
  .big .dim { font-size: 18px; }
</style>
