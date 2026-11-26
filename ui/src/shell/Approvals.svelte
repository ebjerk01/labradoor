<script>
  import { lab } from '$lab/lab.svelte.js';
  import Icon from '$lab/Icon.svelte';
  import { ago } from '$lab/fmt.js';
  const ST = { pending: 'sig', done: 'ok', denied: 'bad', failed: 'bad', expired: 'faint', cancelled: 'faint', invalid: 'faint', running: 'sig' };
  // admins: their own requests (past ones too) by default, everyone's on "all" (results stay owner-only)
  let who = $state('mine');
  const shown = $derived(lab.role === 'owner' || who === 'all' ? lab.approvals : lab.approvals.filter((a) => a.requester === lab.me?.username));
</script>

{#if lab.drawer === 'approvals'}
  <div class="drawer" role="dialog" aria-label="Approvals">
    <div class="h"><span class="cap">~/approvals</span><button class="btn" aria-label="Close" onclick={() => (lab.drawer = null)}><Icon name="close" size={12} /></button></div>
    {#if lab.role === 'owner'}
      <p class="mono dim intro">admins ask for one-time approval of owner-only actions</p>
    {:else}
      <div class="intro filt">
        <div class="seg" role="group" aria-label="Whose requests">
          {#each [['mine', 'my requests'], ['all', 'all requests']] as [k, l]}<button aria-pressed={who === k} onclick={() => (who = k)}>{l}</button>{/each}
        </div>
        <span class="mono dim">ask owner from any locked action</span>
      </div>
    {/if}
    {#each shown as a (a.id)}
      <div class="ap">
        <div class="top"><span class="mono {ST[a.status] || 'dim'}">{a.status}</span><span class="mono dim">#{a.id} · {ago(a.created, lab.now)}</span></div>
        <div class="lbl">{a.label}</div>
        <div class="mono dim small">{a.requester} · {a.module}: {a.method} {a.path}{a.query ? `?${a.query}` : ''}</div>
        <!-- the label is the asker's text: what runs is method + path + query + this body, exactly -->
        {#if a.body}<pre class="mono small body" title="request body that will be sent">{a.body.length > 600 ? a.body.slice(0, 600) + ' …' : a.body}</pre>{/if}
        {#if a.reason}<div class="small">“{a.reason}”</div>{/if}
        {#if a.result_code}<div class="mono small dim">→ {a.result_code} {(a.result_body || '').slice(0, 120)}</div>{/if}
        {#if a.status === 'pending'}
          <div class="row">
            {#if lab.role === 'owner'}
              <button class="btn primary" onclick={() => lab.decide(a.id, 'approve')}><Icon name="check" size={13} />approve once</button>
              <button class="btn" onclick={() => lab.decide(a.id, 'deny')}>deny</button>
            {:else}
              <span class="mono dim spin small">waiting for owner</span>
              <button class="btn" onclick={() => lab.decide(a.id, 'cancel')}>cancel</button>
            {/if}
          </div>
        {/if}
      </div>
    {:else}
      <p class="mono dim intro">{lab.role === 'owner' ? 'nothing to decide' : who === 'mine' ? 'you have not asked for anything yet' : 'no requests yet'}</p>
    {/each}
  </div>
{/if}

<style>
  .drawer { position: fixed; right: 0; top: 0; bottom: 0; width: min(400px, 100vw); background: var(--panel); border-left: 1px solid var(--line);
    z-index: 30; overflow-y: auto; box-shadow: -20px 0 50px rgba(0, 0, 0, .25); }
  .h { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--line); }
  .intro { padding: 0 18px; font-size: 11.5px; }
  .filt { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 10px 18px; }
  .ap { padding: 12px 18px; border-bottom: 1px solid var(--q); display: flex; flex-direction: column; gap: 4px; }
  .top { display: flex; justify-content: space-between; font-size: 11.5px; }
  .lbl { font-size: 14px; }
  .small { font-size: 11.5px; }
  .body { margin: 2px 0; padding: 4px 6px; background: var(--q); white-space: pre-wrap; word-break: break-all; max-height: 140px; overflow-y: auto; }
  .row { display: flex; gap: 8px; margin-top: 6px; align-items: center; }
  .spin { display: inline-flex; flex-direction: row-reverse; gap: 6px; flex: 1; justify-content: flex-end; }
</style>
