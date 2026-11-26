// guacamole: who gets which console button (the gateway + connector enforce it; this keeps the UI honest about it).
import assert from 'node:assert/strict';
import test from 'node:test';
import { mode, isProtected, openPath, grantPath, grantFor, connsFor } from '../modules/guacamole/ui/guac.js';

const c = { id: '19', name: 'workstation (CT 112)', protocol: 'ssh', terminal: true, label: 'workstation', vmid: 112 };
const obj = { id: 'workstation' };
// a ctx whose can() answers like the shell would from the manifest routes (+ _protect for admins)
function ctx(role, { protect = [], username = 'admin' } = {}) {
  const prot = (p) => isProtected(c, obj, { settings: { _protect: protect } }) && p.startsWith('/api/open/');
  return {
    role, now: 1000, me: { username }, settings: { _protect: protect, aliases: [] },
    peer: () => null,
    can(method, path) {
      if (role === 'guest') return 'no';
      if (path.startsWith('/api/grant/')) return role === 'owner' ? 'yes' : 'ask';
      if (path.startsWith('/api/open/')) return role === 'admin' && prot(path) ? 'ask' : 'yes';
      return 'no';
    },
  };
}
const grant = (user = 'admin', until = 2000) => ({ admins: true, sessions: { grants: [{ id: '19', user, until }] } });

test('paths', () => {
  assert.equal(openPath(c, obj), '/api/open/19/workstation');
  assert.equal(grantPath(c, { id: 'a b' }), '/api/grant/19/a%20b');
});

test('owner opens; guest never', () => {
  assert.equal(mode({ admins: false }, c, obj, ctx('owner')), 'open');
  assert.equal(mode({ admins: true }, c, obj, ctx('guest')), null);
});

test('admin: nothing while admins are off, ask without a grant, open with a live one', () => {
  assert.equal(mode({ admins: false }, c, obj, ctx('admin')), null);
  assert.equal(mode({ admins: true, sessions: { grants: [] } }, c, obj, ctx('admin')), 'ask');
  assert.equal(mode(grant(), c, obj, ctx('admin')), 'open');
  assert.equal(mode(grant('someone-else'), c, obj, ctx('admin')), 'ask');
  assert.equal(mode(grant('admin', 999), c, obj, ctx('admin')), 'ask');  // expired
  assert.equal(grantFor(grant(), c, ctx('admin')).user, 'admin');
});

test('_protect: protected machines are owner only (owner gets a confirm, admin no button even with a grant)', () => {
  for (const p of ['/api/open/19/**', 'POST /api/open/19/workstation', 'POST,DELETE /api/open/*/workstation', '/api/**']) {
    assert.equal(isProtected(c, obj, { settings: { _protect: [p] } }), true, p);
    assert.equal(mode(grant(), c, obj, ctx('admin', { protect: [p] })), null, p);
    assert.equal(mode({}, c, obj, ctx('owner', { protect: [p] })), 'open', p);
  }
  for (const p of ['/api/open/20/**', 'GET /api/open/19/workstation', 'POST /api/open/19/workstation numbers=1', '/api/grant/19/**']) {
    assert.equal(isProtected(c, obj, { settings: { _protect: [p] } }), false, p);
  }
});

test('connections match objects by vmid hint via peers, else label', () => {
  const d = { connections: [c, { ...c, id: '5', label: 'pve1', vmid: null }] };
  const cx = { settings: {}, peer: (id) => (id === 'proxmox' ? { resources: [{ type: 'lxc', vmid: 112, name: 'workstation' }] } : null) };
  assert.deepEqual(connsFor(d, { id: 'workstation' }, cx).map((x) => x.id), ['19']);
  assert.deepEqual(connsFor(d, { id: 'PVE1' }, cx).map((x) => x.id), ['5']);
});
