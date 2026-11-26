<script>
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';
  let rows = $state([]);
  let q = $state('');
  async function load() { try { rows = (await api.get('/api/audit', { limit: 500 })).audit; } catch (e) { lab.notify(e.message, 'bad'); } }
  $effect(() => { load(); });
  const shown = $derived(q ? rows.filter((r) => JSON.stringify(r).toLowerCase().includes(q.toLowerCase())) : rows);
  const ts = (t) => new Date(t * 1000).toLocaleString('nb-NO', { dateStyle: 'short', timeStyle: 'medium' });
</script>

<div class="log fade">
  <div class="bar"><span class="cap">~/log · audit · {shown.length}</span><input class="field mono" placeholder="$ grep …" bind:value={q} aria-label="Filter" /></div>
  <div class="scroll-x"><table class="mono">
    <thead><tr><th>when</th><th>who</th><th>role</th><th>action</th><th>module</th><th>target</th><th>res</th><th>detail</th></tr></thead>
    <tbody>
      {#each shown as r (r.id)}
        <tr class="row"><td class="dim">{ts(r.ts)}</td><td>{r.username || '-'}</td><td class="dim">{r.role || ''}</td><td class="sig">{r.action}</td>
          <td>{r.module || ''}</td><td>{r.target || ''}</td><td class:bad={Number(r.result) >= 400}>{r.result || ''}</td><td class="dim det">{r.detail || ''}</td></tr>
      {/each}
    </tbody>
  </table></div>
</div>

<style>
  .bar { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 12px 20px; }
  .bar input { max-width: 280px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 900px; }
  th { text-align: left; font-weight: 400; color: var(--dim); padding: 6px 12px; border-bottom: 1px solid var(--line); }
  td { padding: 5px 12px; border-bottom: 1px solid var(--q); white-space: nowrap; }
  .det { max-width: 360px; overflow: hidden; text-overflow: ellipsis; }
</style>
