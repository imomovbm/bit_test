// Umumiy yordamchilar: DOM, ikonlar, dialoglar, formatlash, ovoz.

export const LETTERS = 'ABCDEFGHIJ';

export function h(tag, attrs, ...children) {
  const parts = tag.split('.');
  const el = document.createElement(parts[0] || 'div');
  if (parts.length > 1) el.className = parts.slice(1).join(' ');
  if (attrs && attrs.constructor === Object) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class') el.className = el.className ? `${el.className} ${v}` : v;
      else if (k === 'style' && typeof v === 'object') {
        for (const [p, val] of Object.entries(v)) {
          if (p.startsWith('--')) el.style.setProperty(p, val); // CSS o'zgaruvchilari faqat shu yo'l bilan
          else el.style[p] = val;
        }
      }
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'html') el.innerHTML = v; // faqat ishonchli (ichki) matn uchun
      else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'hidden') el[k] = v;
      else el.setAttribute(k, v === true ? '' : String(v));
    }
  } else if (attrs !== undefined && attrs !== null) {
    children.unshift(attrs);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false || c === true) continue;
    if (Array.isArray(c)) append(el, c);
    else if (c instanceof Node) el.append(c);
    else el.append(document.createTextNode(String(c)));
  }
}

// ---------------------------------------------------------------- ikonlar
const ICONS = {
  swords: '<polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/><line x1="13" x2="19" y1="19" y2="13"/><line x1="16" x2="20" y1="16" y2="20"/><line x1="19" x2="21" y1="21" y2="19"/><polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5"/><line x1="5" x2="9" y1="14" y2="18"/><line x1="7" x2="4" y1="17" y2="20"/><line x1="3" x2="5" y1="19" y2="21"/>',
  book: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  trophy: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
  sliders: '<line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/><line x1="2" x2="6" y1="14" y2="14"/><line x1="10" x2="14" y1="8" y2="8"/><line x1="18" x2="22" y1="16" y2="16"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" x2="15.42" y1="13.51" y2="17.49"/><line x1="15.41" x2="8.59" y1="6.51" y2="10.49"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  message: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  volume: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>',
  mute: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  edit: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
  eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/>',
  file: '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" x2="8" y1="13" y2="13"/><line x1="16" x2="8" y1="17" y2="17"/><line x1="10" x2="8" y1="9" y2="9"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  right: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  left: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
  flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  wifiOff: '<line x1="2" x2="22" y1="2" y2="22"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M2 8.82a15 15 0 0 1 4.17-2.65"/><path d="M10.66 5c4.01-.36 8.14.9 11.34 3.76"/><path d="M16.85 11.25a10 10 0 0 1 2.22 1.68"/><path d="M5 13a10 10 0 0 1 5.24-2.76"/><line x1="12" x2="12.01" y1="20" y2="20"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/>',
  shuffle: '<path d="m18 14 4 4-4 4"/><path d="m18 2 4 4-4 4"/><path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/>',
  balloon: '<path d="M12 2c3.6 0 6.3 2.7 6.3 6.1 0 3.9-3.1 7.1-6.3 7.6-3.2-.5-6.3-3.7-6.3-7.6C5.7 4.7 8.4 2 12 2Z"/><path d="m10.8 17.4 1.2-1.6 1.2 1.6Z"/><path d="M12 17.4c-1.4.8-1.4 1.6 0 2.3s1.4 1.5 0 2.3"/><path d="M9.2 7a3.3 3.3 0 0 1 2-2.1"/>',
  dice: '<rect width="18" height="18" x="3" y="3" rx="3.5"/><path d="M16 8h.01"/><path d="M8 8h.01"/><path d="M8 16h.01"/><path d="M16 16h.01"/><path d="M12 12h.01"/>',
  maximize: '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
  minimize: '<path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  play: '<polygon points="7 4 20 12 7 20 7 4"/>',
  sparkles: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
  help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  grid: '<rect width="7" height="9" x="3" y="3" rx="1.5"/><rect width="7" height="5" x="14" y="3" rx="1.5"/><rect width="7" height="9" x="14" y="12" rx="1.5"/><rect width="7" height="5" x="3" y="16" rx="1.5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  search: '<circle cx="11" cy="11" r="7.5"/><path d="m20.5 20.5-4.2-4.2"/>',
  userPlus: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" x2="19" y1="8" y2="14"/><line x1="22" x2="16" y1="11" y2="11"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  unlock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  crown: '<path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.734H5.81a1 1 0 0 1-.957-.734L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294z"/><path d="M5 21h14"/>',
  bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
  minus: '<path d="M5 12h14"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  folderPlus: '<path d="M12 10v6"/><path d="M9 13h6"/><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
};

