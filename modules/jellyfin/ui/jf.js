// Jellyfin helpers: compact sessions/items/users, user ids, policy writes (owner-only routes → admins ask).
import { act, forget } from '$lab/sdk.js';

export const UID = (name) => `jellyfin-user:${name}`;

// Authentik username ⇄ Jellyfin name. Equal names link by themselves; the setting user_links adds "authentik=jellyfin" pairs.
export function links(settings) {
  const a2j = {}, j2a = {};
  for (const p of settings?.user_links || []) {
    const [a, j] = String(p).split('=').map((s) => s.trim().toLowerCase());
    if (a && j) { a2j[a] = j; j2a[j] = a; }
  }
  return { toJellyfin: (a) => a2j[a.toLowerCase()] || a.toLowerCase(), toAuthentik: (j) => j2a[j.toLowerCase()] || j.toLowerCase() };
}

export const TICK = 1e7;  // Jellyfin times are 100 ns ticks
export function session(s) {
  const n = s.NowPlayingItem, p = s.PlayState || {}, tr = s.TranscodingInfo;
  const cmds = s.Capabilities?.SupportedCommands || [];
  return {
    id: s.Id, user: s.UserName || '—', userId: s.UserId, client: s.Client, device: s.DeviceName, deviceId: s.DeviceId, version: s.ApplicationVersion,
    control: !!s.SupportsRemoteControl, message: cmds.includes('DisplayMessage'), itemId: n?.Id || null,
    last: s.LastActivityDate ? Date.parse(s.LastActivityDate) / 1000 : null, remote: s.RemoteEndPoint,
    playing: n ? {
      name: n.Name, type: n.Type, series: n.SeriesName, s: n.ParentIndexNumber, e: n.IndexNumber, year: n.ProductionYear,
      pct: n.RunTimeTicks ? (100 * (p.PositionTicks || 0)) / n.RunTimeTicks : null, runtime: n.RunTimeTicks ? n.RunTimeTicks / TICK : null,
    } : null,
    paused: !!p.IsPaused, method: p.PlayMethod || null,
    transcode: tr ? { video: tr.IsVideoDirect ? 'direct' : tr.VideoCodec, audio: tr.IsAudioDirect ? 'direct' : tr.AudioCodec,
      hw: tr.HardwareAccelerationType || null, reasons: tr.TranscodeReasons || [], fps: tr.Framerate, bitrate: tr.Bitrate } : null,
  };
}

export const label = (it) => (it.Type === 'Episode' ? `${it.SeriesName} S${String(it.ParentIndexNumber ?? 0).padStart(2, '0')}E${String(it.IndexNumber ?? 0).padStart(2, '0')}` : `${it.Name}${it.ProductionYear ? ` (${it.ProductionYear})` : ''}`);
export const playLabel = (p) => (p.type === 'Episode' ? `${p.series} S${String(p.s ?? 0).padStart(2, '0')}E${String(p.e ?? 0).padStart(2, '0')} ${p.name}` : `${p.name}${p.year ? ` (${p.year})` : ''}`);

export function user(u, libs) {
  const P = u.Policy || {};
  const names = Object.fromEntries((libs || []).map((l) => [l.ItemId, l.Name]));
  return {
    id: u.Id, name: u.Name, admin: !!P.IsAdministrator, disabled: !!P.IsDisabled, hidden: !!P.IsHidden,
    hasPassword: !!u.HasPassword, lastLogin: u.LastLoginDate ? Date.parse(u.LastLoginDate) / 1000 : null,
    lastActivity: u.LastActivityDate ? Date.parse(u.LastActivityDate) / 1000 : null,
    allFolders: !!P.EnableAllFolders, folders: (P.EnabledFolders || []).map((f) => names[f] || names[f.replace(/-/g, '')] || f),
    folderIds: P.EnabledFolders || [], maxSessions: P.MaxActiveSessions || 0, remote: P.EnableRemoteAccess !== false,
    lockout: P.LoginAttemptsBeforeLockout, failed: P.InvalidLoginAttemptCount || 0, policy: P,
    rating: P.MaxParentalRating ?? null, bitrate: P.RemoteClientBitrateLimit || 0, deletion: !!P.EnableContentDeletion,
  };
}

export const access = (u) => (u.allFolders ? 'all libraries' : u.folders.length ? u.folders.join(', ') : 'no libraries');

// Jellyfin wants the WHOLE policy on every change: start from the current one.
export function setPolicy(ctx, u, changes, label, confirmText) {
  forget(`${ctx.id}:users`);
  return act(ctx, { path: `/Users/${u.id}/Policy`, body: { ...u.policy, ...changes }, label: `jellyfin ${u.name}: ${label}`, confirm: confirmText });
}
export function setPassword(ctx, u, pw) {
  return act(ctx, { path: `/Users/Password?userId=${u.id}`, body: { NewPw: pw, ResetPassword: false }, label: `jellyfin ${u.name}: set password` });
}
export function removeUser(ctx, u) {
  forget(`${ctx.id}:users`);
  return act(ctx, { method: 'DELETE', path: `/Users/${u.id}`, label: `jellyfin: delete user ${u.name}`, confirm: `Delete the Jellyfin user "${u.name}"? Their watch history and settings in Jellyfin go with it.` });
}

// "8 Mbit/s" from bits per second (Jellyfin's remote bitrate limit); 0 = no limit
export const mbit = (b) => (b ? `${+(b / 1e6).toFixed(1)} Mbit/s` : 'no limit');
export const runtime = (ticks) => {
  if (!ticks) return '–';
  const m = Math.round(ticks / TICK / 60);
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m}m`;
};
