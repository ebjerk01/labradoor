// stalwart — the Stalwart mail server (0.16+) through the lab connector `stalwart` (connectors/stalwart, port 8121).
// Stalwart's management is JMAP on one URL, so the connector turns fixed REST-ish routes into fixed JMAP calls and
// never returns a credential. The facet sits on the mail server's machine object (setting `object`).
import Facet from './Facet.svelte';
import Tile from './Tile.svelte';
import MailView from './MailView.svelte';
import { problems, statusOf, objId, blockedSince, secs } from './sw.js';
import { clip } from '$lab/sdk.js';

export default {
  id: 'stalwart',

  async load(ctx) {
    return ctx.api.get('/api/overview');
  },

  objects(d, ctx) {
    const c = d.counts;
    return [{ id: objId(ctx?.settings), type: 'service', name: objId(ctx?.settings), kind: 'mail server', status: statusOf(d, ctx?.settings),
      meta: `stalwart · ${c.queue} queued · ${c.accounts} accounts · ${c.domains} domain${c.domains === 1 ? '' : 's'} · ${c.blocked} blocked IPs` }];
  },

  alerts(d, ctx) {
    return problems(d, ctx?.settings || {});
  },

  kpis(d, ctx) {
    const c = d.counts;
    return [{ label: 'mail queue', value: String(c.queue), sub: `${c.failing} failing · ${c.blocked} blocked IPs`,
      status: c.failing ? 'warn' : null, open: objId(ctx?.settings) }];
  },

  status(d, ref) {
    return statusOf(d, {});
  },

  ticker(d, ctx) {
    const day = Date.now() / 1000 - 86400;
    const obj = objId(ctx?.settings);
    const out = [];
    for (const m of d.queue.filter((x) => x.status !== 'Scheduled').slice(0, 2)) {
      out.push({ g: '▲', c: 'var(--warn)', s: 'stalwart', m: `${m.status === 'PermanentFailure' ? 'bounced' : 'retrying'}: ${clip(m.recipients.map((r) => r.to).join(', '), 60)}`, object: obj });
    }
    const n = blockedSince(d, day);
    if (n) out.push({ g: '■', c: 'var(--dim)', s: 'stalwart', m: `${n} IP${n > 1 ? 's' : ''} auto-blocked in 24 h`, object: obj });
    const newest = d.blocked[0];
    if (newest && (secs(newest.created) || 0) > day) out.push({ g: '·', c: 'var(--dim)', s: 'stalwart', m: `blocked ${newest.address} (${newest.reason})`, object: obj });
    return out;
  },

  search(d, ctx) {
    const obj = objId(ctx?.settings);
    return [
      ...d.accounts.map((a) => ({ label: a.email, sub: `mail account · ${a.description || a.role}${a.disabled ? ' · disabled' : ''}`, object: obj })),
      ...d.domains.map((x) => ({ label: x.name, sub: `mail domain · ${x.accounts} accounts`, object: obj })),
      ...d.blocked.slice(0, 200).map((b) => ({ label: b.address, sub: `blocked by stalwart · ${b.reason}`, object: obj })),
    ];
  },

  facets: { service: Facet },
  views: [{ id: 'stalwart', label: 'Mail server', icon: 'mail', component: MailView, min: 'admin' }],
  tiles: [{ id: 'mail', label: 'mail server', w: 3, h: 1, component: Tile, min: 'admin' }],
};