export function icon(name, size = 20) {
  const span = document.createElement('span');
  span.className = 'ic';
  span.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  return span;
}

export function logoMark(size = 32) {
  const span = document.createElement('span');
  span.className = 'logo-mark';
  span.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="tdlg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5b50f0"/><stop offset="1" stop-color="#f26b1d"/></linearGradient></defs><rect width="32" height="32" rx="9" fill="url(#tdlg)"/><g fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" transform="translate(4 4)">${ICONS.swords}</g></svg>`;
  return span;
}

// ---------------------------------------------------------- avatar, ranglar
function hashStr(s) {
  let x = 0;
  for (const ch of String(s)) x = (x * 31 + ch.codePointAt(0)) >>> 0;
  return x;
}

export function avatar(login, size = 'md') {
  const hue = hashStr(login) % 360;
  return h('span', {
    class: `avatar ${size}`,
    style: { background: `linear-gradient(135deg, hsl(${hue} 70% 58%), hsl(${(hue + 40) % 360} 70% 48%))` },
    'aria-hidden': 'true',
  }, (String(login || '?').trim()[0] || '?').toUpperCase());
}

// ------------------------------------------------------------- formatlash
export function fmtMs(ms) {
  const s = (ms || 0) / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} daq ${Math.round(s - m * 60)} s`;
}

export function fmtClock(sec) {
  sec = Math.max(0, Math.floor(sec));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

/** "5 daqiqa oldin" ko'rinishidagi vaqt (bir haftadan eski bo'lsa — sana). */
export function fmtAgo(ms) {
  if (!ms) return '—';
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return 'hozirgina';
  if (s < 3600) return `${Math.floor(s / 60)} daqiqa oldin`;
  if (s < 86400) return `${Math.floor(s / 3600)} soat oldin`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} kun oldin`;
  return fmtDate(ms);
}

export function fmtDate(ms) {
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function pct(part, whole) {
  return whole ? Math.round((part / whole) * 100) : 0;
}

export function shuffleArray(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// ------------------------------------------------------------------ toast
export function toast(message, kind = 'info', ms = 3800) {
  const root = document.getElementById('toasts');
  if (!root) return;
  const ic = { success: 'check', error: 'alert', warning: 'alert', info: 'zap' }[kind] || 'zap';
  const el = h('div', { class: `toast ${kind}`, role: kind === 'error' ? 'alert' : 'status' }, icon(ic, 18), h('span', message));
  root.append(el);
  requestAnimationFrame(() => el.classList.add('show'));
  const remove = () => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 250);
  };
  el.addEventListener('click', remove);
  setTimeout(remove, ms);
}

// ------------------------------------------------------------------ modal
const openModals = new Set();

