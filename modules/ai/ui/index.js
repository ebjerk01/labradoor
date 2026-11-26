// ai — the assistant (connectors/ai, 127.0.0.1:8117, Claude API). Reads lab as the signed-in person through the
// gateway's delegation (never more, never secret routes, redacted); changes only as proposals the person runs with a
// click. Rail: ~/ai chat · triage · usage. Every object gets an "ai" facet (triage notes + "ask ai"); Ctrl-K: "? question".
import Chat from './Chat.svelte';
import Triage from './Triage.svelte';
import Usage from './Usage.svelte';
import Facet from './Facet.svelte';
import SpendTile from './SpendTile.svelte';
import SummaryTile from './SummaryTile.svelte';
import Overview from './Overview.svelte';
import { askQuick, startSync, bind } from './state.svelte.js';

const money = (v) => `$${Number(v || 0).toFixed(2)}`;

export default {
  id: 'ai',

  async load(ctx) {
    bind(ctx);
    const st = await ctx.api.get('/api/state');
    if (st.enabled) startSync();
    return st;
  },

  kpis(d) {
    const p = d.month.cap ? d.month.spent / d.month.cap : 0;
    return [{ label: 'ai spend', value: money(d.month.spent), sub: `of $${d.month.cap}`, status: p >= 1 ? 'bad' : p >= 0.8 ? 'warn' : null, view: 'ai-usage' }];
  },

  alerts(d) {
    if (d.month.spent < d.month.cap) return [];
    return [{ key: 'ai:cap', status: 'warn', title: 'AI budget used up', since: d.month.start,
      detail: `${money(d.month.spent)} of $${d.month.cap}: the assistant refuses until the reset` }];
  },

  ticker(d, ctx) {
    const out = d.triage.filter((t) => ['queued', 'running'].includes(t.status))
      .map((t) => ({ g: '●', c: 'var(--sig)', s: 'ai', view: 'ai-triage', m: `triaging: ${t.alert?.title || t.key}` }));
    const today = new Date(ctx.now * 1000).toLocaleDateString('sv-SE');
    if (d.summary?.day === today && d.summary.status === 'done') out.push({ g: '●', c: 'var(--sig)', s: 'ai', view: 'ai-triage', m: 'morning summary ready (~/ai triage)' });
    return out;
  },

  // Ctrl-K: "? question" asks the assistant
  async lookup(q, ctx) {
    bind(ctx);
    const s = q.trim();
    if (!s.startsWith('?') || s.length < 4) return [];
    const question = s.slice(1).trim();
    return [{ label: `ask ai: ${question}`, sub: 'enter asks', run: () => askQuick(question) }];
  },

  facets: { '*': Facet },
  overview: Overview,
  tiles: [
    { id: 'spend', label: 'ai spend', w: 2, h: 1, component: SpendTile, min: 'admin' },
    { id: 'summary', label: 'morning summary', w: 4, h: 2, component: SummaryTile, min: 'admin' },
  ],
  views: [
    { id: 'ai', label: 'chat', icon: 'shell', component: Chat, min: 'admin' },
    { id: 'ai-triage', label: 'triage', icon: 'bell', component: Triage, min: 'admin' },
    { id: 'ai-usage', label: 'usage', icon: 'activity', component: Usage, min: 'admin' },
  ],
};
