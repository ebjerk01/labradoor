// The logs view's search, shared so a facet / tile / Ctrl-K can open the view with a query already in it.
export const logq = $state({ q: '*', range: 3600, sources: [], stream: '', live: false, run: 0 });

export function searchLogs(ctx, { q = '*', range = 3600, sources = [], stream = '' } = {}) {
  Object.assign(logq, { q, range, sources, stream });
  logq.run++;
  ctx.go('graylog-logs');   // also closes the object panel
}
