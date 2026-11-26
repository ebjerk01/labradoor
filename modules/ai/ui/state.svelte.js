// ai — shared state of the chat (one per tab), the poller for running answers, the alert/object snapshot sync,
// and running a proposal the user clicked (through the TARGET module's normal gateway path: verdicts, owner
// approval and audit all apply; the assistant itself never writes).
import { untrack } from 'svelte';

// The shell's ctx for this module, handed over by load()/lookup(): this file keeps state outside any component and
// still must not import the shell (docs/sdk.md). requires "*" + delegate lets it reach every module the user may use.
let C = null;
export const bind = (ctx) => { C = ctx; };

export const ai = $state({
  conv: null,        // open conversation id (null = a new chat)
  title: '',
  owner: '',
  items: [],         // rendered conversation from the connector
  live: [],          // items built from the running turn's events
  running: false,
  error: '',
  draft: '',
  context: null,     // object the new chat is about (from the object panel)
  focus: 0,          // bump → the input takes focus
});

const api = () => C.api;
let pollTimer = null;
let seen = 0;

export async function openConv(id) {
  stopPoll();
  ai.error = '';
  ai.live = [];
  try {
    const r = await api().get(`/api/conversations/${id}`);
    ai.conv = id;
    ai.title = r.conversation.title;
    ai.owner = r.conversation.owner;
    ai.items = r.items;
    if (r.running) { seen = 0; ai.running = true; poll(); } else ai.running = false;
  } catch (e) { ai.error = e.message; }
}

export function newChat(context = null) {
  stopPoll();
  Object.assign(ai, { conv: null, title: '', owner: C.me?.username || '', items: [], live: [], running: false, error: '', context });
  ai.focus++;
}

export async function send(text) {
  text = (text || '').trim();
  if (!text || ai.running) return;
  ai.error = '';
  ai.items = [...ai.items, { t: 'q', text, at: Date.now() / 1000 }];
  ai.live = [];
  ai.running = true;
  seen = 0;
  try {
    if (!ai.conv) {
      const r = await api().post('/api/conversations', { text, ...(ai.context ? { context: ai.context } : {}) });
      ai.conv = r.conversation;
      ai.title = text.slice(0, 70);
      ai.context = null;
    } else {
      await api().post(`/api/conversations/${ai.conv}/messages`, { text });
    }
    poll();
    C.refresh();
  } catch (e) {
    ai.running = false;
    ai.error = e.body?.budget ? `budget: ${e.message}` : e.message;
  }
}

export async function stop() {
  if (ai.conv) { try { await api().post(`/api/conversations/${ai.conv}/stop`, {}); } catch { /* ignore */ } }
}

export async function remove(id) {
  try {
    await api().del(`/api/conversations/${id}`);
    if (ai.conv === id) newChat();
    C.refresh();
  } catch (e) { C.notify(e.message, 'bad'); }
}

function stopPoll() { clearTimeout(pollTimer); pollTimer = null; }

function poll() {
  stopPoll();
  const cid = ai.conv;
  pollTimer = setTimeout(async () => {
    if (cid !== ai.conv) return;
    try {
      const r = await api().get(`/api/conversations/${cid}/live`, { since: seen });
      if (cid !== ai.conv) return;
      for (const ev of r.events) apply(ev);
      seen += r.events.length;
      if (r.status === 'running') return poll();
      ai.running = false;
      await openConv(cid);
      C.refresh();
    } catch (e) { ai.running = false; ai.error = e.message; }
  }, document.hidden ? 1500 : 350);
}

// running turn → items, the same shapes the connector renders afterwards
function apply(ev) {
  const L = ai.live;
  const last = L[L.length - 1];
  if (ev.name === 'propose_action') return;  // its card (ev.t === 'proposal') stands for it
  if (ev.t === 'text') {
    if (last?.t === 'a') last.text += ev.d; else L.push({ t: 'a', text: ev.d });
  } else if (ev.t === 'note') {
    if (last?.t === 'note') last.text += ev.d; else L.push({ t: 'note', text: ev.d });
  } else if (ev.t === 'tool_start') {
    L.push({ t: 'tool', id: ev.id, name: ev.name, args: '', running: true });
  } else if (ev.t === 'tool') {
    const it = L.find((x) => x.t === 'tool' && x.id === ev.id);
    if (it) it.args = ev.args; else L.push({ t: 'tool', id: ev.id, name: ev.name, args: ev.args, running: true });
  } else if (ev.t === 'tool_done') {
    const it = L.find((x) => x.t === 'tool' && x.id === ev.id);
    if (it) Object.assign(it, { running: false, ok: ev.ok, size: ev.size });
  } else if (ev.t === 'proposal') {
    L.push({ t: 'proposal', p: ev.p });
  } else if (ev.t === 'refusal') {
    L.push({ t: 'sys', text: 'declined by the API safety system' });
  } else if (ev.t === 'error') {
    ai.error = ev.d;
  }
}

