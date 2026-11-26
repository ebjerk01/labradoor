<script>
  // Settings → a v2 module's connection: the fields its manifest asks for (URL, API key, login …), a test call with the
  // values as typed, and save. Secrets are write-only: the gateway says whether one is set, never what it is.
  import { api } from '$lab/api.js';
  import { lab } from '$lab/lab.svelte.js';

  let { m, editable, onsaved } = $props();
  let cfg = $state(null);
  let err = $state('');
  let draft = $state({});
  let busy = $state('');
  let result = $state(null);
  let failedSave = $state(false);

  async function load() {
    try { cfg = await api.get(`/api/config/${m.id}`); draft = {}; err = ''; }
    catch (e) { err = e.status === 403 ? 'the connection is set by the owner' : e.message; }
  }
  $effect(() => { void m.id; load(); });

  // only what was touched goes to the gateway; an untouched secret stays as stored
  const changed = () => Object.fromEntries(Object.entries(draft).filter(([, v]) => v !== undefined));
  const value = (f) => (f.key in draft ? draft[f.key] : f.value ?? (f.type === 'bool' ? true : ''));

  async function run(kind, force = false) {
    busy = kind; result = null; failedSave = false;
    try {
      if (kind === 'test') {
        const r = await api.post(`/api/config/${m.id}/test`, { values: changed() });
        result = r.test || { ok: false, error: r.missing?.length ? `missing: ${r.missing.join(', ')}` : 'no test call' };
      } else {
        const r = await api.post(`/api/config/${m.id}`, { values: changed(), force });
        result = r.test; cfg = r; draft = {};
        lab.notify(`${m.id}: connection saved ✓`);
        onsaved?.();
      }
    } catch (e) {
      if (e.status === 422) { result = e.body?.test; failedSave = true; } else lab.notify(`${m.id}: ${e.message}`, 'bad');
    }
    busy = '';
  }
</script>

<span class="k">connection</span>
<div class="cf">
  {#if err}<span class="mono dim">{err}</span>
  {:else if !cfg}<span class="mono dim spin">loading</span>
  {:else}
    {#if cfg.needsSetup}<span class="mono warn small">▲ needs setup: {cfg.missing.join(', ')}</span>{/if}
    {#if !cfg.secretsReady}<span class="mono bad small">■ no master key on the gateway: secrets can't be stored</span>{/if}
    {#each cfg.fields as f (f.key)}
      <label class="fl">
        <span class="mono lbl" title={f.help || ''}>{f.label || f.key}{f.required ? ' *' : ''}</span>
        {#if f.type === 'bool'}
          <button type="button" class="tog mono" aria-pressed={value(f) !== false} disabled={!editable}
            onclick={() => (draft[f.key] = !(value(f) !== false))}>{value(f) !== false ? 'on' : 'off'}</button>
        {:else if f.type === 'enum'}
          <select class="field mono" value={value(f)} disabled={!editable} onchange={(e) => (draft[f.key] = e.currentTarget.value)}>
            {#each f.options as o}<option value={o}>{o}</option>{/each}
          </select>
        {:else if f.type === 'secret' && f.multiline}
          <!-- a private key: write-only like every secret; the box stays empty, the placeholder says whether one is set -->
          <textarea class="field mono area" rows="4" spellcheck="false" autocomplete="off" disabled={!editable}
            placeholder={f.set ? '•••••• set — paste to replace' : 'not set'} value={draft[f.key] ?? ''}
            oninput={(e) => (draft[f.key] = e.currentTarget.value || undefined)}></textarea>
        {:else if f.type === 'secret'}
          <input class="field mono" type="password" autocomplete="new-password" disabled={!editable}
            placeholder={f.set ? '•••••• set — type to replace' : 'not set'} value={draft[f.key] ?? ''}
            oninput={(e) => (draft[f.key] = e.currentTarget.value || undefined)} />
        {:else if f.type === 'int'}
          <input class="field mono" type="number" min={f.min} max={f.max} value={value(f)} disabled={!editable}
            oninput={(e) => (draft[f.key] = Number(e.currentTarget.value))} />
        {:else if f.type === 'list'}
          <input class="field mono" value={(value(f) || []).join(', ')} disabled={!editable}
            oninput={(e) => (draft[f.key] = e.currentTarget.value.split(',').map((x) => x.trim()).filter(Boolean))} />
        {:else if f.multiline}
          <textarea class="field mono area" rows="4" spellcheck="false" placeholder={f.placeholder || ''} value={value(f)}
            disabled={!editable} oninput={(e) => (draft[f.key] = e.currentTarget.value)}></textarea>
        {:else}
          <input class="field mono" type={f.type === 'url' ? 'url' : 'text'} placeholder={f.placeholder || ''} value={value(f)}
            disabled={!editable} oninput={(e) => (draft[f.key] = e.currentTarget.value)} />
        {/if}
        {#if f.help}<span class="dim small help">{f.help}</span>{/if}
      </label>
    {/each}
    {#if editable}
      <div class="acts">
        {#if cfg.testable}<button class="btn" disabled={!!busy} onclick={() => run('test')}>{busy === 'test' ? 'testing…' : 'test'}</button>{/if}
        <button class="btn primary" disabled={!!busy || !Object.keys(changed()).length} onclick={() => run('save')}>{busy === 'save' ? 'saving…' : 'save'}</button>
        {#if failedSave}<button class="btn" onclick={() => run('save', true)}>save anyway</button>{/if}
        {#if result}
          <span class="mono small {result.ok ? 'ok' : 'bad'}">{result.ok ? `● ok · ${result.detail ? result.detail + ' · ' : ''}${result.ms} ms` : `■ ${result.error || 'failed'}`}</span>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .cf { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .fl { display: grid; grid-template-columns: 150px minmax(0, 360px); gap: 4px 12px; align-items: center; }
  .lbl { font-size: 12px; color: var(--dim); }
  .help { grid-column: 2; }
  .small { font-size: 11.5px; }
  .field { padding: 5px 8px; font-size: 12px; }
  .area { resize: vertical; min-height: 64px; white-space: pre; overflow-x: auto; }
  .acts { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .k { font: 12px "Geist Mono Variable", monospace; color: var(--dim); align-self: start; padding-top: 6px; }
  .tog { justify-self: start; min-width: 52px; padding: 4px 10px; font-size: 11.5px; border: 1px solid var(--line); border-radius: 12px; background: transparent; color: var(--dim); }
  .tog[aria-pressed="true"] { background: var(--sig); border-color: var(--sig); color: var(--sigink); }
  @media (max-width: 700px) { .fl { grid-template-columns: 1fr; } .help { grid-column: 1; } }
</style>
