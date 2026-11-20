// Ilova: marshrutlar (router), umumiy qobiq (sarlavha, menyu) va global hodisalar.
import { h, icon, logoMark, avatar, toast, confirmDialog, closeAllModals, beep, initAudio, isSoundOn, setSoundOn, fmtClock, confetti } from './lib.js';
import { api, setUnauthorizedHandler } from './api.js';
import { live } from './live.js';
import { authView } from './views/auth.js';
import { duelView } from './views/duel.js';
import { inviteView } from './views/invite.js';
import { practiceView } from './views/practice.js';
import { balloonView } from './views/balloon.js';
import { statsView } from './views/stats.js';
import { adminView } from './views/admin.js';

const ROUTES = [
  { path: '/login', view: authView('login'), public: true },
  { path: '/register', view: authView('register'), public: true },
  { path: '/duel', view: duelView, nav: 'duel' },
  { path: '/invite/:code', view: inviteView, nav: 'duel' },
  { path: '/practice', view: practiceView, nav: 'practice' },
  { path: '/practice/:id', view: practiceView, nav: 'practice' },
  { path: '/balloon', view: balloonView, nav: 'balloon' },
  { path: '/balloon/:id', view: balloonView, nav: 'balloon' },
  { path: '/stats', view: statsView, nav: 'stats' },
  { path: '/admin', view: adminView, nav: 'admin', admin: true },
];

const NAV = [
  { id: 'duel', href: '#/duel', icon: 'swords', label: 'Duel' },
  { id: 'practice', href: '#/practice', icon: 'book', label: 'Oʻrganish' },
  { id: 'balloon', href: '#/balloon', icon: 'balloon', label: 'Balloon Pop' },
  { id: 'stats', href: '#/stats', icon: 'trophy', label: 'Reyting' },
  { id: 'admin', href: '#/admin', icon: 'sliders', label: 'Boshqaruv', admin: true },
];

const state = { user: null };
const rootEl = document.getElementById('app');
let shell = null;
let current = null;
let bannerTimer = null;
const baseTitle = document.title;

const ctx = {
  get user() {
    return state.user;
  },
  navigate,
  onLogin,
  logout,
};

