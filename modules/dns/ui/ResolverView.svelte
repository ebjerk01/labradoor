<script>
  // ~/dns — Technitium: 24 h stats, top lists, zones + records. Add/flush: admin; delete: owner.
  import Section from '$lab/Section.svelte';
  import Stats from '$lab/Stats.svelte';
  import Lines from '$lab/Lines.svelte';
  import Glyph from '$lab/Glyph.svelte';
  import Icon from '$lab/Icon.svelte';
  import { act } from '$lab/sdk.js';
  import DomainLists from './DomainLists.svelte';
  import { unwrap, value, recordQuery, EDITABLE } from './tdns.js';
  let { data, ctx } = $props();

  let zone = $state(null);
  let records = $state([]);
  let loading = $state(false);
  let nr = $state({ name: '', type: 'A', value: '', ttl: 3600 });

  async function openZone(z) {
    zone = z.name; loading = true; records = [];
    try {
      records = unwrap(await ctx.api.get('/api/zones/records/get', { domain: z.name, zone: z.name, listZone: 'true' })).records || [];
    } catch (e) { ctx.notify(e.message, 'bad'); }
    loading = false;
  }
  // Technitium answers HTTP 200 even on errors ({status: error}): check: unwrap fails the action before any ✓.
  // An owner-only route ('ask' for an admin) becomes an approval request inside act().
  const write = (path, label, reload = true, confirm = undefined) => act(ctx, { path, label, confirm, check: unwrap,
    done: async () => { if (reload && zone) await openZone({ name: zone }); } });
  function add(e) {
    e.preventDefault();
    // "", "@" or the zone name itself = apex; "www" or "www.<zone>" = www.<zone>
    const rel = nr.name.trim().replace(/\.$/, '').replace(new RegExp(`(^|\\.)${zone.replace(/\./g, '\\.')}$`, 'i'), '');
    const name = rel && rel !== '@' ? `${rel}.${zone}` : zone;
    write(`/api/zones/records/add?${recordQuery(zone, name, nr.type, nr.value.trim(), { ttl: String(nr.ttl) })}`, `add ${nr.type} ${name}`);
  }
  function del(r) {
    write(`/api/zones/records/delete?${recordQuery(zone, r.name, r.type, value(r))}`, `delete ${r.type} ${r.name}`, true,
      `Delete ${r.type} ${r.name} ${value(r)}?`);
  }
  const s = $derived(data?.stats || {});
  const top = (xs) => xs.slice(0, 8).map((x) => ({ p: String(x.hits).padStart(5), c: 'var(--sig)', t: `${x.name}${x.domain ? ' · ' + x.domain : ''}` }));
</script>

