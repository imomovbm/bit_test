// REST API bilan ishlash.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized = null;
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export async function api(path, { method = 'GET', body } = {}) {
  const opts = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new ApiError("Server bilan aloqa yo'q. Internet yoki serverni tekshiring", 0);
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    if (res.status === 401 && onUnauthorized && !path.startsWith('/api/auth/')) onUnauthorized();
    throw new ApiError((data && data.error) || `Xatolik yuz berdi (${res.status})`, res.status);
  }
  return data;
}
