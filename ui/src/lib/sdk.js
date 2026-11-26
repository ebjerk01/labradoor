// The module SDK: the one import a module's UI needs besides its own files and the shared components.
//   import { act, lazy, cached, errText, ago, Glyph … } from '$lab/sdk.js';
// Everything a module needs from the shell comes through `ctx` (ctx.api, ctx.can, ctx.peer, ctx.open …), never from
// `$lab/lab.svelte.js`. Reference with examples: docs/sdk.md. Enforced for "manifest": 2 modules by
// tests/module_isolation.test.mjs.
export { GLYPH, RANK, worst, statusVar, bytes, rate, bits, pct, num, ago, dur, clock, sparkPoints, memLevel, safeUrl } from './fmt.js';
export {
  LOCALE, errText, qs, withQuery, barePath, act, getOrDenied, soft, cached, forget, ts, rel, duration, when, day, hhmm,
  worstOf, siteStatus, level, clip, sortRows, readonly,
} from './sdk-core.js';
export { lazy, poll, watch, watching } from './sdk.svelte.js';