{#if !data}<p class="mono dim pad spin">loading technitium</p>{:else}
<div class="rv fade">
  <Section title="last 24h" src="technitium">
    <Stats cols={6} items={[
      { n: 'queries', v: s.totalQueries ?? '–' }, { n: 'blocked', v: s.totalBlocked ?? '–', c: 'var(--sig)' },
      { n: 'nxdomain', v: s.totalNxDomain ?? '–' }, { n: 'servfail', v: s.totalServerFailure ?? '–', s: s.totalServerFailure ? 'warn' : null },
      { n: 'cached', v: s.totalCached ?? '–' }, { n: 'clients', v: s.totalClients ?? '–' },
    ]} />
    <Stats cols={6} items={[
      { n: 'zones', v: s.zones ?? data.zones.length }, { n: 'block lists', v: s.blockListZones ?? '–' }, { n: 'blocked zones', v: s.blockedZones ?? '–' },
      { n: 'allowed', v: s.allowedZones ?? '–' }, { n: 'cache entries', v: s.cachedEntries ?? '–' }, { n: 'recursive', v: s.totalRecursive ?? '–' },
    ]} />
    <div class="row">
      {#if ctx.can('POST', '/api/cache/flush') !== 'no'}<button class="btn" onclick={() => write('/api/cache/flush', 'flush DNS cache', false, 'Flush the whole DNS cache?')}><Icon name="restart" size={12} />flush cache</button>{/if}
      <span class="mono dim note">LAN clients resolve via your router (DHCP hands out 192.0.2.1), so these numbers are only what asks Technitium directly.</span>
    </div>
  </Section>
  <div class="tops">
    <Section title="top domains" src="technitium"><Lines items={top(data.topDomains)} empty="none" /></Section>
    <Section title="top blocked" src="technitium"><Lines items={top(data.topBlocked)} empty="none" /></Section>
    <Section title="top clients" src="technitium"><Lines items={top(data.topClients)} empty="none" /></Section>
  </div>
  <DomainLists {ctx} />
  <Section title="zones · {data.zones.length}" src="technitium">
    <div class="scroll-x"><table>
      <thead><tr class="cap"><th></th><th>zone</th><th>type</th><th>dnssec</th><th>serial</th><th></th></tr></thead>
      <tbody>
        {#each data.zones.filter((z) => !z.internal) as z (z.name)}
          <tr class="row" class:on={zone === z.name}>
            <td><Glyph status={z.disabled ? 'off' : z.syncFailed || z.isExpired ? 'bad' : 'ok'} /></td>
            <td><button class="lnk mono" onclick={() => openZone(z)}>{z.name || '.'}</button></td>
            <td class="mono dim">{z.type}</td><td class="mono dim">{z.dnssecStatus}</td><td class="mono dim">{z.soaSerial ?? ''}</td><td></td>
          </tr>
        {/each}
      </tbody>
    </table></div>
  </Section>
  {#if zone}
    <Section title="{zone} · records" src="technitium">
      {#if ctx.can('POST', '/api/zones/records/add') !== 'no'}
        <form class="new" onsubmit={add}>
          <input class="field mono" placeholder="name (blank = apex)" bind:value={nr.name} aria-label="Name" />
          <select class="field mono sel" bind:value={nr.type} aria-label="Type">{#each EDITABLE as t}<option>{t}</option>{/each}</select>
          <input class="field mono" placeholder={nr.type === 'CNAME' ? 'target.name' : nr.type === 'TXT' ? 'text' : 'address'} bind:value={nr.value} required aria-label="Value" />
          <input class="field mono ttl" type="number" min="1" bind:value={nr.ttl} aria-label="TTL" />
          <button class="btn primary">add</button>
        </form>
      {/if}
      {#if loading}<p class="mono dim spin">loading records</p>{:else}
        <Lines items={records.filter((r) => r.type !== 'RRSIG' && r.type !== 'NSEC' && r.type !== 'NSEC3').map((r) => ({ p: r.disabled ? '○' : '●', s: r.disabled ? 'off' : 'ok', t: `${r.name} ${r.type} ${value(r)} · ttl ${r.ttl}` }))} empty="no records" />
        {#if ctx.can('POST', '/api/zones/records/delete') !== 'no'}
          <div class="dels">
            {#each records.filter((r) => EDITABLE.includes(r.type)) as r}
              <button class="btn" onclick={() => del(r)} title={ctx.can('POST', '/api/zones/records/delete') === 'ask' ? 'owner only' : 'delete'}>
                <Icon name={ctx.can('POST', '/api/zones/records/delete') === 'ask' ? 'lock' : 'close'} size={11} />{r.name.replace(`.${zone}`, '') || '@'} {r.type}</button>
            {/each}
          </div>
        {/if}
      {/if}
    </Section>
  {/if}
</div>
{/if}

<style>
  .pad { padding: 16px 20px; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .note { font-size: 11px; }
  .tops { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-weight: 400; padding: 6px 10px; border-bottom: 1px solid var(--line); }
  td { padding: 4px 10px; border-bottom: 1px solid var(--q); }
  td.mono, .mono.dim { font-size: 11.5px; }
  tr.on { background: var(--raise); }
  .new { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .new .field { max-width: 200px; padding: 5px 8px; font-size: 12px; }
  .ttl { max-width: 90px !important; }
  .sel { width: auto; padding: 5px 8px; font-size: 12px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; }
  .dels { display: flex; flex-wrap: wrap; gap: 4px; }
  .dels .btn { padding: 2px 6px; font-size: 11px; }
</style>
