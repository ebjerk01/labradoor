// The module SDK's reactive half (runes): call these while a component initialises (top of <script>), or inside
// $effect.root(). Modules import them from `$lab/sdk.js`. Reference: docs/sdk.md.
import { loader, startPoll, watchTask } from './sdk-core.js';

// A GET that runs now and again whenever pathFn() / query() change; pathFn() → null/'' = nothing to load.
// Returns {data, error, loading, denied, reload}: data = the whole JSON answer (or pick(answer)); error = one line of
// text; denied = 'ask' | 'no' when this user may not read the route (it is then not sent). The data is cleared when
// the path changes unless keep: true. Call reload() after a write.
//   const users = lazy(() => ctx, () => `/api/users/${id}`, { query: () => ({ page }), pick: (r) => r.items });
// It also loads again when the module reports a change (ctx.rev: a write through act(), a panel action, or another
// tab's write pushed by the gateway); that reload keeps the shown data until the answer is in (no flicker).
// follow: false opts out, for loads that are expensive to repeat (an interactive indexer search).
export function lazy(getCtx, pathFn, opts = {}) {
  const s = $state({ data: null, error: null, loading: true, denied: null });
  const reload = loader(s, getCtx, pathFn, opts);
  let last;
  $effect(() => {
    const key = JSON.stringify([pathFn() ?? null, opts.query?.() ?? null]);
    if (opts.follow !== false) (typeof getCtx === 'function' ? getCtx() : getCtx)?.rev;  // dependency: the module's change counter
    if (key !== last && !opts.keep) s.data = null;
    last = key;
    reload();
  });
  return {
    get data() { return s.data; }, get error() { return s.error; }, get loading() { return s.loading; },
    get denied() { return s.denied; }, reload,
  };
}

// fn() now and every `ms` while the component is mounted (skipped while the tab is hidden unless hidden: true).
// Stopped when the component is destroyed; stop() ends it earlier.
export function poll(fn, ms, opts = {}) {
  let stop = () => {};
  $effect(() => {
    stop = startPoll(fn, ms, opts);
    return () => stop();
  });
  return { stop: () => stop() };
}

// Background tasks being watched (watch()), newest first: [{id, module, label, started}]. Render it anywhere.
export const watching = $state({ list: [] });

// Watch a task this module started until it ends, then toast + refresh; see watchTask in sdk-core.js for options.
// Not tied to a component: it keeps watching when the view is left.
export function watch(ctx, opts) {
  return watchTask(ctx, opts, watching);
}