// ---------------------------------------------------------------- router
function parseHash() {
  const raw = location.hash.replace(/^#/, '') || '/';
  const qi = raw.indexOf('?');
  return {
    path: (qi >= 0 ? raw.slice(0, qi) : raw) || '/',
    query: new URLSearchParams(qi >= 0 ? raw.slice(qi + 1) : ''),
  };
}

function matchRoute(path) {
  for (const route of ROUTES) {
    const keys = [];
    const re = new RegExp(`^${route.path.replace(/:(\w+)/g, (_, k) => {
      keys.push(k);
      return '([^/]+)';
    })}/?$`);
    const m = path.match(re);
    if (m) {
      const params = {};
      keys.forEach((k, i) => {
        params[k] = decodeURIComponent(m[i + 1]);
      });
      return { route, params };
    }
  }
  return null;
}

function navigate(path) {
  if (location.hash === `#${path}`) render();
  else location.hash = `#${path}`;
}

function redirect(path) {
  history.replaceState(null, '', `#${path}`);
  render();
}

function render() {
  const { path, query } = parseHash();
  const m = matchRoute(path);
  if (!state.user) {
    if (!m || !m.route.public) {
      if (m && m.route.path === '/invite/:code') sessionStorage.setItem('td-invite', m.params.code);
      return redirect('/login');
    }
  } else if (!m || m.route.public || (m.route.admin && !state.user.isAdmin)) {
    return redirect('/duel');
  }
  mount(m, path, query);
}

function mount(m, path, query) {
  if (current && current.cleanup) {
    try {
      current.cleanup();
    } catch (e) {
      console.error(e);
    }
  }
  closeAllModals();
  const container = m.route.public ? authLayout() : appLayout();
  container.replaceChildren();
  let cleanup = null;
  try {
    cleanup = m.route.view(container, m.params, ctx, query);
  } catch (e) {
    console.error(e);
    container.append(h('div.alert.error', `Sahifani ochishda xatolik: ${e.message}`));
  }
  current = { path, route: m.route, cleanup: typeof cleanup === 'function' ? cleanup : null };
  setActiveNav(m.route.nav);
  updateBanner();
  window.scrollTo({ top: 0 });
}

function inActiveDuel() {
  return !!live.duel && live.duel.phase !== 'done';
}

function confirmLeave() {
  return confirmDialog({
    title: 'Duelni tark etasizmi?',
    message: 'Agar hozir chiqib ketsangiz, duelda magʻlub deb topilasiz va raqibingiz gʻolib boʻladi.',
    okText: 'Ha, chiqaman',
    cancelText: 'Duelni davom ettirish',
    danger: true,
  });
}

let guardOpen = false;
async function onHashChange() {
  const { path } = parseHash();
  if (state.user && current && current.path === '/duel' && path !== '/duel' && inActiveDuel()) {
    const target = location.hash;
    history.replaceState(null, '', '#/duel');
    if (guardOpen) return;
    guardOpen = true;
    const ok = await confirmLeave();
    guardOpen = false;
    if (!ok) return;
    if (inActiveDuel()) live.leaveDuel();
    history.replaceState(null, '', target);
  }
  render();
}

// ----------------------------------------------------------------- qobiq
function authLayout() {
  shell = null;
  clearInterval(bannerTimer);
  const main = h('main.auth-main');
  rootEl.replaceChildren(main);
  return main;
}

function appLayout() {
  if (!shell) shell = buildShell();
  return shell.main;
}

function buildShell() {
  const user = state.user;
  const items = NAV.filter((n) => !n.admin || user.isAdmin);
  const topLinks = items.map((n) => h('a.nav-link', { href: n.href, title: n.label, 'aria-label': n.label, dataset: { nav: n.id } }, icon(n.icon, 18), h('span', n.label)));
  const bottomLinks = items.map((n) => h('a.bnav-link', { href: n.href, dataset: { nav: n.id } }, icon(n.icon, 22), h('span', n.label)));
  const onlineCount = h('b', '0');
  const onlinePill = h('a.pill.online-pill', { href: '#/duel', title: 'Hozir onlayn foydalanuvchilar' }, h('span.live-dot'), onlineCount, h('span.hide-sm', ' onlayn'));
  const connPill = h('span.pill.conn-pill', { hidden: true }, icon('wifiOff', 14), h('span.hide-sm', 'Ulanmoqda…'));
  const soundBtn = h('button.icon-btn', { type: 'button', title: 'Ovozni yoqish/oʻchirish', 'aria-label': 'Ovoz', onclick: toggleSound });
  const themeBtn = h('button.icon-btn', { type: 'button', title: 'Yorugʻ/qorongʻi rejim', 'aria-label': 'Mavzu rangi', onclick: toggleTheme });
  const userBox = h('div.user-box', { title: user.login }, avatar(user.login, 'sm'), h('span.user-name.hide-sm', user.login), user.isAdmin ? h('span.badge.admin.hide-sm', 'admin') : null);
  const logoutBtn = h('button.icon-btn', { type: 'button', title: 'Chiqish', 'aria-label': 'Chiqish', onclick: logout }, icon('logout', 18));
  const header = h('header.app-header',
    h('div.header-inner',
      h('a.brand', { href: '#/duel' }, logoMark(30), h('span.brand-text', 'Test', h('b', 'Duel'))),
      h('nav.top-nav', topLinks),
      h('div.header-right', connPill, onlinePill, soundBtn, themeBtn, userBox, logoutBtn)));
  const main = h('main.app-main');
  const banner = h('div.queue-banner', { hidden: true });
  const bottom = h('nav.bottom-nav', bottomLinks);
  rootEl.replaceChildren(header, main, banner, bottom);
  const s = { header, main, banner, bottom, onlineCount, connPill, soundBtn, themeBtn };
  paintSound(s);
  paintTheme(s);
  paintHeader(s);
  return s;
}

function setActiveNav(id) {
  if (!shell) return;
  for (const a of rootEl.querySelectorAll('[data-nav]')) a.classList.toggle('active', a.dataset.nav === id);
}

function paintHeader(s = shell) {
  if (!s) return;
  s.onlineCount.textContent = String(live.presence.online || 0);
  s.connPill.hidden = live.status === 'online';
}

function updateBanner() {
  if (!shell) return;
  const q = live.queue;
  const onDuelPage = current && current.path === '/duel';
  clearInterval(bannerTimer);
  if (!q || onDuelPage) {
    shell.banner.hidden = true;
    return;
  }
  const time = h('span.mono');
  const tick = () => {
    time.textContent = fmtClock((Date.now() - (q.localSince || Date.now())) / 1000);
  };
  tick();
  bannerTimer = setInterval(tick, 1000);
  shell.banner.replaceChildren(
    h('span.spinner.sm'),
    h('div.qb-text', h('b', q.inviteFor ? `${q.inviteFor.login} kutilmoqda` : 'Raqib kutilmoqda'), h('span.muted', ` · ${q.topicName} · `), time),
    h('a.btn.primary.sm', { href: '#/duel' }, 'Ochish'),
    h('button.icon-btn', { type: 'button', title: 'Bekor qilish', 'aria-label': 'Kutishni bekor qilish', onclick: () => live.leaveQueue() }, icon('x', 16)));
  shell.banner.hidden = false;
}

function currentTheme() {
  return document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem('td-theme', next);
  } catch {
    /* e'tiborsiz */
  }
  paintTheme(shell);
}

