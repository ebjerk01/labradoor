<script>
  // Settings → ~/updates (owner only): the installed version, the release index, check → notes → update, roll back.
  // The gateway asks a root helper that verifies every release (signature, sha256, MANIFEST) before installing it; an
  // install or rollback runs as a job that outlives the gateway's own restart, so this polls /api/update/status and
  // reloads the page when a new version is live (new UI files).
  import { lab } from '$lab/lab.svelte.js';
  import { api } from '$lab/api.js';

  let info = $state(null);
  let err = $state('');
  let draft = $state(null);
  let busy = $state('');
  let checked = $state(null);
  let progress = $state('');
  let target = $state('');
  let watching = $state('');   // job id being followed

  async function load() {
    try { info = await api.get('/api/update'); err = ''; } catch (e) { err = e.message; }
  }
  $effect(() => { if (lab.role === 'owner') load(); });

  const st = $derived(info?.helper || null);
  const job = $derived(st?.job || null);
  const running = $derived(job && (job.state === 'queued' || job.state === 'running'));
  const releases = $derived((st?.releases || []).slice().reverse());
  const previous = $derived.by(() => {
    const r = st?.releases || [];
    const i = r.findIndex((x) => x.live);
    return i > 0 ? r[i - 1].name : '';
  });
  const index = $derived(draft ?? info?.index?.url ?? '');
  const ago = (t) => (t ? new Date(t * 1000).toLocaleString() : '');

  async function saveIndex() {
    busy = 'save';
    try { const r = await api.post('/api/update/settings', { index: draft || null }); info.index = r.index; draft = null; checked = null; lab.notify('updates: index saved ✓'); }
    catch (e) { lab.notify(e.message, 'bad'); } finally { busy = ''; }
  }
  async function check() {
    busy = 'check'; checked = null;
    try { checked = await api.post('/api/update/check'); }
    catch (e) { checked = { error: e.message }; } finally { busy = ''; }
  }

  // follow a job: the gateway restarts in the middle of an install, so failed polls are expected for a few seconds
  async function follow(id, after) {
    watching = id;
    const until = Date.now() + 20 * 60 * 1000;
    while (watching === id && Date.now() < until) {
      await new Promise((r) => setTimeout(r, 2000));
      let s;
      try { s = await api.get('/api/update/status'); } catch { progress = 'waiting for the gateway (restarting) …'; continue; }
      if (info) info.helper = s;
      const j = s.job;
      if (!j || j.id !== id) continue;
      if (j.state === 'queued' || j.state === 'running') { progress = j.message || j.state; continue; }
      watching = ''; progress = '';
      lab.notify(j.message || j.state, j.state === 'ok' ? 'ok' : 'bad');
      if (j.state === 'ok' && after) after();
      await load();
      return;
    }
  }

  async function update(v) {
    if (!confirm(`Install ${v}? The gateway restarts (about 10 seconds); the database is backed up first and a failed install rolls back by itself.`)) return;
    busy = 'update'; progress = `downloading + verifying ${v} …`;
    try {
      await api.post('/api/update/stage', { version: v });
      progress = `installing ${v} …`;
      const r = await api.post('/api/update/apply', { version: v });
      busy = '';
      await follow(r.job, () => setTimeout(() => location.reload(), 1500));
    } catch (e) { lab.notify(e.message, 'bad'); progress = ''; } finally { busy = ''; }
  }

  async function rollback() {
    const rel = target || previous;
    if (!rel) return;
    const msg = `Roll back to ${rel}? (If the live release changed the database, the older one can't start: the rollback then undoes itself. Restoring the database too is done as root on the host: lab-admin rollback --with-db)`;
    if (!confirm(msg)) return;
    busy = 'rollback'; progress = `rolling back to ${rel} …`;
    try {
      const r = await api.post('/api/update/rollback', { release: rel });
      busy = '';
      await follow(r.job, () => setTimeout(() => location.reload(), 1500));
    } catch (e) { lab.notify(e.message, 'bad'); progress = ''; } finally { busy = ''; }
  }
  $effect(() => { if (running && !watching && job?.id) follow(job.id); });
</script>

