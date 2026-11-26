// jellyfin — reactive helpers: items opened in this browser (they become `jellyfin-item:<id>` objects, so the object panel
// can show them) and plain-text GETs (logs).
import { label } from './jf.js';
import { act, forget } from '$lab/sdk.js';

export const IID = (id) => `jellyfin-item:${id}`;

// Items the user opened (newest first, capped): objects() turns them into objects; nothing is stored server side.
export const opened = $state({ list: [] });
export function remember(it) {
  if (!it?.Id) return IID('');
  const row = { id: it.Id, name: label(it), type: it.Type, series: it.SeriesName || null };
  opened.list = [row, ...opened.list.filter((x) => x.id !== it.Id)].slice(0, 24);
  return IID(it.Id);
}

// Jellyfin log files are text/plain: ctx.api.text
export const textGet = (ctx, path, query) => ctx.api.text(path, query);

// act() after dropping the cached loads this write changes (see `cached` in index.js), so the refresh right after it shows the result
export function write(ctx, keys, opts) {
  for (const k of keys) forget(`${ctx.id}:${k}`);
  return act(ctx, opts);
}
