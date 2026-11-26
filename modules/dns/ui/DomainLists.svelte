<script>
  // allowed / blocked domains (Technitium "Allowed zones" and "Blocked zones"). The API is a zone tree: browse from the
  // root, an entry is a zone with its own SOA. admin may add and remove. Needs Technitium permissions Allowed/Blocked
  // View (+ Modify to add, + Delete to remove) for the API user.
  import Section from '$lab/Section.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import Lazy from '$lab/Lazy.svelte';
  import { lazy, act } from '$lab/sdk.js';
  import { unwrap } from './tdns.js';
  let { ctx } = $props();

  let kind = $state('blocked'); // 'allowed' | 'blocked'
  let at = $state(''); // the domain being browsed ('' = root)
  let name = $state('');
  const list = lazy(() => ctx, () => `/api/${kind}/list`, { query: () => (at ? { domain: at } : {}), pick: unwrap, keep: false });

  const clean = (s) => s.trim().toLowerCase().replace(/\.$/, '');
  const verb = $derived(kind === 'allowed' ? 'allow' : 'block');
  const undo = $derived(kind === 'allowed' ? 'remove from allowed' : 'unblock');
  const child = (z) => (at && !z.endsWith(`.${at}`) && z !== at ? `${z}.${at}` : z);
  const up = $derived(at.includes('.') ? at.slice(at.indexOf('.') + 1) : '');
  const isEntry = (r) => (r?.records || []).some((x) => x.type === 'SOA' && x.name === at);

  async function add(e) {
    e.preventDefault();
    const d = clean(name);
    if (!d) return;
    if (await act(ctx, { path: `/api/${kind}/add`, query: { domain: d }, label: `${verb} ${d}`, check: unwrap })) { name = ''; at = d.includes('.') ? d.slice(d.indexOf('.') + 1) : ''; list.reload(); }
  }
  const switchTo = (k) => { kind = k; at = ''; };
</script>

<Section title="allowed · blocked domains" src="technitium">
  <div class="bar">
    <div class="seg" role="group" aria-label="List">
      {#each ['blocked', 'allowed'] as k}<button aria-pressed={kind === k} onclick={() => switchTo(k)}>{k}</button>{/each}
    </div>
    {#if ctx.can('POST', `/api/${kind}/add`) !== 'no'}
      <form class="add" onsubmit={add}>
        <input class="field mono" placeholder="example.com" bind:value={name} aria-label="Domain to {verb}" required />
        <button class="btn primary">{verb} domain</button>
      </form>
    {/if}
  </div>
  <p class="mono dim path">~/{kind}{at ? ` / ${at}` : ''}{#if at} <button class="lnk" onclick={() => (at = up)}>up</button>{/if}</p>
  <Lazy of={list} empty="nothing {kind} here">
    {#snippet children(r)}
      <ul class="l">
        {#if isEntry(r)}
          <li class="mono"><span class="sig">●</span> {at} <span class="dim">· {kind}</span>
            <ActionButton {ctx} path={`/api/${kind}/delete`} query={{ domain: at }} label={`${undo} ${at}`} confirm={`${undo} ${at}?`} check={unwrap}
              done={() => { at = up; list.reload(); }} small>{undo}</ActionButton></li>
        {/if}
        {#each r.zones || [] as z}
          <li class="mono"><button class="lnk" onclick={() => (at = child(z))}>{child(z)}</button></li>
        {/each}
        {#if !isEntry(r) && !(r.zones || []).length}<li class="mono dim">{at ? `nothing ${kind} under ${at}` : `no ${kind} domains`}</li>{/if}
      </ul>
    {/snippet}
  </Lazy>
</Section>

<style>
  .bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .add .btn { white-space: nowrap; }
  .add { display: flex; gap: 6px; align-items: center; }
  .add .field { max-width: 220px; padding: 5px 8px; font-size: 12px; }
  .path { font-size: 11.5px; margin: 8px 0 4px; }
  .l { list-style: none; margin: 0; padding: 0; }
  .l li { padding: 4px 0; border-bottom: 1px solid var(--q); font-size: 12px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
