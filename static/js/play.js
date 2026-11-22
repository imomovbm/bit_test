// O'quvchilar sahifasi (/play, /play/PIN): ro'yxatdan o'tmasdan — faqat PIN va ism. Telefonlar uchun yengil:
// asosiy ilova (app.js, lib.js) yuklanmaydi, shakllar — inline SVG, serverdan faqat kichik xabarlar keladi
// (savol matni va variantlar o'qituvchi ekranida; bu yerda faqat rangli shakllar).
import { GAME_NAME, SHAPES, shapeIcon, formatPin } from './octagon/common.js';

const T = {
  pageTitle: `${GAME_NAME} — oʻyinga qoʻshilish`,
  pinLabel: 'Oʻyin PIN kodi',
  pinHint: 'Oʻqituvchi ekranidagi 6 xonali raqam',
  next: 'Davom etish',
  nickLabel: 'Ismingiz',
  nickHint: '1–20 belgi. Bu ism oʻqituvchi ekranida koʻrinadi.',
  nickPlaceholder: 'Masalan: Ali',
  join: 'Oʻyinga kirish',
  changePin: 'Boshqa PIN',
  pinBad: 'PIN — 6 xonali son (masalan: 482 913)',
  nickEmpty: 'Ismingizni kiriting',
  checking: 'Tekshirilmoqda…',
  reconnecting: 'Aloqa uzildi — qayta ulanmoqda…',
  lobbyTitle: 'Siz oʻyindasiz!',
  lobbyText: 'Ismingizni oʻqituvchi ekranida koʻryapsizmi? Oʻyin boshlanishini kuting…',
  question: (i, n) => `Savol ${i} / ${n}`,
  getReady: 'Tayyorlaning!',
  lookUp: 'Savol va javoblarni oʻqituvchi ekranidan oʻqing',
  chooseShape: 'Toʻgʻri javob shaklini bosing',
  sent: 'Javob yuborildi',
  waitOthers: 'Boshqalar javob berishini kutamiz…',
  correct: 'Toʻgʻri!',
  wrong: 'Notoʻgʻri',
  noAnswer: 'Javob berilmadi',
  correctWas: 'Toʻgʻri javob',
  points: (p) => `+${fmt(p)} ball`,
  score: 'ball',
  rank: (k, n) => `${k}-oʻrin · ${n} ta oʻquvchi`,
  waitNext: 'Keyingi savolni kuting…',
  waitFinal: 'Yakuniy natijalarni kuting…',
  joinedLate: 'Siz oʻyinga qoʻshildingiz. Keyingi savol tez orada boshlanadi.',
  finished: 'Oʻyin tugadi!',
  place: (k) => `${k}-oʻrin`,
  winners: 'Gʻoliblar',
  kicked: 'Oʻqituvchi sizni oʻyindan chiqardi',
  kickedText: 'Boshqa ism bilan qayta qoʻshilishingiz mumkin.',
  replaced: 'Oʻyin boshqa oynada ochildi',
  replacedText: 'Siz shu oʻyinga boshqa oyna yoki qurilmadan kirdingiz. Oʻyin oʻsha yerda davom etmoqda.',
  continueHere: 'Shu yerda davom etish',
  ended: 'Oʻyin yopildi',
  endedText: 'Oʻqituvchi oʻyinni yakunladi. Rahmat!',
  rejoin: 'Qayta qoʻshilish',
  otherGame: 'Boshqa oʻyinga qoʻshilish',
  gone: 'Oldingi oʻyindagi joyingiz topilmadi — qaytadan qoʻshiling.',
  late: 'Vaqt tugadi — javob qabul qilinmadi',
  queued: 'Aloqa yoʻq — javob ulanish tiklanishi bilan yuboriladi',
  answer: (name) => `Javob: ${name}`,
  you: 'Siz',
};

const PIN_KEY = (pin) => `oct:${pin}`;
const PIN_RE = /^[1-9]\d{5}$/;             // serverdagi PIN_RE bilan bir xil
const ME_TTL = 12 * 3600 * 1000;           // saqlangan o'yinchi (ID + token) 12 soatdan keyin unutiladi
const root = document.getElementById('play');
document.title = T.pageTitle;