function paintTheme(s) {
  if (s) s.themeBtn.replaceChildren(icon(currentTheme() === 'dark' ? 'sun' : 'moon', 18));
}

function toggleSound() {
  setSoundOn(!isSoundOn());
  paintSound(shell);
  if (isSoundOn()) beep('correct');
}

function paintSound(s) {
  if (s) s.soundBtn.replaceChildren(icon(isSoundOn() ? 'volume' : 'mute', 18));
}

let titleTimer = null;
function flashTitle(text) {
  if (!document.hidden) return;
  clearInterval(titleTimer);
  let on = false;
  titleTimer = setInterval(() => {
    on = !on;
    document.title = on ? text : baseTitle;
  }, 900);
  const stop = () => {
    clearInterval(titleTimer);
    document.title = baseTitle;
    document.removeEventListener('visibilitychange', stop);
  };
  document.addEventListener('visibilitychange', stop);
}

// ------------------------------------------------------------ kirish/chiqish
function onLogin(user) {
  state.user = user;
  shell = null;
  live.connect();
  const invite = sessionStorage.getItem('td-invite');
  sessionStorage.removeItem('td-invite');
  navigate(invite ? `/invite/${encodeURIComponent(invite)}` : '/duel');
}

async function logout() {
  if (inActiveDuel()) {
    if (!(await confirmLeave())) return;
    live.leaveDuel();
  } else if (live.queue) {
    live.leaveQueue();
  }
  await new Promise((r) => setTimeout(r, 80));
  try {
    await api('/api/auth/logout', { method: 'POST' });
  } catch {
    /* baribir chiqamiz */
  }
  live.disconnect();
  state.user = null;
  shell = null;
  navigate('/login');
}

// ------------------------------------------------------ global hodisalar
live.on('change', (kind) => {
  paintHeader();
  if (['queue', 'hello', 'duel:start', 'duel:end', 'status'].includes(kind)) updateBanner();
});

live.on('duel:start', () => {
  beep('match');
  flashTitle('⚔ Raqib topildi!');
  if (!current || current.path !== '/duel') navigate('/duel');
});

live.on('duel:feedback', (fb) => beep(fb.correct ? 'correct' : 'wrong'));

live.on('duel:end', (r) => {
  beep(r.result === 'win' ? 'win' : r.result === 'draw' ? 'draw' : 'lose');
  if (r.result === 'win') confetti();
  if (!current || current.path !== '/duel') {
    const label = { win: 'Gʻalaba! 🏆', lose: 'Magʻlubiyat', draw: 'Durang' }[r.result];
    toast(`Duel yakunlandi: ${label} (${r.me.correct}:${r.opp.correct})`, r.result === 'win' ? 'success' : 'info', 7000);
  }
});

live.on('unauthorized', () => {
  if (!state.user) return;
  state.user = null;
  shell = null;
  live.disconnect();
  toast('Sessiya muddati tugagan. Qaytadan kiring', 'warning');
  navigate('/login');
});
setUnauthorizedHandler(() => live.emit('unauthorized'));

window.addEventListener('beforeunload', (e) => {
  if (inActiveDuel()) {
    e.preventDefault();
    e.returnValue = '';
  }
});

// ------------------------------------------------------------------ start
async function boot() {
  initAudio();
  try {
    const r = await api('/api/auth/me');
    state.user = r.user || null;
  } catch (e) {
    toast(e.message, 'error');
  }
  if (state.user) live.connect();
  window.addEventListener('hashchange', onHashChange);
  render();
}

boot();
