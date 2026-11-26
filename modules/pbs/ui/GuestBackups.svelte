<script>
  // A guest's backups in PBS (group ct/<vmid> or vm/<vmid>): age, size, verify state, protection, encryption.
  // Actions: verify, protect/unprotect, delete (confirm). Restore is deliberately NOT automated (a restore onto the
  // live VMID replaces the guest; to a new one it clashes on MAC/IP when started): copyable commands instead.
  import Section from '$lab/Section.svelte';
  import Lines from '$lab/Lines.svelte';
  import ActionButton from '$lab/ActionButton.svelte';
  import { ago, bytes, lazy, watching } from '$lab/sdk.js';
  import { dsOf, STALE_S, guestRef, snapQuery, volid, watchUpid } from './pbs.svelte.js';
  let { object, data, ctx } = $props();

  const DS = $derived(dsOf(data?.store || ctx.settings?.store || 'homelab'));
  const running = $derived(watching.list.filter((w) => w.module === ctx.id));
  const storage = $derived(ctx.settings?.pve_storage || 'pbs');
  const target = $derived(ctx.settings?.restore_storage || '<storage>');
  const ref = $derived(data && object.type === 'machine' ? guestRef(object, ctx) : null);
  const group = $derived(ref ? data.groups.find((g) => g['backup-type'] === ref.type && g['backup-id'] === ref.id) : null);
  const snaps = lazy(() => ctx, () => (group ? `${DS}/snapshots` : null),
    { query: () => (ref ? { 'backup-type': ref.type, 'backup-id': ref.id } : undefined), pick: (r) => r.data });
  const list = $derived((snaps.data || []).slice().sort((a, b) => b['backup-time'] - a['backup-time']));
  const stale = $derived(group ? data.at - group['last-backup'] > STALE_S : false);
  let open = $state(null);
  let all = $state(false);
  const enc = (s) => (s.files || []).some((f) => f['crypt-mode'] === 'encrypt');
  const vst = (s) => s.verification?.state || 'none';
  const cmd = (s) => { const v = volid(s, storage); return s['backup-type'] === 'ct'
    ? [`pct restore <NEWID> ${v} --storage ${target} --unique 1`, `# same id: pct stop ${s['backup-id']} && pct restore ${s['backup-id']} ${v} --force 1`]
    : [`qmrestore ${v} <NEWID> --storage ${target} --unique 1`, `# same id: qm stop ${s['backup-id']} && qmrestore ${v} ${s['backup-id']} --force 1`]; };
  function copy(t) {
    navigator.clipboard?.writeText(t).then(() => ctx.notify('copied'), () => ctx.notify('copy failed', 'bad'));
  }
</script>

{#if ref}
  <Section title="backups · pbs" src="pbs · {ref.type}/{ref.id}">
    {#if !group}
      <span class="mono warn small">▲ no backups of {ref.type}/{ref.id} in {data.store}</span>
    {:else}
      <span class="mono dim small"><span class={stale ? 'warn' : 'ok'}>{stale ? '▲' : '●'}</span> last {ago(group['last-backup'], data.at)} ago · {group['backup-count']} kept{group.comment ? ` · ${group.comment}` : ''} · owner {group.owner}</span>
      {#each running as t (t.id)}<span class="mono sig small spin">{t.label} </span>{/each}
      {#if snaps.error}<span class="mono bad small">{snaps.error}</span>
      {:else if !snaps.data}<span class="mono dim small spin">snapshots </span>
      {:else}
        <div class="list">
          {#each (all ? list : list.slice(0, 8)) as s (s['backup-time'])}
            {@const k = s['backup-time']}
            <div class="r">
              <button class="lnk mono nm" onclick={() => (open = open === k ? null : k)}>
                <span class={vst(s) === 'ok' ? 'ok' : vst(s) === 'failed' ? 'bad' : 'faint'} title="verify: {vst(s)}">{vst(s) === 'ok' ? '●' : vst(s) === 'failed' ? '■' : '○'}</span>
                {new Date(k * 1000).toLocaleString('nb-NO', { dateStyle: 'short', timeStyle: 'short' })}
                <span class="dim">· {bytes(s.size, 0)}{enc(s) ? '' : ' · plain'}{s.protected ? ' · protected' : ''}</span>
              </button>
              <span class="dim mono a">{ago(k, data.at)}</span>
            </div>
            {#if open === k}
              <div class="more">
                <ActionButton {ctx} small path="{DS}/verify" body={snapQuery(s)} label="verify backup {s['backup-type']}/{s['backup-id']}" done={watchUpid(`verify ${s['backup-type']}/${s['backup-id']}`)}>verify</ActionButton>
                <ActionButton {ctx} small method="PUT" path="{DS}/protected" body={{ ...snapQuery(s), protected: !s.protected }}
                  label="{s.protected ? 'unprotect' : 'protect'} backup {s['backup-type']}/{s['backup-id']}" done={() => { snaps.reload(); }}>{s.protected ? 'unprotect' : 'protect'}</ActionButton>
                {#if !s.protected}
                  <ActionButton {ctx} small method="DELETE" path="{DS}/snapshots" query={snapQuery(s)} label="delete backup {s['backup-type']}/{s['backup-id']} {new Date(k * 1000).toISOString().slice(0, 16)}" confirm done={() => { snaps.reload(); }}>delete</ActionButton>
                {/if}
                <button class="btn sm" onclick={() => copy(cmd(s)[0])}>copy restore cmd</button>
                <Lines items={[...cmd(s).map((t) => ({ p: '$', t })), ...(s.comment ? [{ p: '#', t: s.comment }] : []), { p: '#', t: 'files: pve UI → storage pbs → backups → file restore' }]} />
              </div>
            {/if}
          {/each}
          {#if list.length > 8}<button class="lnk mono dim small" onclick={() => (all = !all)}>{all ? 'fewer' : `all ${list.length}`}</button>{/if}
        </div>
      {/if}
    {/if}
  </Section>
{/if}

<style>
  .small { font-size: 11.5px; }
  .list { display: flex; flex-direction: column; max-height: 420px; overflow-y: auto; }
  .r { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 3px 0; border-bottom: 1px solid var(--q); }
  .nm { font-size: 11.5px; display: flex; gap: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .a { font-size: 11px; }
  .more { display: flex; flex-wrap: wrap; gap: 6px; padding: 6px 0 8px 18px; border-bottom: 1px solid var(--q); }
  .more :global(.lines) { flex-basis: 100%; }
  .sm { padding: 2px 7px; font-size: 11px; }
</style>
