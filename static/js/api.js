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

// Ilova versiyasi: sahifa yuklangan versiya (modul manzilidagi /assets/<release>/). Server boshqasini aytsa — sayt
// yangilangan: foydalanuvchiga bir marta «sahifani yangilang» deyiladi (eski kod yangi server bilan jim buzilmasin).
const LOADED_RELEASE = (import.meta.url.match(/\/assets\/([0-9a-f]{12})\//) || [])[1] || null;
let onNewRelease = null;
let announced = false;
export function setNewReleaseHandler(fn) {
  onNewRelease = fn;
}

function checkRelease(res) {
  const release = res.headers.get('X-Release');
  if (LOADED_RELEASE && release && release !== LOADED_RELEASE && !announced && onNewRelease) {
    announced = true;
    onNewRelease(release);
  }
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
  checkRelease(res);
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    if (res.status === 401 && onUnauthorized && !path.startsWith('/api/auth/')) onUnauthorized();
    const err = new ApiError((data && data.error) || `Xatolik yuz berdi (${res.status})`, res.status);
    err.data = data; // masalan, o'yin holati eskirgan bo'lsa server yangi holatni ham yuboradi
    throw err;
  }
  return data;
}