// --- entry points from the rest of lab ------------------------------------------------------------------------------
export function objectContext(o) {
  if (!o) return null;
  const alerts = C.alerts().filter((a) => a.object === o.id).map((a) => ({ module: a.module, key: a.key, status: a.status, title: a.title, detail: a.detail }));
  return { object: { id: o.id, name: o.name, type: o.type, kind: o.kind, status: o.status, parent: o.parent, meta: o.meta, sources: o.sources }, alerts };
}

export function askAbout(o) {
  newChat(objectContext(o));
  const word = { bad: 'red', warn: 'yellow' }[o.status];
  ai.draft = word ? `why is ${o.name} ${word}?` : `how is ${o.name} doing?`;
  C.go('ai');
}

export function askQuick(q) {
  newChat();
  C.go('ai');
  setTimeout(() => send(q), 0);
}

// --- running a proposal (a click) -----------------------------------------------------------------------------------
export async function runProposal(p, after) {
  const c = C.via(p.module);
  if (!c) { C.notify(`module ${p.module} is not available to you`, 'bad'); return; }
  const full = p.path + (p.query ? `?${p.query}` : '');
  const verdict = c.can(p.method, p.path);
  if (verdict === 'no') { C.notify(`not allowed: ${p.label}`, 'bad'); return; }
  const body = p.body == null ? undefined : p.body;
  const shown = `${p.label}\n\n${p.method} ${p.module} ${full}${body !== undefined ? `\n${JSON.stringify(body)}` : ''}\n\n`;
  if (!confirm(shown + (verdict === 'ask' ? 'This needs the owner\'s approval. Send the request?' : 'Run it?'))) return;
  const report = (outcome, extra = {}) => api().post(`/api/proposals/${p.id}/result`, { outcome, ...extra })
    .then((r) => { if (r.running && ai.conv === r.conversation) { seen = 0; ai.running = true; ai.live = []; poll(); } else after?.(); })
    .catch((e) => C.notify(e.message, 'bad'));
  if (verdict === 'ask') {
    const ap = await c.ask(p.method, full, body, p.label, `via ai: ${p.why || ''}`.slice(0, 480));
    if (ap) await report('asked', { approval: ap.id });
    return;
  }
  try {
    const call = { POST: () => c.api.post(full, body ?? {}), PUT: () => c.api.put(full, body ?? {}),
      PATCH: () => c.api.patch(full, body ?? {}), DELETE: () => c.api.del(full) }[p.method];
    const r = await call();
    C.notify(`${p.label} ✓`);
    await report('ran', { code: 200, excerpt: JSON.stringify(r ?? null).slice(0, 1500) });
  } catch (e) {
    if (e.body?.approval) {
      const ap = await c.ask(p.method, full, body, p.label, `via ai: ${p.why || ''}`.slice(0, 480));
      if (ap) await report('asked', { approval: ap.id });
      return;
    }
    C.notify(`${p.label}: ${e.message}`, 'bad');
    await report('failed', { code: e.status || 0, excerpt: String(e.message).slice(0, 500) });
  }
  C.refresh();
}

export async function dismissProposal(p, after) {
  try {
    await api().post(`/api/proposals/${p.id}/result`, { outcome: 'dismissed' });
    after?.();
  } catch (e) { C.notify(e.message, 'bad'); }
}

// --- snapshot sync: alerts + objects are computed in the browser; the connector needs them for triage, the
// summary and the "current alerts" tool. Posted 5 s after a change and at least every 5 min (lab refreshes every 15 s, which re-runs the effect; the
// morning summary starts on a sync after its time).
let started = false;
export function startSync() {
  if (started) return;
  started = true;
  let last = '', lastAt = 0, timer = null;
  const push = (payload, key) => {
    if (key === last && Date.now() - lastAt < 300000) return;
    C.api.post('/api/sync', payload).then(() => { last = key; lastAt = Date.now(); }).catch(() => {});
  };
  $effect.root(() => {
    $effect(() => {
      const alerts = C.alerts().filter((a) => a.module !== 'ai')
        .map((a) => ({ key: String(a.key ?? ''), module: a.module, status: a.status, title: a.title, detail: a.detail, object: a.object, since: a.since }));
      const objects = [...C.objects().values()].map((o) => ({ id: o.id, type: o.type, name: o.name, kind: o.kind, status: o.status, parent: o.parent, sources: o.sources }));
      untrack(() => {
        const mine = C.data();
        if (C.role === 'guest' || mine == null || !mine.enabled) return;
        const payload = { alerts, objects };
        const key = JSON.stringify(payload);
        clearTimeout(timer);
        timer = setTimeout(() => push(payload, key), 5000);
      });
    });
  });
}