const st = {
  view: 'pin',          // pin | checking | nick | game | closed
  pin: '',
  me: null,             // {id, tok, nick}
  s: null,              // serverdan kelgan oxirgi holat
  deadline: 0,          // joriy bosqich tugaydigan payt (performance.now)
  picked: null,         // {q, o} — tanlangan, server hali tasdiqlamagan javob
  queued: null,         // aloqa yo'qligida tanlangan javob
  late: false,
  error: '',
  closed: null,         // replaced | kicked | ended
  status: 'connecting', // connecting | online | offline
  rtt: 0,
};

// ---------------------------------------------------------------- yordamchilar
function el(tag, attrs, ...children) {
  const [name, ...classes] = tag.split('.');
  const node = document.createElement(name);
  if (classes.length) node.className = classes.join(' ');
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
  } else if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else if (k === 'style') Object.assign(node.style, v);
      else node.setAttribute(k, v === true ? '' : String(v));
    }
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function fmt(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function urlPin() {
  const m = location.pathname.match(/^\/play\/(\d{6})\/?$/) || location.search.match(/[?&]pin=(\d{6})(?:&|$)/);
  return m && PIN_RE.test(m[1]) ? m[1] : '';
}

function saveMe(pin, me) {
  const value = JSON.stringify({ ...me, at: Date.now() });
  try {
    localStorage.setItem(PIN_KEY(pin), value);
  } catch {
    const secure = location.protocol === 'https:' ? '; secure' : '';
    document.cookie = `oct_${pin}=${encodeURIComponent(value)}; path=/play; max-age=${ME_TTL / 1000}; samesite=strict${secure}`;
  }
}

function validMe(me) {
  return me && typeof me.id === 'string' && typeof me.tok === 'string' && Date.now() - (me.at || 0) < ME_TTL ? me : null;
}

function loadMe(pin) {
  try {
    const v = localStorage.getItem(PIN_KEY(pin));
    if (v) return validMe(JSON.parse(v));
  } catch {
    /* localStorage yo'q — cookie */
  }
  const m = document.cookie.match(new RegExp(`(?:^|; )oct_${pin}=([^;]*)`));
  if (m) {
    try {
      return validMe(JSON.parse(decodeURIComponent(m[1])));
    } catch {
      /* buzilgan */
    }
  }
  return null;
}

// Eski o'yinlardan qolgan ID/tokenlar (umumiy kompyuterlarda) qurilmada to'planib qolmasin
function pruneStored() {
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith('oct:')) continue;
      let me = null;
      try {
        me = validMe(JSON.parse(localStorage.getItem(key)));
      } catch {
        /* buzilgan */
      }
      if (!me) localStorage.removeItem(key);
    }
  } catch {
    /* localStorage yo'q */
  }
}

function forgetMe(pin) {
  try {
    localStorage.removeItem(PIN_KEY(pin));
  } catch {
    /* e'tiborsiz */
  }
  document.cookie = `oct_${pin}=; path=/play; max-age=0`;
}

// -------------------------------------------------------------------- aloqa
let ws = null;
let retry = 0;
let retryTimer = 0;
let stopped = false;
let pending = null;   // ulanish ochilganda yuboriladigan so'rov (check/join)
let lastMsgAt = 0;
let pingAt = 0;

