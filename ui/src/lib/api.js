// Small fetch wrapper. Errors carry .status and the server's JSON (e.g. {approval: true} for owner-only routes).
export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error || `HTTP ${status}`);
    this.status = status;
    this.body = body || {};
  }
}

async function req(method, url, body, raw) {
  const opt = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
  if (raw !== undefined) {
    opt.headers['Content-Type'] = raw.type || 'application/octet-stream';
    opt.body = raw;
  } else if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(url, opt);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text.slice(0, 200) }; }
  if (!r.ok) throw new ApiError(r.status, data);
  return data;
}

// a GET whose answer is plain text (logs): the text as-is; errors still carry .status and the server's JSON
async function getText(url) {
  const r = await fetch(url, { headers: { Accept: 'text/plain, */*' }, credentials: 'same-origin' });
  const text = await r.text();
  if (!r.ok) {
    let data;
    try { data = JSON.parse(text); } catch { data = { error: text.slice(0, 200) }; }
    throw new ApiError(r.status, data);
  }
  return text;
}

export const api = {
  get: (url, query) => req('GET', query ? `${url}?${new URLSearchParams(query)}` : url),
  text: (url, query) => getText(query ? `${url}?${new URLSearchParams(query)}` : url),
  post: (url, body = {}) => req('POST', url, body),
  patch: (url, body = {}) => req('PATCH', url, body),
  del: (url) => req('DELETE', url),
  put: (url, body = {}) => req('PUT', url, body),
  raw: (method, url, blob) => req(method, url, undefined, blob),
};

// The API a module's UI code gets: paths are its own backend paths, the gateway checks + signs them.
export function moduleApi(id) {
  const base = `/api/m/${id}`;
  return {
    get: (path, query) => api.get(base + path, query),
    text: (path, query) => api.text(base + path, query),
    post: (path, body) => api.post(base + path, body),
    patch: (path, body) => api.patch(base + path, body),
    del: (path) => api.del(base + path),
    put: (path, body) => api.put(base + path, body),
    upload: (path, blob, method = 'PUT') => api.raw(method, base + path, blob),
  };
}
