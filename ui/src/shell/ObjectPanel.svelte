<script>
  import { lab } from '$lab/lab.svelte.js';
  import Icon from '$lab/Icon.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Section from '$lab/Section.svelte';
  import Lines from '$lab/Lines.svelte';
  import { ago } from '$lab/fmt.js';
  import { dedupeActions } from '$lab/routes.js';

  let { closable = true } = $props();
  const obj = $derived(lab.sel ? lab.objects.get(lab.sel) : null);
  const facets = $derived(lab.facets(obj));
  // how many objects each module knows: the module that knows fewer is the more specific one for a shared verb
  const sizes = $derived.by(() => { const c = {}; for (const o of lab.objects.values()) for (const s of o.sources || []) c[s] = (c[s] || 0) + 1; return c; });
  // one button per verb (proxmox "reboot" + manage "reboot" → one); the button names the module that runs it
  const actions = $derived(dedupeActions(lab.actions(obj), obj || {}, (m) => sizes[m]));
  const objAlerts = $derived(obj ? lab.alerts.filter((a) => a.object === obj.id) : []);
  const locked = $derived(obj?.ownerOnly && lab.role !== 'owner');

  // a short |/-\ while the facets "arrive" — and real loading when the modules are syncing
  let settling = $state(false);
  let last = null;
  $effect(() => {
    const id = lab.sel;
    if (id !== last) {
      last = id;
      settling = true;
      const t = setTimeout(() => (settling = false), 380);
      return () => clearTimeout(t);
    }
  });
</script>

<aside class="panel" class:open={lab.panelOpen && !!obj} aria-label="Object">
  {#if !obj}
    <div class="empty mono dim">{lab.sel ? `${lab.sel}: not known to any module` : 'select an object'}</div>
  {:else}
    <div class="head">
      <div class="title">
        <Glyph status={obj.status} size={13} />
        <h2>{obj.name}</h2>
        {#if obj.kind}<span class="mono kind">{obj.kind}</span>{/if}
        <button class="btn x" class:phone-only={!closable} aria-label="Close" onclick={() => lab.close()}><Icon name="close" size={12} /></button>
      </div>
      <span class="mono dim meta">{[obj.meta, obj.parent && `on ${obj.parent}`, obj.sources?.join(' + ')].filter(Boolean).join(' · ')}</span>
      {#if locked}
        <div class="lock">
          <Icon name="lock" size={15} />
          <span class="mono dim">owner only · {obj.ownerOnly}</span>
        </div>
      {/if}
      {#if actions.length}
        <div class="acts">
          {#each actions as a}
            <button class="btn" class:askbtn={a.verdict === 'ask'} onclick={() => lab.run(a)}
              title="{a.verdict === 'ask' ? 'needs a one-time approval from the owner · ' : ''}runs in {a.module}{a.also?.length ? ` (also offered by ${a.also.join(', ')})` : ''}">
              <Icon name={a.verdict === 'ask' ? 'lock' : a.icon || 'play'} size={13} />{a.label}<span class="mod">{a.module}</span>{#if a.verdict === 'ask'}<span class="ask">ask owner</span>{/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>

    {#if settling}
      <div class="mono spin loading">fetching facets</div>
    {:else}
      <div class="fade">
        {#if objAlerts.length}
          <Section title="alerts" src={[...new Set(objAlerts.map((a) => a.module))].join(' ')}>
            <Lines items={objAlerts.map((a) => ({ p: a.status === 'bad' ? '■' : '▲', s: a.status, t: `${a.title} · ${ago(a.since, lab.now)}` }))} />
          </Section>
        {/if}
        {#each facets as f (f.module)}
          {@const C = f.component}
          <C object={obj} data={lab.data[f.module]} ctx={lab.ctx(f.module)} />
        {/each}
        {#if !facets.length && obj.about}
          <Section title="about"><p class="about">{obj.about}</p></Section>
        {/if}
        {#if !facets.length && !obj.about}
          <div class="empty mono dim">no module has facets for “{obj.type}” yet</div>
        {/if}
      </div>
    {/if}
  {/if}
</aside>

<style>
  .panel { flex: 1 1 340px; max-width: 440px; min-width: 300px; border-left: 1px solid var(--line); background: var(--panel); display: flex; flex-direction: column; }
  .head { padding: 18px 20px 14px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px; }
  .title { display: flex; align-items: center; gap: 10px; }
  h2 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -.02em; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .kind { font-size: 11.5px; color: var(--dim); border: 1px solid var(--line); padding: 1px 6px; border-radius: 3px; white-space: nowrap; }
  .x { padding: 6px; }
  .meta { font-size: 11.5px; }
  .lock { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px dashed var(--sig); border-radius: 4px; color: var(--sig); font-size: 11.5px; }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
  .askbtn { border-style: dashed; border-color: var(--sig); }
  .mod { font-size: 10px; color: var(--dim); opacity: .75; }
  .ask { font-size: 10px; color: var(--sig); }
  .loading { padding: 20px; font-size: 12px; color: var(--dim); display: flex; flex-direction: row-reverse; justify-content: flex-end; gap: 8px; }
  .empty { padding: 20px; font-size: 12px; }
  .about { margin: 0; font-size: 13px; color: var(--dim); }
  @media (max-width: 860px) { .panel { max-width: none; border-left: none; border-top: 1px solid var(--line); } }
  /* phone: an opened object is a full-screen sheet (it used to land ~6000px below the overview, out of sight);
     nothing selected = no panel at all */
  .phone-only { display: none; }
  @media (max-width: 760px) {
    .panel:not(.open) { display: none; }
    .panel.open { position: fixed; inset: 0; z-index: 45; max-width: none; min-width: 0; border: none; overflow-y: auto; overflow-x: hidden;
      overscroll-behavior: contain; }
    .phone-only { display: inline-flex; }
  }
</style>
