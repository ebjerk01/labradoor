<script>
  // Recent Proxmox tasks of one node (optionally one guest); a click shows the task's log tail. Running tasks this token
  // started can be stopped (Proxmox only lets a user stop its own tasks).
  import Lines from '$lab/Lines.svelte';
  import { ago } from '$lab/fmt.js';
  import Act from './Act.svelte';
  import { lazy, errText } from '$lab/sdk.js';
  import { taskOk } from './pve.svelte.js';
  let { ctx, node, vmid = null, limit = 12 } = $props();

  const res = lazy(() => ctx, () => `/nodes/${node}/tasks`, { query: () => ({ limit, source: 'all', ...(vmid != null ? { vmid: String(vmid) } : {}) }), pick: (r) => r?.data ?? null });
  let open = $state(null);
  let log = $state(null);

  async function show(t) {
    if (open === t.upid) { open = null; return; }
    open = t.upid;
    log = null;
    try {
      const r = await ctx.api.get(`/nodes/${node}/tasks/${encodeURIComponent(t.upid)}/log`, { start: 0, limit: 5000 });
      log = (r.data || []).map((l) => l.t).filter((x) => x && x !== 'no content').slice(-40);
    } catch (e) { log = [errText(e)]; }
  }
  const glyph = (t) => (!t.endtime ? '◌' : taskOk(t) ? '●' : '■');
  const st = (t) => (!t.endtime ? null : taskOk(t) ? 'ok' : 'bad');
</script>

{#if res.error}<span class="mono bad small">{res.error}</span>
{:else if !res.data}<span class="mono dim small spin">tasks </span>
{:else}
  <div class="list">
    {#each res.data as t (t.upid)}
      <div class="t">
        <button class="lnk r" onclick={() => show(t)}>
          <span class="mono g" class:ok={st(t) === 'ok'} class:bad={st(t) === 'bad'} class:sig={!t.endtime}>{glyph(t)}</span>
          <span class="mono n">{t.type}{t.id ? ` ${t.id}` : ''}</span>
          <span class="mono dim u">{t.user.replace(/@.*!/, '!').replace('@pam', '')}</span>
          <span class="mono dim a">{ago(t.endtime || t.starttime)}</span>
        </button>
        {#if !t.endtime && t.user.startsWith('lab@pve')}
          <Act {ctx} method="DELETE" path={`/nodes/${node}/tasks/${encodeURIComponent(t.upid)}`} label="stop task {t.type} {t.id || ''}" text="stop" confirm done={res.reload} />
        {/if}
      </div>
      {#if open === t.upid}
        {#if !taskOk(t) && t.status}<span class="mono bad small">{t.status}</span>{/if}
        <Lines items={(log || ['…']).map((x) => ({ p: '>', t: x }))} empty="no log" />
      {/if}
    {:else}
      <span class="mono dim small">no tasks</span>
    {/each}
  </div>
{/if}

<style>
  .small { font-size: 11.5px; }
  .list { display: flex; flex-direction: column; max-height: 360px; overflow-y: auto; }
  .t { display: flex; align-items: center; gap: 6px; border-bottom: 1px solid var(--q); }
  .r { flex: 1; display: grid; grid-template-columns: 14px 1fr auto 34px; gap: 8px; padding: 3px 0; font-size: 11.5px; min-width: 0; }
  .n, .u { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .a { text-align: right; }
</style>