{#if lab.role === 'owner'}
  <section>
    <div class="sh">
      <span class="cap">~/updates</span>
      <span class="mono dim">owner only · signed releases, verified before they are installed</span>
    </div>
    {#if info}
      <div class="grid">
        <span class="k">installed</span>
        <div class="fld mono">
          <span>{st?.version || info.build.version}</span>
          {#if st?.commit || info.build.commit}<span class="dim small">{(st?.commit || info.build.commit).slice(0, 7)}</span>{/if}
          {#if st?.live}<span class="dim small">release {st.live}</span>{/if}
        </div>
        <label class="k" for="up-index">release index</label>
        <div class="fld">
          <input id="up-index" class="field mono" spellcheck="false" placeholder="https://… /index.json (empty = updates off)"
            disabled={!!busy} value={index} oninput={(e) => (draft = e.currentTarget.value)} />
          {#if info.index.source === 'env'}<span class="tag mono" title="the default from /etc/lab/lab.env; a URL saved here overrides it, an empty one goes back to it">default {info.index.env}</span>{/if}
          {#if draft !== null}<button class="btn" disabled={!!busy} onclick={saveIndex}>save</button>{/if}
        </div>
        <span class="k">signing key</span>
        <span class="mono small {st?.key ? 'dim' : 'warn'}">{st ? (st.key || `▲ none (${st.key_file}): updates can't be verified`) : '—'}{st?.allow_http ? ' · ▲ http:// LAN test servers allowed' : ''}</span>
        {#if info.helperError}<span class="k">helper</span><span class="mono small bad">■ {info.helperError}</span>{/if}
        <span></span>
        <div class="row">
          <button class="btn" disabled={!!busy || running || !info.index.url || draft !== null} onclick={check}>{busy === 'check' ? 'checking…' : 'check for updates'}</button>
          {#if checked?.update}
            <button class="btn primary" disabled={!!busy || running} onclick={() => update(checked.update)}>{busy === 'update' ? 'updating…' : `update to ${checked.update}`}</button>
          {/if}
          {#if checked && !checked.error}<span class="mono small {checked.update ? 'ok' : 'dim'}">{checked.update ? `● ${checked.update} available` : `● up to date (newest: ${checked.latest || '—'})`}</span>{/if}
          {#if checked?.error}<span class="mono small bad">■ {checked.error}</span>{/if}
        </div>
      </div>

      {#if checked?.releases?.length}
        <div class="notes">
          {#each checked.releases.filter((r) => r.ok || r.version === checked.latest) as r (r.version)}
            <div class="rel">
              <div class="mono"><b>{r.version}</b> <span class="dim small">{r.date}</span>
                {#if !r.ok}<span class="small warn">▲ {r.why}</span>{/if}</div>
              {#if r.notes}<pre class="mono small">{r.notes}</pre>{/if}
            </div>
          {/each}
        </div>
      {/if}

      {#if progress || running}
        <p class="mono small pad ok"><span class="spin">◐</span> {progress || job?.message}</p>
      {/if}

      <div class="sub mono">roll back</div>
      <div class="grid">
        <label class="k" for="up-rel">release</label>
        <div class="fld">
          <select id="up-rel" class="field mono sel" bind:value={target} disabled={!!busy || running}>
            <option value="">previous ({previous || 'none'})</option>
            {#each releases.filter((r) => !r.live) as r (r.name)}<option value={r.name}>{r.name} · {r.version || '?'} {r.commit.slice(0, 7)}</option>{/each}
          </select>
          <button class="btn" disabled={!!busy || running || !(target || previous)} onclick={rollback}>{busy === 'rollback' ? 'rolling back…' : 'roll back'}</button>
          <span class="mono small chk" title="the gateway can't ask root to put database files back">code only · with the database: <code>lab-admin rollback --with-db</code> as root on the host</span>
        </div>
        {#if job}
          <span class="k">last job</span>
          <div class="mono small">
            <span class={job.state === 'ok' ? 'ok' : job.state === 'failed' || job.state === 'interrupted' ? 'bad' : 'dim'}>{job.state}</span>
            {job.op} {job.target} · {job.by || '?'} · {ago(job.finished || job.started)} — {job.message}
            {#if job.state !== 'ok' && job.tail?.length}<pre class="tail">{job.tail.join('\n')}</pre>{/if}
          </div>
        {/if}
      </div>
    {:else if err}
      <p class="mono bad pad">{err}</p>
    {/if}
  </section>
{/if}

<style>
  section { border-bottom: 1px solid var(--line); padding-bottom: 8px; }
  .sh { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; padding: 14px 20px 6px; font-size: 11.5px; }
  .sub { padding: 10px 20px 2px; font-size: 12px; color: var(--ink); }
  .grid { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 8px 16px; align-items: center; padding: 6px 20px 10px; max-width: 900px; }
  .k { font: 12px "Geist Mono Variable", monospace; color: var(--dim); }
  .fld { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-width: 0; }
  .fld .field { flex: 1 1 220px; max-width: 520px; padding: 6px 8px; font-size: 12px; }
  .sel { max-width: 340px; }
  .field:disabled { opacity: .7; }
  .tag { font-size: 10.5px; padding: 1px 6px; border: 1px solid var(--line); border-radius: 3px; color: var(--dim); }
  .small { font-size: 11.5px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .pad { padding: 4px 20px; }
  .chk { display: inline-flex; gap: 5px; align-items: center; color: var(--dim); }
  .notes { padding: 0 20px 8px 206px; max-width: 900px; }
  .rel { border-left: 2px solid var(--line); padding: 4px 10px; margin: 6px 0; }
  pre { white-space: pre-wrap; word-break: break-word; margin: 4px 0 0; color: var(--dim); }
  .tail { max-height: 180px; overflow: auto; background: var(--panel); padding: 6px 8px; border: 1px solid var(--q); }
  .spin { display: inline-block; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; padding: 6px 16px 10px; gap: 4px 0; } .sh, .sub { padding-left: 16px; padding-right: 16px; } .grid .k { margin-top: 6px; } .notes { padding-left: 16px; } }
</style>
