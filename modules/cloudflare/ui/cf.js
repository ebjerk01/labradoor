// Cloudflare data loading + checks shared by the module's hooks and components. Everything is discovered from the API.
//   zones + Access apps/policies change rarely: cached 10 min (a policy edit calls refreshSlow());
//   DNS records every 30 s (a write in the Cloudflare view calls refreshRecords() so it shows at once).
import { cached, forget } from '$lab/sdk.js';

export const refreshSlow = () => forget('cloudflare:slow');
export const refreshRecords = () => forget('cloudflare:records');

// follow Cloudflare's pagination (result_info.total_pages), at most `max` pages
async function pages(ctx, path, per, max = 20) {
  const out = [];
  for (let page = 1; page <= max; page++) {
    const r = await ctx.api.get(path, { per_page: per, page });
    out.push(...(r.result || []));
    if (!r.result_info || page >= (r.result_info.total_pages || 1)) break;
  }
  return out;
}

export function loadSlow(ctx) {
  return cached('cloudflare:slow', 600000, async () => {
    const zones = (await pages(ctx, '/zones', 50)).map((x) => ({ id: x.id, name: x.name, status: x.status, plan: x.plan?.name, paused: x.paused,
      ns: x.name_servers, account: x.account?.id }));
    const accountId = zones[0]?.account || null;
    let apps = [], policies = [];
    if (accountId) {
      const [a, p] = await Promise.allSettled([pages(ctx, `/accounts/${accountId}/access/apps`, 200), pages(ctx, `/accounts/${accountId}/access/policies`, 200)]);
      if (a.status === 'fulfilled') apps = a.value.map((x) => ({ id: x.id, name: x.name, domain: x.domain, type: x.type,
        domains: x.self_hosted_domains || [x.domain], session: x.session_duration,
        policies: (x.policies || []).map((y) => ({ id: y.id, name: y.name, decision: y.decision, reusable: y.reusable })) }));
      if (p.status === 'fulfilled') policies = p.value.map((x) => ({ id: x.id, name: x.name, decision: x.decision,
        include: x.include, exclude: x.exclude, require: x.require, session: x.session_duration, apps: x.app_count }));
    }
    return { zones, apps, policies, accountId };
  });
}

export function loadRecords(ctx, zones) {
  return cached('cloudflare:records', 30000, async () => {
    const per = await Promise.all(zones.map(async (z) => (await pages(ctx, `/zones/${z.id}/dns_records`, 1000))
      .map((x) => ({ id: x.id, zoneId: z.id, zone: z.name, name: x.name, type: x.type, content: x.content,
        proxied: !!x.proxied, proxiable: x.proxiable, ttl: x.ttl, comment: x.comment || '', modified: Date.parse(x.modified_on) / 1000,
        priority: x.priority }))));
    return per.flat();
  });
}

// explicit A records that differ from their zone's apex = probably not kept current by the dynamic-DNS updater → going stale
export function staleA(records) {
  const apex = {};
  for (const r of records) if (r.type === 'A' && r.name === r.zone) apex[r.zone] = r.content;
  return records.filter((r) => r.type === 'A' && r.name !== r.zone && apex[r.zone] && r.content !== apex[r.zone]
    && !/^(10|192\.168|172\.(1[6-9]|2\d|3[01]))\./.test(r.content));
}

// Cloudflare answers {success: false, errors: [...]} — with a non-2xx status normally, but check in-band too
export function check(r) {
  if (r?.success === false) throw new Error(r.errors?.[0]?.message || 'Cloudflare refused the request');
}
