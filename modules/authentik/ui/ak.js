// Small helpers shared by the authentik module's components.
import { act, forget } from '$lab/sdk.js';

export const U = '/api/v3/core/users/';
export const G = '/api/v3/core/groups/';
export const B = '/api/v3/policies/bindings/';

// A write through the SDK's act() (owner → runs; admin → asks the owner), then the module's cached lists are dropped
// so the refresh that follows shows the change.
export const write = (ctx, opts) => act(ctx, { ...opts, done: (r, c) => { forget('authentik:d:*'); return opts.done?.(r, c); } });

export const humans = (users) => users.filter((u) => u.type !== 'service_account' && u.type !== 'internal_service_account' && !u.username.startsWith('ak-outpost'));

// app → who may use it: no bindings = everyone (Authentik default policy_engine_mode any + no bindings = allow)
export function appAccess(app, bindings, groupsById) {
  const bs = bindings.filter((b) => b.target === app.pk);
  if (!bs.length) return { everyone: true, groups: [], users: [], other: 0, bindings: [] };
  return {
    everyone: false,
    groups: bs.filter((b) => b.group).map((b) => ({ binding: b.pk, name: groupsById[b.group]?.name || b.group_obj?.name || '?', pk: b.group })),
    users: bs.filter((b) => b.user).map((b) => ({ binding: b.pk, name: b.user_obj?.username || String(b.user), pk: b.user })),
    other: bs.filter((b) => b.policy).length,
    bindings: bs,
  };
}
