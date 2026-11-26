// guacamole — terminals and consoles (the Guacamole server) on lab's machine objects. Backend = the lab connector
// connectors/guacamole (127.0.0.1:8112 on the lab CT), logged in as the read-only Guacamole user lab-svc. Guacamole hides
// hosts from non-admins, so a connection is matched to an object by the hints in its name: "(CT 112)" → the guest with
// vmid 112, else the name's first word ("pve1 (Proxmox, …)" → pve1).
// Opening one goes through POST /api/open/<connection>/<object> (audited; owner, or an admin holding a grant the owner
// approved); the answer's client URL opens in its own window, where Guacamole signs in the viewer's OWN account.
import { soft } from '$lab/sdk.js';
import ConsoleFacet from './ConsoleFacet.svelte';
import ConsolesTile from './ConsolesTile.svelte';
import { objectFor, connsFor, mode, openPath, grantPath, kindOf, isProtected, protectQuestion, show } from './guac.js';

export default {
  id: 'guacamole',

  async load(ctx) {
    const [d, sessions] = await Promise.all([ctx.api.get('/api/connections'), soft(ctx.api.get('/api/sessions'))]);
    return { ...d, sessions };
  },

  actions(obj, d, ctx) {
    const cs = connsFor(d, obj, ctx);
    const out = [];
    for (const c of cs) {
      const m = mode(d, c, obj, ctx);
      const name = cs.length > 1 ? `${kindOf(c)} ${c.protocol}` : kindOf(c);
      if (m === 'open') {
        out.push({ label: name, icon: 'shell', method: 'POST', path: openPath(c, obj),
          confirm: ctx.role === 'owner' && isProtected(c, obj, ctx) ? protectQuestion(c, obj) : undefined,
          done: (r) => show(r, ctx) });
      } else if (m === 'ask') {
        out.push({ label: `${name} (${d.sessions?.grant_minutes || 30} min)`, icon: 'shell', method: 'POST', path: grantPath(c, obj) });
      }
    }
    return out;
  },

  ticker(d, ctx) {
    return d.connections.filter((c) => c.active).map((c) => ({ g: '●', c: 'var(--sig)', s: 'guac', m: `${c.active} session${c.active > 1 ? 's' : ''} on ${objectFor(c, ctx)}`, object: objectFor(c, ctx) }));
  },

  // Ctrl-K: "console <machine>" opens the machine (its panel has the button); "terminal <machine>" finds the action itself
  search(d, ctx) {
    return d.connections.map((c) => ({ label: `${kindOf(c)} ${objectFor(c, ctx)}`, sub: `${c.protocol} · ${c.group || 'guacamole'}`,
      object: objectFor(c, ctx), status: c.active ? 'ok' : undefined }));
  },

  facets: { machine: ConsoleFacet },
  tiles: [{ id: 'consoles', label: 'consoles', w: 2, h: 1, component: ConsolesTile }],
};
