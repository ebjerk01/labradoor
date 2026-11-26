<script>
  // API keys: owner only (secret). Admins don't read them, not even through an approval. Lab's own key is marked: revoking
  // it cuts lab off from Jellyfin until a new one is put in /etc/lab/keys/jellyfin.apikey on CT 132.
  import Icon from '$lab/Icon.svelte';
  import { ago } from '$lab/fmt.js';
  import { lazy, qs } from '$lab/sdk.js';
  import { write } from './store.svelte.js';
  let { ctx } = $props();

  const verdict = $derived(ctx.can('GET', '/Auth/Keys'));
  const keys = lazy(() => ctx, () => (verdict === 'yes' ? '/Auth/Keys' : null));
  let shown = $state({});
  let app = $state('');
  const USED = { lab: 'lab (this site)', driftsstatus: 'Driftsstatus checks', seerr: 'Seerr' };
  const mask = (t) => `${t.slice(0, 4)}…${t.slice(-4)}`;
  const when = (d) => (d && !d.startsWith('0001') ? ago(Date.parse(d) / 1000, ctx.now) : '–');
  async function create(e) {
    e.preventDefault();
    const name = app.trim();
    if (!/^[\w .-]{2,40}$/.test(name)) return ctx.notify('an app name: letters, digits, space . - _', 'bad');
    if (await write(ctx, [], { path: `/Auth/Keys?${qs({ app: name })}`, label: `jellyfin: create API key ${name}` })) { app = ''; keys.reload(); }
  }
  async function revoke(k) {
    const used = USED[String(k.AppName).toLowerCase()];
    const txt = `Revoke the Jellyfin API key “${k.AppName}”?${used ? `\n\nIt is used by ${used}: that stops working until it gets a new key.` : ''}`;
    if (used && String(k.AppName).toLowerCase() === 'lab' && !confirm('This is LAB\'S OWN key. Lab loses Jellyfin until a new key is installed on CT 132. Continue?')) return;
    if (await write(ctx, [], { method: 'DELETE', path: `/Auth/Keys/${k.AccessToken}`, label: `jellyfin: revoke API key ${k.AppName}`, confirm: txt })) keys.reload();
  }
  const copy = async (t) => { try { await navigator.clipboard.writeText(t); ctx.notify('copied'); } catch { ctx.notify('copy failed', 'bad'); } };
</script>

{#if verdict !== 'yes'}
  <p class="mono dim s"><Icon name="lock" size={11} /> API keys are secrets: owner only (lab does not even send them to admins)</p>
{:else}
  {#if keys.error}<p class="mono bad s">{keys.error}</p>{/if}
  <div class="scroll-x"><div class="k">
    <span class="h">app</span><span class="h">key</span><span class="h">created</span><span class="h">used</span><span class="h"></span>
    {#each keys.data?.Items || [] as k (k.AccessToken)}
      {@const used = USED[String(k.AppName).toLowerCase()]}
      <span>{k.AppName}{#if used}<span class="mono dim s"> · {used}</span>{/if}</span>
      <span class="mono s tok">
        <button class="lnk mono" title="show / hide" onclick={() => (shown[k.AccessToken] = !shown[k.AccessToken])}>{shown[k.AccessToken] ? k.AccessToken : mask(k.AccessToken)}</button>
        {#if shown[k.AccessToken]}<button class="lnk dim" onclick={() => copy(k.AccessToken)}>copy</button>{/if}
      </span>
      <span class="mono dim s">{when(k.DateCreated)}</span>
      <span class="mono dim s">{when(k.DateLastActivity)}</span>
      <button class="btn x danger" aria-label="revoke {k.AppName}" onclick={() => revoke(k)}><Icon name="close" size={11} /></button>
    {/each}
  </div></div>
  <form class="add" onsubmit={create}>
    <input class="field" placeholder="app name" bind:value={app} aria-label="App name for the new key" />
    <button class="btn"><Icon name="key" size={12} />new key</button>
    <span class="mono dim s">the new key shows in the list (click to reveal)</span>
  </form>
{/if}

<style>
  .k { display: grid; grid-template-columns: minmax(110px, 1fr) minmax(120px, 1.4fr) auto auto auto; gap: 6px 14px; align-items: center; font-size: 12.5px; min-width: 480px; }
  .h { font: 10px "Geist Mono Variable", monospace; color: var(--dim); }
  .tok { display: flex; gap: 8px; word-break: break-all; }
  .s { font-size: 10.5px; }
  .x { padding: 3px 6px; }
  .add { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font-size: 12px; color: var(--ink); }
  .danger:not(:disabled) { color: var(--bad); border-color: var(--bad); }
  .bad { color: var(--bad); }
</style>
