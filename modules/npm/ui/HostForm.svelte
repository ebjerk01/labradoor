<script>
  // create / edit a proxy host (safe fields only; raw nginx config + auth gate are owner-only and live in the {} editor)
  import { act } from '$lab/sdk.js';
  let { data, ctx, host = null, done } = $props();

  const covers = (c, d) => c.domains.some((x) => x === d || (x.startsWith('*.') && d.endsWith(x.slice(1)) && d.split('.').length === x.split('.').length));
  const init = () => host
    ? { domains: host.domains.join(' '), scheme: host.scheme, host: host.host, port: host.port, certId: host.certId,
      sslForced: host.sslForced, http2: host.http2, websockets: host.websockets, blockExploits: host.blockExploits,
      hsts: host.hsts, caching: host.caching, accessLists: [...host.accessLists] }
    : { domains: '', scheme: 'http', host: '', port: 8080, certId: 0, sslForced: true, http2: true, websockets: true,
      blockExploits: true, hsts: false, caching: false, accessLists: [] };
  let f = $state(init());
  let certTouched = $state(false);
  const names = $derived(f.domains.split(/[\s,]+/).map((x) => x.trim().toLowerCase()).filter(Boolean));
  $effect(() => {
    if (host || certTouched || !names.length) return;
    const c = data.certs.find((x) => names.every((n) => covers(x, n)));
    f.certId = c ? c.id : 0;
  });
  const OPTS = [['sslForced', 'force ssl'], ['http2', 'http/2'], ['websockets', 'websockets'], ['blockExploits', 'block exploits'], ['hsts', 'hsts'], ['caching', 'cache']];

  async function submit(e) {
    e.preventDefault();
    const body = { domains: names, scheme: f.scheme, host: f.host.trim(), port: Number(f.port), certId: Number(f.certId),
      accessLists: f.accessLists.map(Number) };
    for (const [k] of OPTS) body[k] = f[k];
    if (host) {
      for (const k of Object.keys(body)) if (JSON.stringify(body[k]) === JSON.stringify(k === 'domains' ? host.domains : host[k])) delete body[k];
      if (!Object.keys(body).length) return done();
    }
    const r = host ? await act(ctx, { method: 'PUT', path: `/api/hosts/${host.id}`, body, label: `edit #${host.id} ${host.domains[0]}` })
      : await act(ctx, { path: '/api/hosts', body, label: `create ${names[0]}` });
    if (r) done();
  }
</script>

<form class="hf" onsubmit={submit}>
  <input class="field mono w2" placeholder="app.example.com (space-separated)" bind:value={f.domains} required aria-label="Domain names" />
  <span class="mono dim">→</span>
  <select class="field mono sel" bind:value={f.scheme} aria-label="Scheme"><option>http</option><option>https</option></select>
  <input class="field mono w1" placeholder="forward host / ip" bind:value={f.host} required aria-label="Forward host" />
  <input class="field mono w0" type="number" min="1" max="65535" bind:value={f.port} required aria-label="Forward port" />
  <select class="field mono sel" bind:value={f.certId} onchange={() => (certTouched = true)} aria-label="Certificate">
    <option value={0}>no cert</option>
    {#each data.certs as c}<option value={c.id}>{c.name}</option>{/each}
  </select>
  <div class="opts">
    {#each OPTS as [k, l]}<label class="mono"><input type="checkbox" bind:checked={f[k]} /> {l}</label>{/each}
    {#each data.accessLists as a}<label class="mono"><input type="checkbox" value={a.id} bind:group={f.accessLists} /> acl {a.name}</label>{/each}
  </div>
  <button class="btn primary">{host ? 'save' : 'create host'}</button>
  {#if host}<button type="button" class="btn" onclick={done}>cancel</button>{/if}
  <span class="mono dim hint">{host ? '' : 'then: a DNS record for the name, a monitoring check, and — for admin UIs — the origin lock + an access gate (owner). '}cf-only / access / auth gate are not set here.</span>
</form>

<style>
  .hf { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 20px; border-bottom: 1px solid var(--line); align-items: center; }
  .hf .field { padding: 6px 10px; font-size: 12.5px; }
  .w2 { max-width: 320px; } .w1 { max-width: 150px; } .w0 { max-width: 90px; }
  .sel { width: auto; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; max-width: 260px; }
  .opts { display: flex; flex-wrap: wrap; gap: 4px 14px; width: 100%; font-size: 11.5px; color: var(--dim); }
  .opts label { display: flex; gap: 4px; align-items: center; }
  .hint { font-size: 11px; width: 100%; }
</style>
