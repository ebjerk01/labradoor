// Pure helpers for the stalwart module (no $lab imports, so node --test can load them).

export const secs = (iso) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? Math.floor(t / 1000) : null;
};

export const objId = (settings) => String(settings?.object || 'stalwart').trim() || 'stalwart';

// recipients' worst state → lab status
export const QSTATUS = { PermanentFailure: 'bad', TemporaryFailure: 'warn', Scheduled: 'ok', Completed: 'off' };

export function blockedSince(d, since) {
  return (d?.blocked || []).filter((b) => (secs(b.created) || 0) >= since).length;
}

// one list feeds alerts() and the object's status
export function problems(d, settings = {}, now = Date.now() / 1000) {
  if (!d) return [];
  const out = [];
  const obj = objId(settings);
  const qn = d.counts?.queue || 0;
  const qa = Number(settings.queue_alert ?? 10) || 0;
  if (qa && qn >= qa) {
    out.push({ key: 'stalwart:queue', status: 'warn', title: `Stalwart: ${qn} messages queued`, detail: `${d.counts.failing || 0} failing delivery`, object: obj });
  }
  const sh = Number(settings.stuck_hours ?? 6) || 0;
  if (sh) {
    const old = (d.queue || []).filter((m) => (secs(m.created) || now) < now - sh * 3600);
    if (old.length) {
      const first = old[old.length - 1];
      out.push({ key: 'stalwart:stuck', status: 'warn', title: `Stalwart: ${old.length} message${old.length > 1 ? 's' : ''} stuck over ${sh} h`,
        detail: `oldest from ${first.from} to ${(first.recipients || []).map((r) => r.to).slice(0, 3).join(', ')}`, since: secs(first.created), object: obj });
    }
  }
  const perm = (d.queue || []).filter((m) => m.status === 'PermanentFailure');
  if (perm.length) {
    out.push({ key: 'stalwart:bounced', status: 'warn', title: `Stalwart: ${perm.length} queued message${perm.length > 1 ? 's' : ''} failed permanently`,
      detail: perm.slice(0, 3).map((m) => (m.recipients || []).map((r) => r.to).join(', ')).join('; '), object: obj });
  }
  const ba = Number(settings.blocked_day_alert ?? 20) || 0;
  const day = blockedSince(d, now - 86400);
  if (ba && day >= ba) {
    out.push({ key: 'stalwart:blocked', status: 'warn', title: `Stalwart: ${day} IPs blocked in 24 h`, detail: 'auto-ban is busy: scanners or password guessing', object: obj });
  }
  for (const c of d.certificates || []) {
    const left = ((secs(c.notAfter) || now + 1e9) - now) / 86400;
    if (left < 14) {
      out.push({ key: `stalwart:cert:${c.id}`, status: left < 3 ? 'bad' : 'warn', title: `Stalwart: certificate ${(c.names || [])[0] || c.id} expires in ${Math.max(0, Math.floor(left))} d`,
        detail: 'ACME renewal should have run by now', object: obj });
    }
  }
  return out;
}

export function statusOf(d, settings) {
  const p = problems(d, settings);
  return p.some((x) => x.status === 'bad') ? 'bad' : p.length ? 'warn' : 'ok';
}

// DMARC/TLS row → status: anything failing is a warning
export const reportStatus = (r) => ((r.failed || 0) > 0 ? 'warn' : 'ok');

export const KINDS = [
  { id: 'dmarc', label: 'DMARC in' }, { id: 'tls', label: 'TLS-RPT in' }, { id: 'arf', label: 'ARF (abuse)' },
  { id: 'dmarc-out', label: 'DMARC out' }, { id: 'tls-out', label: 'TLS-RPT out' },
];

export const reportCount = (d, kind) => ({ dmarc: d.reports.dmarc, tls: d.reports.tls, arf: d.reports.arf,
  'dmarc-out': d.reports.dmarcOut, 'tls-out': d.reports.tlsOut })[kind] ?? 0;

// Graylog search for the server's auth failures (Stalwart logs plain messages to journald → rsyslog → Graylog)
export const LOGQ = {
  auth: '("Authentication failed" OR "Too many authentication attempts")',
  blocked: '"Blocked IP address"',
};
export const logQuery = (base, which) => `${(base || 'source:stalwart').trim()} AND message:${LOGQ[which]}`;