function connect() {
  clearTimeout(retryTimer);
  if (ws || stopped) return;
  const sock = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/octagon`);
  ws = sock;
  setStatus(st.status === 'online' ? 'connecting' : st.status);
  sock.onopen = () => {
    retry = 0;
    lastMsgAt = Date.now();
    setStatus('online');
    if (st.me && st.pin) send('resume', { pin: st.pin, id: st.me.id, tok: st.me.tok });
    else if (pending) send(pending.t, pending.d);
    ping();
  };
  sock.onmessage = (ev) => {
    lastMsgAt = Date.now();
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg && typeof msg.t === 'string') onMessage(msg.t, msg.d || {});
  };
  sock.onclose = (ev) => {
    if (ws !== sock) return;
    ws = null;
    if (ev.code === 4001 || ev.code === 4002 || ev.code === 4003) {
      showClosed({ 4001: 'replaced', 4002: 'kicked', 4003: 'ended' }[ev.code]);
      return;
    }
    setStatus('offline');
    schedule();
  };
}

function schedule() {
  if (stopped) return;
  clearTimeout(retryTimer);
  const delay = Math.min(5000, 400 * 2 ** retry) + Math.random() * 400;
  retry = Math.min(retry + 1, 6);
  retryTimer = setTimeout(connect, delay);
}

function reconnectNow() {
  if (!ws && !stopped) {
    retry = 0;
    connect();
  }
}

function send(t, d = {}) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ t, d }));
    return true;
  }
  return false;
}

function ping() {
  pingAt = performance.now();
  send('ping');
}

setInterval(() => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (Date.now() - lastMsgAt > 45000) ws.close(); // jim o'lgan ulanish
  else ping();
}, 15000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    reconnectNow();
    keepAwake();
  }
});
window.addEventListener('online', reconnectNow);

function setStatus(s) {
  st.status = s;
  const bar = root.querySelector('.pl-conn');
  if (bar) bar.hidden = s === 'online' || st.view === 'closed';
}

// ------------------------------------------------------------------ xabarlar
function onMessage(t, d) {
  switch (t) {
    case 'pong':
      if (pingAt) st.rtt = Math.min(2000, performance.now() - pingAt);
      break;
    case 'c':
      pending = null;
      st.error = '';
      st.view = 'nick';
      render();
      break;
    case 'w':
      pending = null;
      st.me = { id: d.id, tok: d.tok || (st.me && st.me.tok), nick: d.nick };
      st.pin = d.pin;
      saveMe(st.pin, st.me);
      if (location.pathname !== `/play/${st.pin}`) history.replaceState(null, '', `/play/${st.pin}`);
      st.view = 'game';
      st.error = '';
      keepAwake();
      render();
      break;
    case 's':
      onState(d);
      break;
    case 'e':
      onError(d);
      break;
    case 'k':
      showClosed(d.r);
      break;
    default:
      break;
  }
}

function onState(s) {
  const prev = st.s;
  const newQuestion = !prev || prev.q !== s.q || prev.p !== s.p;
  st.s = s;
  if (typeof s.r === 'number') st.deadline = performance.now() + s.r - Math.min(st.rtt / 2, 1000);
  if (s.a != null) st.picked = null;            // server tasdiqladi
  if (newQuestion && s.p === 'question' && s.a == null) {
    st.late = false;
    if (!(st.picked && st.picked.q === s.q)) st.picked = null;
  }
  if (st.queued && s.p === 'question' && s.q === st.queued.q && s.a == null) {
    send('a', { q: st.queued.q, o: st.queued.o });  // qayta ulanishdan keyin navbatdagi javob
    st.queued = null;
  }
  if (s.p !== 'question') st.queued = null;
  if (st.view === 'game') render();
}

function onError(e) {
  if (['pin', 'rate', 'nick', 'taken', 'banned', 'full', 'ended', 'locked'].includes(e.c)) pending = null; // qayta ulanishda takrorlanmasin
  switch (e.c) {
    case 'pin':
    case 'rate':
      st.view = st.me ? st.view : 'pin';
      st.error = e.m;
      render();
      break;
    case 'locked':  // o'qituvchi yangi qo'shilishlarni to'xtatgan
      if (!st.me) {
        st.view = st.view === 'nick' ? 'nick' : 'pin';
        st.error = e.m;
        render();
      }
      break;
    case 'nick':
    case 'taken':
    case 'banned':
    case 'full':
      st.view = 'nick';
      st.error = e.m;
      render();
      break;
    case 'ended':
      if (!st.me) showClosed('ended');
      break;
    case 'gone':  // saqlangan joy topilmadi (o'yin tugagan, server qayta ishga tushgan yoki chiqarilgan)
      forgetMe(st.pin);
      st.me = null;
      st.s = null;
      st.error = T.gone;
      st.view = 'checking';
      pending = { t: 'check', d: { pin: st.pin } };
      send(pending.t, pending.d);
      render();
      break;
    case 'late':
      if (st.picked) {
        st.picked = null;
        st.late = true;
        render();
      }
      break;
    case 'early':  // savol hali ochilmagan (soatlar farqi) — tanlov bekor, savol ochilganda qayta bosish mumkin
      st.picked = null;
      render();
      break;
    default:
      break;
  }
}

function showClosed(reason) {
  stopped = true;
  clearTimeout(retryTimer);
  if (reason === 'kicked' || reason === 'ended') forgetMe(st.pin);
  if (reason === 'kicked') st.me = null;
  st.closed = reason || 'ended';
  st.view = 'closed';
  if (ws) {
    const s = ws;
    ws = null;
    s.close();
  }
  render();
}

// ------------------------------------------------------------------- amallar
function submitPin(value) {
  const pin = String(value || '').replace(/\D/g, '');
  if (!PIN_RE.test(pin)) {
    st.error = T.pinBad;
    render();
    return;
  }
  st.pin = pin;
  const me = loadMe(pin);
  if (me) {  // shu PIN bilan oldin qo'shilgan — davom etamiz
    st.me = me;
    st.view = 'game';
    if (!send('resume', { pin, id: me.id, tok: me.tok })) reconnectNow();
    render();
    return;
  }
  st.view = 'checking';
  st.error = '';
  pending = { t: 'check', d: { pin } };
  if (!send(pending.t, pending.d)) reconnectNow();
  render();
}

function submitNick(value) {
  const nick = String(value || '').trim();
  if (!nick) {
    st.error = T.nickEmpty;
    render();
    return;
  }
  st.error = '';
  pending = { t: 'join', d: { pin: st.pin, nick } };
  if (!send(pending.t, pending.d)) reconnectNow();
  render();
}

function pick(o) {
  const s = st.s;
  if (!s || s.p !== 'question' || s.a != null || st.picked) return;
  if (performance.now() > st.deadline + 150) {
    st.late = true;
    render();
    return;
  }
  st.picked = { q: s.q, o };
  if (navigator.vibrate) navigator.vibrate(25);
  if (!send('a', { q: s.q, o })) st.queued = { q: s.q, o };
  render();
}

function restart(keepPin) {
  stopped = false;
  st.closed = null;
  st.me = null;
  st.s = null;
  st.error = '';
  pending = null;
  if (keepPin && st.pin) {
    st.view = 'checking';
    pending = { t: 'check', d: { pin: st.pin } };
  } else {
    st.view = 'pin';
    st.pin = '';
    history.replaceState(null, '', '/play');
  }
  reconnectNow();
  render();
}

function continueHere() {
  stopped = false;
  st.closed = null;
  st.me = loadMe(st.pin);
  st.view = st.me ? 'game' : 'checking';
  if (!st.me) pending = { t: 'check', d: { pin: st.pin } };
  reconnectNow();
  render();
}

let wakeLock = null;
async function keepAwake() {
  try {
    if ('wakeLock' in navigator && !wakeLock && st.view === 'game') {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => {
        wakeLock = null;
      });
    }
  } catch {
    /* qo'llab-quvvatlanmaydi */
  }
}

// --------------------------------------------------------------------- chizish
function topBar() {
  const pin = st.pin && st.view !== 'pin' ? el('div.pl-pin', el('span', 'PIN'), el('b', formatPin(st.pin))) : el('div.pl-brand', GAME_NAME);
  const s = st.s;
  const me = st.me && st.view === 'game'
    ? el('div.pl-me', el('span.pl-nick', st.me.nick), s ? el('span.pl-score', fmt(s.sc), el('small', ` ${T.score}`)) : null)
    : null;
  const conn = el('div.pl-conn', { role: 'status' }, el('span.pl-spin'), T.reconnecting);
  conn.hidden = st.status === 'online' || st.view === 'closed' || st.view === 'pin';
  return [el('header.pl-top', pin, me), conn];
}

function errorLine() {
  return el('p.pl-error', { role: 'alert', hidden: !st.error }, st.error || '');
}

function viewPin() {
  const input = el('input.pl-input.pl-pin-input', {
    type: 'text', inputmode: 'numeric', autocomplete: 'off', maxlength: 7, placeholder: '000 000',
    'aria-label': T.pinLabel, value: formatPin(st.pin),
  });
  input.addEventListener('input', () => {
    const digits = input.value.replace(/\D/g, '').slice(0, 6);
    input.value = digits.length > 3 ? `${digits.slice(0, 3)} ${digits.slice(3)}` : digits;
  });
  const form = el('form.pl-card', { novalidate: true },
    el('h1', T.pinLabel), el('p.pl-muted', T.pinHint), input, errorLine(),
    el('button.pl-btn', { type: 'submit' }, T.next));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    submitPin(input.value);
  });
  setTimeout(() => input.focus(), 50);
  return form;
}

function viewChecking() {
  return el('div.pl-card.pl-center', el('div.pl-spin.lg'), el('p.pl-muted', T.checking), errorLine());
}

function viewNick() {
  const input = el('input.pl-input', {
    type: 'text', maxlength: 20, autocomplete: 'nickname', autocapitalize: 'words', spellcheck: 'false',
    placeholder: T.nickPlaceholder, 'aria-label': T.nickLabel,
  });
  const waiting = pending && pending.t === 'join';
  const form = el('form.pl-card', { novalidate: true },
    el('h1', T.nickLabel), el('p.pl-muted', T.nickHint), input, errorLine(),
    el('button.pl-btn', { type: 'submit', disabled: waiting }, T.join),
    el('button.pl-link', { type: 'button', onclick: () => restart(false) }, T.changePin));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    submitNick(input.value);
  });
  setTimeout(() => input.focus(), 50);
  return form;
}

function shapeBadge(o, size) {
  const s = SHAPES[o];
  return el('span.pl-shape', { style: { background: s.bg, color: s.fg }, role: 'img', 'aria-label': s.name }, shapeIcon(o, size));
}

function viewGame() {
  const s = st.s;
  if (!s) return el('div.pl-card.pl-center', el('div.pl-spin.lg'));
  const qLabel = s.q != null ? T.question(s.q + 1, s.n) : '';
  switch (s.p) {
    case 'lobby':
      return el('div.pl-wait',
        el('div.pl-pulse', el('span', '✓')),
        el('h1', T.lobbyTitle),
        el('p.pl-big-nick', st.me ? st.me.nick : ''),
        el('p.pl-muted', T.lobbyText));
    case 'ready':
      return el('div.pl-wait',
        el('p.pl-qlabel', qLabel),
        el('div.pl-count', { 'data-countdown': '' }, String(Math.max(1, Math.ceil((st.deadline - performance.now()) / 1000)))),
        el('h1', T.getReady),
        el('p.pl-muted', T.lookUp));
    case 'question': {
      const chosen = s.a != null ? s.a : st.picked ? st.picked.o : null;
      const timer = el('div.pl-timer', el('div.pl-timer-bar', { 'data-bar': '' }), el('span.pl-timer-num', { 'data-countdown': '' }, ''));
      if (chosen != null) {
        return el('div.pl-wait',
          el('p.pl-qlabel', qLabel), timer,
          shapeBadge(chosen, 64),
          el('h1', T.sent),
          el('p.pl-muted', st.queued ? T.queued : T.waitOthers));
      }
      if (st.late) {
        return el('div.pl-wait', el('p.pl-qlabel', qLabel), el('div.pl-res-ic.bad', '⏱'), el('h1', T.late));
      }
      const grid = el(`div.pl-grid.n${s.o}`, { role: 'group', 'aria-label': T.chooseShape },
        Array.from({ length: s.o }, (_, o) => {
          const sh = SHAPES[o];
          return el('button.pl-answer', {
            type: 'button', style: { background: sh.bg, color: sh.fg }, 'aria-label': T.answer(sh.name),
            onclick: () => pick(o),
          }, shapeIcon(o, 72));
        }));
      return el('div.pl-question', el('div.pl-qhead', el('span.pl-qlabel', qLabel), timer), grid);
    }
    case 'reveal':
    case 'leaderboard': {
      const r = s.res;
      if (!r) return el('div.pl-wait', el('div.pl-pulse', el('span', '…')), el('h1', T.joinedLate), rankLine(s));
      const ok = r.ok === true;
      return el(`div.pl-result.${ok ? 'good' : r.ok === false ? 'bad' : 'none'}`,
        el('p.pl-qlabel', qLabel),
        el('div.pl-res-ic', ok ? '✓' : r.ok === false ? '✗' : '⏱'),
        el('h1', ok ? T.correct : r.ok === false ? T.wrong : T.noAnswer),
        ok ? el('p.pl-points', T.points(r.pts)) : el('div.pl-correct-was', el('span', T.correctWas), shapeBadge(r.co, 36)),
        rankLine(s),
        el('p.pl-muted', s.q + 1 >= s.n ? T.waitFinal : T.waitNext));
    }
    case 'podium':
      return el('div.pl-final',
        el('h1', T.finished),
        el('div.pl-medal', s.k <= 3 ? ['🥇', '🥈', '🥉'][s.k - 1] : '🎉'),
        el('p.pl-place', T.place(s.k)),
        el('p.pl-points', `${fmt(s.sc)} ${T.score}`),
        el('p.pl-muted', T.rank(s.k, s.pl)),
        s.top && s.top.length ? el('ol.pl-top3', { 'aria-label': T.winners }, s.top.map(([nick, score], i) => el('li', { class: st.me && nick === st.me.nick ? 'me' : null },
          el('span.pl-top3-n', String(i + 1)), el('span.pl-top3-nick', nick), el('b', fmt(score))))) : null,
        el('button.pl-btn.ghost', { type: 'button', onclick: () => { forgetMe(st.pin); restart(false); } }, T.otherGame));
    default:
      return el('div.pl-card.pl-center', el('div.pl-spin.lg'));
  }
}

function rankLine(s) {
  return el('p.pl-rank', el('b', `${fmt(s.sc)} ${T.score}`), ' · ', T.rank(s.k, s.pl));
}

function viewClosed() {
  const reason = st.closed;
  if (reason === 'replaced') {
    return el('div.pl-card.pl-center', el('div.pl-res-ic.none', '⧉'), el('h1', T.replaced), el('p.pl-muted', T.replacedText),
      el('button.pl-btn', { type: 'button', onclick: continueHere }, T.continueHere));
  }
  if (reason === 'kicked') {
    return el('div.pl-card.pl-center', el('div.pl-res-ic.bad', '✗'), el('h1', T.kicked), el('p.pl-muted', T.kickedText),
      el('button.pl-btn', { type: 'button', onclick: () => restart(true) }, T.rejoin));
  }
  return el('div.pl-card.pl-center', el('div.pl-res-ic.none', '■'), el('h1', T.ended), el('p.pl-muted', T.endedText),
    el('button.pl-btn', { type: 'button', onclick: () => restart(false) }, T.otherGame));
}

function render() {
  const body = {
    pin: viewPin,
    checking: viewChecking,
    nick: viewNick,
    game: viewGame,
    closed: viewClosed,
  }[st.view]();
  const s = st.view === 'game' ? st.s : null;
  const res = s && s.res && (s.p === 'reveal' || s.p === 'leaderboard') ? ` pl-res-${s.res.ok ? 'good' : s.res.ok === false ? 'bad' : 'none'}` : '';
  root.className = `pl-view-${st.view}${s ? ` pl-phase-${s.p}` : ''}${res}`;
  root.replaceChildren(...topBar(), el('section.pl-stage', body));
  tick();
}

// Taymer: faqat sanoq va chiziq yangilanadi (butun sahifa emas)
function tick() {
  const s = st.s;
  if (!s || st.view !== 'game' || (s.p !== 'ready' && s.p !== 'question')) return;
  const left = Math.max(0, st.deadline - performance.now());
  for (const n of root.querySelectorAll('[data-countdown]')) {
    const v = s.p === 'ready' ? String(Math.max(1, Math.ceil(left / 1000))) : String(Math.ceil(left / 1000));
    if (n.textContent !== v) n.textContent = v;
  }
  const bar = root.querySelector('[data-bar]');
  if (bar && s.t) bar.style.transform = `scaleX(${Math.min(1, left / s.t)})`;
}
setInterval(tick, 200);

// ---------------------------------------------------------------------- start
function boot() {
  pruneStored();
  const pin = urlPin();
  if (pin) {
    st.pin = pin;
    const me = loadMe(pin);
    if (me && me.id && me.tok) {
      st.me = me;
      st.view = 'game';
    } else {
      st.view = 'checking';
      pending = { t: 'check', d: { pin } };
    }
  }
  render();
  connect();
}

boot();
