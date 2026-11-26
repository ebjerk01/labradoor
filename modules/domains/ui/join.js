// One row per hostname: Cloudflare DNS (+proxied/Access) → NPMplus host → backend target → drift checks → cert → status.
// Pure function over the modules' data (ctx.peer(<id>)), so it runs in the browser and in tests alike. Read-only:
// "dead" only FLAGS candidates for the planned NPMplus cleanup — nothing here deletes anything.
import { days, certLevel, ipMap, hostPort } from './net.js';

const ADDR = new Set(['A', 'AAAA', 'CNAME']);
const RANK = { unknown: 0, off: 1, ok: 2, warn: 3, bad: 4 };
const worst = (...s) => s.filter(Boolean).reduce((a, b) => (RANK[b] > RANK[a] ? b : a), 'unknown');

// does a wildcard record cover `name`? (*.P covers x.P and y.x.P only while no record exists for x.P — RFC 4592)
function wildcardFor(name, byName) {
  const labels = name.split('.');
  for (let i = 1; i < labels.length - 1; i++) {
    const parent = labels.slice(i).join('.');
    const wc = byName.get(`*.${parent}`);
    if (wc) {
      const between = labels.slice(1, i).map((_, j) => labels.slice(j + 1).join('.'));
      if (!between.some((n) => byName.has(n))) return wc;
    }
  }
  return null;
}

export function join({ npm, cloudflare: cf, drift, unifi }) {
  const recs = (cf?.records || []);
  const byName = new Map();
  for (const r of recs) if (ADDR.has(r.type)) byName.set(r.name, [...(byName.get(r.name) || []), r]);
  const zones = new Set((cf?.zones || []).map((z) => z.name));
  const hosts = npm?.hosts || [];
  const certs = Object.fromEntries((npm?.certs || []).map((c) => [c.id, c]));
  const checks = drift?.overview?.checks || [];
  const ips = ipMap(unifi, drift);
  const apex = Object.fromEntries([...zones].map((z) => [z, (byName.get(z) || []).find((r) => r.type === 'A')?.content]));

  const names = new Set();
  for (const r of recs) if (ADDR.has(r.type) && !r.name.startsWith('*.')) names.add(r.name);
  for (const h of hosts) for (const d of h.domains) if (!d.startsWith('*.')) names.add(d);

  const rows = [];
  for (const name of names) {
    const own = byName.get(name) || [];
    const wc = own.length ? null : wildcardFor(name, byName);
    const rec = own[0] || wc?.[0] || null;
    const zone = [...zones].find((z) => name === z || name.endsWith(`.${z}`)) || null;
    const dns = rec ? { kind: own.length ? 'record' : 'wildcard', type: rec.type, content: rec.content, proxied: !!rec.proxied,
      id: own.length ? rec.id : null, zoneId: rec.zoneId, comment: rec.comment || '' } : { kind: zone ? 'none' : 'external' };
    const access = (cf?.apps || []).filter((a) => (a.domains || [a.domain]).some((d) => d && d.split('/')[0] === name))
      .map((a) => ({ name: a.name, path: (a.domain || '').includes('/') ? a.domain.slice(a.domain.indexOf('/')) : '',
        policies: (a.policies || []).map((p) => `${p.decision === 'bypass' ? '↷ ' : ''}${p.name}`) }));

    const h = hosts.find((x) => x.domains.includes(name)) || null;
    const cert = h?.certId ? certs[h.certId] : null;
    const certDays = cert ? days(cert.expires) : null;
    const machine = h ? ips[h.host] || null : null;

    const pub = [], back = [];
    for (const c of checks) {
      const t = hostPort(c.target);
      if ((t && t.host === name) || (c.name || '').startsWith(`${name} `)) pub.push(c);
      else if (h && t && t.port != null && t.host === String(h.host).toLowerCase() && (t.port === h.port || (h.extra || []).some((x) => x.port === t.port))) back.push(c);
    }
    const passing = [...pub, ...back].filter((c) => c.ok).length;

    // references from elsewhere: DNS records pointing at the name, redirections to it, other hosts' nginx config
    const refs = [];
    for (const r of recs) if (r.name !== name && (r.content === name || (r.type !== 'TXT' && (r.content || '').split(/\s+/).includes(name)))) refs.push(`${r.type} ${r.name}`);
    for (const x of npm?.redirections || []) if (x.target === name) refs.push(`redirect #${x.id}`);
    const word = new RegExp(`(^|[^a-z0-9.-])${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^a-z0-9-])`, 'i');
    for (const x of hosts) if (x !== h && word.test((x.advanced || '').replace(/#.*$/gm, ''))) refs.push(`npm #${x.id} config`);

    const backend = h?.backend || null;
    const backendUp = backend?.state === 'up' || (h?.extraBackend || []).some((b) => b?.state === 'up');
    const reasons = [];
    let status = 'ok';
    if (h) {
      if (!h.enabled) { status = 'off'; reasons.push('npm host disabled'); }
      if (h.enabled && h.online === false) { status = worst(status, 'bad'); reasons.push(`nginx: ${h.err || 'config error'}`); }
      if (h.enabled && backend && backend.state !== 'up' && !back.some((c) => c.ok)) {
        status = worst(status, backend.state === 'refused' ? 'bad' : 'warn'); reasons.push(`backend ${backend.state} from lab`);
      }
      const cl = certLevel(certDays);
      if (cl && cl !== 'ok') { status = worst(status, cl); reasons.push(`cert ${certDays.toFixed(1)}d`); }
      if (h.originLock && dns.kind !== 'none' && !dns.proxied) { status = worst(status, 'warn'); reasons.push('origin lock but DNS not proxied'); }
    } else if (dns.kind === 'record' && (dns.content === zone || dns.content === apex[zone] || dns.content === `mail.${zone}`)) {
      status = 'warn'; reasons.push('dns points home but no npm host');
    }
    if (pub.length && !pub.some((c) => c.ok)) { status = worst(status, 'bad'); reasons.push('public check failing'); }
    else if (pub.some((c) => !c.ok)) { status = worst(status, 'warn'); reasons.push('a check is failing'); }
    if (dns.kind === 'none' && h) reasons.push('no DNS record (not covered by a wildcard)');

    const dead = !!(h && backend && !backendUp && !passing && !refs.length);
    const dnsOnly = !h && dns.kind === 'record' && !passing && !refs.length && reasons.includes('dns points home but no npm host');
    if (dead) reasons.unshift('DEAD? backend silent, no passing check, unreferenced');
    rows.push({ name, zone, dns, access, npm: h, cert: cert ? { id: cert.id, days: certDays, name: cert.name } : null,
      machine, checks: { pub, back, passing, total: pub.length + back.length }, refs, status, reasons, dead, dnsOnly });
  }
  return rows.sort((a, b) => a.name.split('.').reverse().join('.').localeCompare(b.name.split('.').reverse().join('.')));
}