export function openModal({ title, body, actions = [], wide = false, dismissible = true, onClose } = {}) {
  const previouslyFocused = document.activeElement;
  const bodyEl = h('div.modal-body', body);
  const footer = h('div.modal-foot');
  const box = h('div', { class: `modal${wide ? ' wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title || 'Oyna' },
    h('div.modal-head',
      h('h3', title || ''),
      dismissible ? h('button.icon-btn', { type: 'button', 'aria-label': 'Yopish', onclick: () => close(null) }, icon('x', 18)) : null),
    bodyEl,
    footer);
  const overlay = h('div.modal-overlay', box);
  let closed = false;

  function close(value) {
    if (closed) return;
    closed = true;
    openModals.delete(api);
    document.removeEventListener('keydown', onKey, true);
    overlay.classList.remove('show');
    setTimeout(() => overlay.remove(), 180);
    if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus({ preventScroll: true });
    if (onClose) onClose(value);
  }

  function onKey(e) {
    if (e.key === 'Escape' && dismissible) {
      e.stopPropagation();
      close(null);
    }
  }

  function setActions(list) {
    footer.replaceChildren(...list.filter(Boolean).map((a) => {
      const btn = h('button', { type: 'button', class: `btn ${a.kind || 'ghost'}`, disabled: !!a.disabled }, a.icon ? icon(a.icon, 16) : null, a.text);
      btn.addEventListener('click', async () => {
        if (a.onClick) {
          btn.disabled = true;
          try {
            await a.onClick(api, btn);
          } finally {
            if (!closed) btn.disabled = !!a.disabled;
          }
        } else {
          close(a.value === undefined ? null : a.value);
        }
      });
      a.el = btn;
      return btn;
    }));
    footer.hidden = !list.filter(Boolean).length;
  }

  const api = { close, el: box, body: bodyEl, setActions };
  setActions(actions);
  overlay.addEventListener('mousedown', (e) => {
    if (e.target === overlay && dismissible) close(null);
  });
  document.addEventListener('keydown', onKey, true);
  document.body.append(overlay);
  openModals.add(api);
  requestAnimationFrame(() => {
    overlay.classList.add('show');
    const focusable = box.querySelector('input, textarea, select, .modal-foot .btn.primary, .modal-foot .btn.danger');
    if (focusable) focusable.focus({ preventScroll: true });
  });
  return api;
}

export function closeAllModals() {
  for (const m of [...openModals]) m.close(null);
}

export function confirmDialog({ title = 'Tasdiqlash', message, okText = 'Ha', cancelText = 'Bekor qilish', danger = false } = {}) {
  return new Promise((resolve) => {
    openModal({
      title,
      body: h('p.confirm-text', message),
      onClose: (v) => resolve(v === true),
      actions: [
        { text: cancelText, value: false },
        { text: okText, value: true, kind: danger ? 'danger' : 'primary' },
      ],
    });
  });
}

export function promptDialog({ title, label, value = '', okText = 'Saqlash', type = 'text', placeholder = '', hint = '', validate } = {}) {
  return new Promise((resolve) => {
    const input = h('input', { type, value, placeholder, autocomplete: 'off' });
    const err = h('div.field-error');
    const submit = (m) => {
      const v = input.value.trim();
      const msg = validate ? validate(v) : (v ? '' : 'Qiymat kiriting');
      if (msg) {
        err.textContent = msg;
        input.focus();
        return;
      }
      m.close(v);
    };
    const m = openModal({
      title,
      body: h('label.field', h('span.field-label', label), input, hint ? h('span.field-hint', hint) : null, err),
      onClose: (v) => resolve(typeof v === 'string' ? v : null),
      actions: [{ text: 'Bekor qilish' }, { text: okText, kind: 'primary', onClick: submit }],
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submit(m);
      }
    });
    setTimeout(() => input.select(), 30);
  });
}

// ------------------------------------------------------------ boshqalar
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = h('textarea', { style: { position: 'fixed', top: '-1000px', opacity: '0' } });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    let done = false;
    try {
      done = document.execCommand('copy');
    } catch {
      done = false;
    }
    ta.remove();
    return done;
  }
}

/** .txt faylni o'qiydi: UTF-8 / UTF-16 (BOM) yoki Windows-1251 kodirovkasini aniqlaydi. */
export async function readTextFile(file) {
  const buf = new Uint8Array(await file.arrayBuffer());
  if (buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) return new TextDecoder('utf-8').decode(buf.subarray(3));
  if (buf[0] === 0xff && buf[1] === 0xfe) return new TextDecoder('utf-16le').decode(buf.subarray(2));
  if (buf[0] === 0xfe && buf[1] === 0xff) return new TextDecoder('utf-16be').decode(buf.subarray(2));
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buf);
  } catch {
    return new TextDecoder('windows-1251').decode(buf);
  }
}

/**
 * Sahifalash tugmalari. onChange(page) — sahifa tanlanganda. Bitta sahifa bo'lsa bo'sh element qaytaradi.
 * Masalan: 1 … 4 5 [6] 7 8 … 20
 */
export function pager({ page, pages, total, per, onChange }) {
  const el = h('nav.pager', { 'aria-label': 'Sahifalar' });
  if (pages <= 1) return el;
  const btn = (p, label, attrs = {}) => h('button', {
    type: 'button',
    class: `pager-btn${p === page ? ' active' : ''}`,
    'aria-current': p === page ? 'page' : null,
    disabled: p < 1 || p > pages || p === page,
    onclick: () => onChange(p),
    ...attrs,
  }, label);
  const nums = new Set([1, pages, page - 1, page, page + 1]);
  if (page <= 3) [2, 3, 4].forEach((n) => nums.add(n));
  if (page >= pages - 2) [pages - 1, pages - 2, pages - 3].forEach((n) => nums.add(n));
  const list = [...nums].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const items = [];
  list.forEach((n, i) => {
    if (i && n - list[i - 1] > 1) items.push(h('span.pager-gap', '…'));
    items.push(btn(n, String(n)));
  });
  const from = (page - 1) * per + 1;
  el.append(...[
    btn(page - 1, icon('left', 16), { 'aria-label': 'Oldingi sahifa', title: 'Oldingi sahifa' }),
    ...items,
    btn(page + 1, icon('right', 16), { 'aria-label': 'Keyingi sahifa', title: 'Keyingi sahifa' }),
    total !== undefined ? h('span.pager-info', `${from}–${Math.min(total, page * per)} / ${total}`) : null,
  ].filter(Boolean));
  return el;
}

/** Ro'yxatning bitta sahifasi (mijoz tomonida sahifalash uchun). Sahifa raqami chegaradan chiqsa tuzatiladi. */
export function slicePage(items, page, per) {
  const pages = Math.max(1, Math.ceil(items.length / per));
  const p = Math.min(Math.max(1, page), pages);
  return { page: p, pages, items: items.slice((p - 1) * per, p * per), total: items.length, per };
}

export function spinner(text = 'Yuklanmoqda…') {
  return h('div.loading', h('span.spinner'), h('span', text));
}

export function emptyState(ic, title, text, action) {
  return h('div.empty', h('div.empty-ic', icon(ic, 28)), h('h3', title), text ? h('p', text) : null, action || null);
}

export function progressRing(percent, cls = '') {
  const R = 52;
  const C = 2 * Math.PI * R;
  const wrap = h('div', { class: `ring ${cls}` });
  wrap.innerHTML = `<svg viewBox="0 0 120 120" width="132" height="132"><circle class="ring-track" cx="60" cy="60" r="${R}"/><circle class="ring-arc" cx="60" cy="60" r="${R}" stroke-dasharray="${C}" stroke-dashoffset="${C}" transform="rotate(-90 60 60)"/></svg><div class="ring-text"><b>${Math.round(percent)}%</b></div>`;
  const arc = wrap.querySelector('.ring-arc');
  requestAnimationFrame(() => requestAnimationFrame(() => {
    arc.style.strokeDashoffset = String(C * (1 - Math.max(0, Math.min(100, percent)) / 100));
  }));
  return wrap;
}

export function confetti(palette) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const colors = palette && palette.length ? palette : ['#5b50f0', '#f26b1d', '#12a150', '#f7b500', '#e03131', '#2563eb'];
  const layer = h('div.confetti');
  for (let i = 0; i < 70; i++) {
    const piece = h('i', {
      style: {
        left: `${Math.random() * 100}%`,
        background: colors[i % colors.length],
        animationDelay: `${Math.random() * 0.6}s`,
        animationDuration: `${2.2 + Math.random() * 1.6}s`,
        transform: `rotate(${Math.random() * 360}deg)`,
      },
    });
    layer.append(piece);
  }
  document.body.append(layer);
  setTimeout(() => layer.remove(), 4500);
}

// ------------------------------------------------------------------- ovoz
let audioCtx = null;
const SOUNDS = {
  match: [[523, 110], [659, 110], [784, 200]],
  tick: [[880, 60]],
  correct: [[784, 80], [1175, 140]],
  wrong: [[262, 220]],
  win: [[523, 120], [659, 120], [784, 120], [1047, 300]],
  lose: [[392, 180], [330, 180], [262, 320]],
  draw: [[523, 160], [523, 160]],
};

export function isSoundOn() {
  try {
    return localStorage.getItem('td-sound') !== 'off';
  } catch {
    return true;
  }
}

export function setSoundOn(on) {
  try {
    localStorage.setItem('td-sound', on ? 'on' : 'off');
  } catch {
    /* saqlab bo'lmasa ham ishlayveradi */
  }
}

export function initAudio() {
  const unlock = () => {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') audioCtx.resume();
    } catch {
      audioCtx = null;
    }
  };
  document.addEventListener('pointerdown', unlock, { passive: true });
  document.addEventListener('keydown', unlock);
}

let noiseBuf = null;

function noise(t, dur, { type = 'bandpass', freq = 1500, q = 0.8, gain = 0.4, attack = 0.003 } = {}) {
  if (!noiseBuf) {
    noiseBuf = audioCtx.createBuffer(1, audioCtx.sampleRate * 2, audioCtx.sampleRate);
    const data = noiseBuf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  }
  const src = audioCtx.createBufferSource();
  src.buffer = noiseBuf;
  const filter = audioCtx.createBiquadFilter();
  filter.type = type;
  filter.frequency.value = freq;
  filter.Q.value = q;
  const g = audioCtx.createGain();
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(gain, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(filter).connect(g).connect(audioCtx.destination);
  src.start(t, Math.random() * 0.5);
  src.stop(t + dur + 0.02);
}

function tone(t, dur, f0, f1, { type = 'sine', gain = 0.2 } = {}) {
  const osc = audioCtx.createOscillator();
  const g = audioCtx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(f0, t);
  osc.frequency.exponentialRampToValueAtTime(f1, t + dur);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(gain, t + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(g).connect(audioCtx.destination);
  osc.start(t);
  osc.stop(t + dur + 0.02);
}

/** O'yin effektlari: pop (shar portlashi), roll (zar), land (zar to'xtadi), splash, chomp. */
export function sfx(kind) {
  if (!audioCtx || !isSoundOn()) return;
  try {
    const t = audioCtx.currentTime + 0.005;
    if (kind === 'pop') {
      noise(t, 0.13, { freq: 1700 + Math.random() * 600, q: 0.7, gain: 0.55, attack: 0.002 });
      tone(t, 0.09, 520, 140, { type: 'triangle', gain: 0.18 });
    } else if (kind === 'roll') {
      let x = t;
      for (let i = 0; i < 9; i++) {
        noise(x, 0.04, { type: 'highpass', freq: 2500, gain: 0.22 });
        x += 0.06 + Math.random() * 0.07;
      }
    } else if (kind === 'land') {
      tone(t, 0.16, 170, 60, { gain: 0.35 });
      noise(t, 0.05, { type: 'highpass', freq: 2200, gain: 0.25 });
    } else if (kind === 'splash') {
      noise(t, 0.8, { type: 'lowpass', freq: 1100, q: 0.4, gain: 0.5, attack: 0.02 });
      for (let i = 0; i < 4; i++) tone(t + 0.25 + i * 0.11, 0.08, 500 + Math.random() * 500, 900, { gain: 0.06 });
    } else if (kind === 'chomp') {
      tone(t, 0.09, 140, 70, { type: 'square', gain: 0.16 });
      tone(t + 0.16, 0.11, 120, 55, { type: 'square', gain: 0.18 });
    }
  } catch {
    /* ovozsiz davom etamiz */
  }
}

export function beep(kind) {
  if (!audioCtx || !isSoundOn()) return;
  const seq = SOUNDS[kind];
  if (!seq) return;
  try {
    let t = audioCtx.currentTime + 0.01;
    for (const [freq, dur] of seq) {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'triangle';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.12, t + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + dur / 1000);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t);
      osc.stop(t + dur / 1000 + 0.03);
      t += dur / 1000;
    }
  } catch {
    /* ovozsiz davom etamiz */
  }
}
