// O'quvchilar sahifasi (/play, /play/PIN): ro'yxatdan o'tmasdan — PIN, ism va avatar. Telefonlar uchun yengil:
// asosiy ilova (app.js, lib.js) yuklanmaydi, shakllar — inline SVG, avatarlar — emoji (rasm fayllari yo'q), serverdan
// faqat kichik xabarlar keladi (savol matni va variantlar o'qituvchi ekranida; bu yerda faqat rangli shakllar).
//
// Server — yagona manba: bosqich, vaqt, ball va javobni qabul qilish faqat serverda hal qilinadi. Sahifa sanoqni
// serverdan kelgan mutlaq vaqtlardan (ps/pe) va bir marta o'lchangan soatlar farqidan ko'rsatadi, xolos.
// Qurilmada faqat: shu o'yindagi joy (id + token, PIN bo'yicha, 12 soatdan keyin o'chiriladi) va oxirgi ism/avatar.
import {
  AVATARS, GAME_NAME, OCTAGON_RING, PHASES, PROTOCOL_VERSION, SHAPES, avatarEmoji, formatPin, octagonLoader, octagonMark,
  serverClock, shapeClass, shapeIcon,
} from './octagon/common.js';

const T = {
  pageTitle: `${GAME_NAME} — oʻyinga qoʻshilish`,
  pinLabel: 'Oʻyin PIN kodi',
  pinHint: 'Oʻqituvchi ekranidagi 6 xonali raqam',
  next: 'Davom etish',
  nickLabel: 'Ismingiz',
  nickHint: '1–20 belgi. Bu ism oʻqituvchi ekranida koʻrinadi.',
  nickPlaceholder: 'Masalan: Ali',
  avatarLabel: 'Avataringiz',
  avatarName: (name) => `Avatar: ${name}`,
  avatarNames: [
    'kuchukcha', 'mushuk', 'sichqon', 'olmaxon', 'quyon', 'boʻri', 'ayiq', 'panda', 'koala', 'yoʻlbars', 'ajdar', 'qurbaqa',
    'maymun', 'pingvin', 'toshbaqa', 'sakkizoyoq', 'delfin', 'kit', 'asalari', 'xonqizi', 'olma', 'tarvuz', 'qulupnay',
    'pitsa', 'futbol toʻpi', 'basketbol toʻpi', 'raketa', 'havo shari', 'gitara', 'kamalak',
  ],
  avatarChange: 'Avatarni almashtirish',
  avatarDone: 'Tayyor',
  join: 'Oʻyinga kirish',
  changePin: 'Boshqa PIN',
  pinBad: 'PIN — 6 xonali son (masalan: 482 913)',
  nickEmpty: 'Ismingizni kiriting',
  checking: 'Tekshirilmoqda…',
  reconnecting: 'Aloqa uzildi — qayta ulanmoqda…',
  lobbyTitle: 'Siz oʻyindasiz!',
  lobbyText: 'Ismingizni oʻqituvchi ekranida koʻryapsizmi? Oʻyin boshlanishini kuting…',
  topic: 'Mavzu',
  starting: 'Oʻyin boshlanmoqda…',
  question: (i, n) => `Savol ${i} / ${n}`,
  readTitle: 'Savolni oʻqing',
  readText: 'Savol oʻqituvchi ekranida. Javob tugmalari sanoq tugagach ochiladi.',
  chooseShape: 'Toʻgʻri javob shaklini bosing',
  sent: 'Javob yuborildi',
  sending: 'Yuborilmoqda…',
  locked: 'Javobingiz qabul qilindi',
  lockedTag: 'Qulflandi',
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
  placeShort: 'oʻrin',
  winners: 'Gʻoliblar',
  kicked: 'Oʻqituvchi sizni oʻyindan chiqardi',
  kickedText: 'Boshqa ism bilan qayta qoʻshilishingiz mumkin.',
  replaced: 'Oʻyin boshqa oynada ochildi',
  replacedText: 'Siz shu oʻyinga boshqa oyna yoki qurilmadan kirdingiz. Oʻyin oʻsha yerda davom etmoqda.',
  continueHere: 'Shu yerda davom etish',
  ended: 'Oʻyin yopildi',
  endedText: 'Oʻqituvchi oʻyinni yakunladi. Rahmat!',
  reloadTitle: 'Sayt yangilandi',
  reloadText: 'Davom etish uchun sahifani yangilang — oʻyindagi joyingiz va balingiz saqlanadi.',
  reload: 'Sahifani yangilash',
  rejoin: 'Qayta qoʻshilish',
  otherGame: 'Boshqa oʻyinga qoʻshilish',
  gone: 'Oldingi oʻyindagi joyingiz topilmadi — qaytadan qoʻshiling.',
  late: 'Vaqt tugadi — javob qabul qilinmadi',
  queued: 'Aloqa yoʻq — javob ulanish tiklanishi bilan yuboriladi',
  answer: (name) => `Javob: ${name}`,
};

// Qurilmada saqlanadigan ma'lumotlar (versiyali: eski formatdagi yozuvlar o'qilmaydi va o'chiriladi)
const STORE_V = 2;
const PIN_KEY = (pin) => `oct:${pin}`;       // {v, id, tok, nick, av, at} — faqat shu o'yinga qayta ulanish uchun
const LAST_KEY = 'oct:last';                 // {v, nick, av} — keyingi safar qulaylik uchun (maxfiy emas)
const PIN_RE = /^[1-9]\d{5}$/;               // serverdagi PIN_RE bilan bir xil
const ME_TTL = 12 * 3600 * 1000;             // saqlangan o'yinchi (ID + token) 12 soatdan keyin unutiladi
const root = document.getElementById('play');
document.title = T.pageTitle;

const st = {
  view: 'pin',          // pin | checking | nick | game | closed
  pin: '',
  me: null,             // {id, tok, nick, av}
  game: null,           // {tn — mavzu nomi, n — savollar soni}
  s: null,              // serverdan kelgan oxirgi holat (phase — nomi)
  av: null,             // qo'shilishda tanlangan avatar
  nickDraft: null,      // yozilayotgan ism: xato yoki qayta chizishda yo'qolmasin
  picking: false,       // lobbida avatar tanlash ochiq
  picked: null,         // {q, o} — tanlangan, server hali tasdiqlamagan javob
  queued: null,         // aloqa yo'qligida tanlangan javob
  late: false,
  error: '',
  closed: null,         // replaced | kicked | ended | reload
  status: 'connecting', // connecting | online | offline
};
const clock = serverClock();

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
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function urlPin() {
  const m = location.pathname.match(/^\/play\/(\d{6})\/?$/) || location.search.match(/[?&]pin=(\d{6})(?:&|$)/);
  return m && PIN_RE.test(m[1]) ? m[1] : '';
}

function store(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function saveMe(pin, me) {
  const value = { v: STORE_V, id: me.id, tok: me.tok, nick: me.nick, av: me.av, at: Date.now() };
  if (!store(PIN_KEY(pin), value)) {
    const secure = location.protocol === 'https:' ? '; secure' : '';
    document.cookie = `oct_${pin}=${encodeURIComponent(JSON.stringify(value))}; path=/play; max-age=${ME_TTL / 1000}; samesite=strict${secure}`;
  }
  store(LAST_KEY, { v: STORE_V, nick: me.nick, av: me.av });
}

function validMe(me) {
  return me && me.v === STORE_V && typeof me.id === 'string' && typeof me.tok === 'string' && Date.now() - (me.at || 0) < ME_TTL ? me : null;
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

/** Oxirgi ism va avatar (faqat qulaylik: maydon oldindan to'ldiriladi; server baribir hammasini tekshiradi). */
function loadLast() {
  try {
    const last = JSON.parse(localStorage.getItem(LAST_KEY) || 'null');
    if (last && last.v === STORE_V) {
      return {
        nick: typeof last.nick === 'string' ? last.nick.slice(0, 20) : '',
        av: Number.isInteger(last.av) && last.av >= 0 && last.av < AVATARS.length ? last.av : null,
      };
    }
  } catch {
    /* e'tiborsiz */
  }
  return { nick: '', av: null };
}

// Eski o'yinlardan qolgan ID/tokenlar (umumiy kompyuterlarda) qurilmada to'planib qolmasin
function pruneStored() {
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith('oct:') || key === LAST_KEY) continue;
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
    clock.request(send);
    if (st.me && st.pin) send('resume', { v: PROTOCOL_VERSION, pin: st.pin, id: st.me.id, tok: st.me.tok });
    else if (pending) send(pending.t, pending.d);
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

setInterval(() => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (Date.now() - lastMsgAt > 45000) ws.close(); // jim o'lgan ulanish
  else send('ping');
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
    case 'sync':
      clock.onSync(d);
      tick();
      break;
    case 'reload': // server protokoli yangilangan — eski sahifa jim buzilmasin
      showClosed('reload');
      break;
    case 'c':
      pending = null;
      st.error = '';
      st.view = 'nick';
      render();
      break;
    case 'w':
      pending = null;
      st.nickDraft = null;
      st.me = { id: d.id, tok: d.tok || (st.me && st.me.tok), nick: d.nick, av: d.av };
      st.game = { tn: d.tn, n: d.n };
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
      break; // noma'lum xabarlar e'tiborsiz
  }
}

function onState(s) {
  const prev = st.s;
  s.phase = PHASES[s.p] || 'lobby';
  const newQuestion = !prev || prev.q !== s.q || prev.phase !== s.phase;
  st.s = s;
  if (s.a != null) st.picked = null;            // server tasdiqladi
  if (newQuestion && s.phase === 'question_active' && s.a == null) {
    st.late = false;
    if (!(st.picked && st.picked.q === s.q)) st.picked = null;
  }
  if (s.phase !== 'lobby') st.picking = false;
  if (st.queued && s.phase === 'question_active' && s.q === st.queued.q && s.a == null) {
    send('a', { q: st.queued.q, o: st.queued.o });  // qayta ulanishdan keyin navbatdagi javob
    st.queued = null;
  }
  if (s.phase !== 'question_active') st.queued = null;
  if (st.view === 'game') render();
}

function onError(e) {
  if (['pin', 'rate', 'nick', 'taken', 'banned', 'full', 'ended', 'locked', 'avatar'].includes(e.c)) pending = null; // qayta yuborilmasin
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
    case 'avatar':
      if (!st.me) st.view = 'nick';
      st.error = e.m;
      render();
      break;
    case 'started':  // avatarni o'yin boshlangach almashtirib bo'lmaydi
      st.picking = false;
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
      pending = { t: 'check', d: { v: PROTOCOL_VERSION, pin: st.pin } };
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
    case 'early':  // savol hali ochilmagan — tanlov bekor, savol ochilganda qayta bosish mumkin
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
    if (!send('resume', { v: PROTOCOL_VERSION, pin, id: me.id, tok: me.tok })) reconnectNow();
    render();
    return;
  }
  st.view = 'checking';
  st.error = '';
  pending = { t: 'check', d: { v: PROTOCOL_VERSION, pin } };
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
  st.nickDraft = String(value || '');
  pending = { t: 'join', d: { v: PROTOCOL_VERSION, pin: st.pin, nick, av: st.av } };
  if (!send(pending.t, pending.d)) reconnectNow();
  render();
}

function pick(o) {
  const s = st.s;
  // Javob vaqtida yoki kechikkanmi — buni faqat server hal qiladi (mijoz soatiga qarab javob bloklanmaydi)
  if (!s || s.phase !== 'question_active' || s.a != null || st.picked) return;
  st.picked = { q: s.q, o };
  if (navigator.vibrate) navigator.vibrate(25);
  if (!send('a', { q: s.q, o })) st.queued = { q: s.q, o };
  render();
}

function changeAvatar(i) {
  st.picking = false;
  if (st.me && i !== st.me.av) send('av', { i }); // server tasdiqlaydi (w xabari) — shundan keyin ekranda almashadi
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
    pending = { t: 'check', d: { v: PROTOCOL_VERSION, pin: st.pin } };
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
  if (!st.me) pending = { t: 'check', d: { v: PROTOCOL_VERSION, pin: st.pin } };
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
const SVG_NS = 'http://www.w3.org/2000/svg';
const GLYPHS = {
  check: 'M5 12.5l4.5 4.5L19 7.5',
  cross: 'M6.5 6.5l11 11M17.5 6.5l-11 11',
  clock: 'M12 7v5l3 2M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18Z',
  lock: 'M7 11V8a5 5 0 0 1 10 0v3M5.5 11h13v9.5h-13Z',
  tabs: 'M3.5 9h11v11h-11ZM8.5 9V4h12v11h-6',
  refresh: 'M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5',
};

/** Chiziqli kichik belgi (inline SVG). */
function glyph(name, size = 24) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', 'pl-glyph');
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', GLYPHS[name]);
  svg.append(path);
  return svg;
}

/** Sakkizburchak sanoq halqasi (mavzu kirishi va o'qish vaqti uchun). */
function ring() {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('aria-hidden', 'true');
  for (const cls of ['track', 'bar']) {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', OCTAGON_RING);
    path.setAttribute('class', cls);
    path.setAttribute('pathLength', '100');
    if (cls === 'bar') path.setAttribute('data-ring', '');
    svg.append(path);
  }
  return svg;
}

/** Avatar (emoji matn sifatida, ekran o'quvchilari uchun yashirin — yonida ism bor). */
function avatar(index, cls = '') {
  return el(`span.pl-avatar${cls}`, { 'aria-hidden': 'true' }, avatarEmoji(index));
}

function avatarGrid(selected, onPick) {
  return el('div.pl-avatars', { role: 'radiogroup', 'aria-label': T.avatarLabel },
    AVATARS.map((emoji, i) => el(`button.pl-av${i === selected ? '.on' : ''}`, {
      type: 'button', role: 'radio', 'aria-checked': String(i === selected), 'aria-label': T.avatarName(T.avatarNames[i]),
      onclick: () => onPick(i),
    }, emoji)));
}

function topBar() {
  const left = st.pin && st.view !== 'pin'
    ? el('div.pl-pin', el('span', 'PIN'), el('b', formatPin(st.pin)))
    : el('div.pl-brand', octagonMark(26), el('span', GAME_NAME));
  const s = st.s;
  const me = st.me && st.view === 'game'
    ? el('div.pl-me', avatar(st.me.av), el('span.pl-nick', st.me.nick), s ? el('span.pl-score', fmt(s.sc), el('small', ` ${T.score}`)) : null)
    : null;
  const conn = el('div.pl-conn', { role: 'status' }, octagonLoader(true), T.reconnecting);
  conn.hidden = st.status === 'online' || st.view === 'closed' || st.view === 'pin';
  return [el('header.pl-top', left, me), conn];
}

function errorLine() {
  return el('p.pl-error', { role: 'alert', hidden: !st.error }, st.error || '');
}

function brand() {
  return el('div.pl-logo', octagonMark(52), el('span', GAME_NAME));
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
    brand(), el('h1', T.pinLabel), el('p.pl-muted', T.pinHint), input, errorLine(),
    el('button.pl-btn', { type: 'submit' }, T.next));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    submitPin(input.value);
  });
  setTimeout(() => input.focus(), 50);
  return form;
}

function viewChecking() {
  return el('div.pl-card.pl-center', octagonLoader(), el('p.pl-muted', T.checking), errorLine());
}

function viewNick() {
  const last = loadLast();
  if (st.av == null) st.av = last.av != null ? last.av : Math.floor(Math.random() * AVATARS.length); // tasodifiy tanlangan
  const input = el('input.pl-input', {
    type: 'text', maxlength: 20, autocomplete: 'nickname', autocapitalize: 'words', spellcheck: 'false',
    placeholder: T.nickPlaceholder, 'aria-label': T.nickLabel, value: st.nickDraft != null ? st.nickDraft : last.nick,
  });
  input.addEventListener('input', () => { st.nickDraft = input.value; });
  const waiting = pending && pending.t === 'join';
  const preview = el('span.pl-av-preview', { 'aria-hidden': 'true' }, avatarEmoji(st.av));
  const grid = avatarGrid(st.av, (i) => {
    st.av = i;
    preview.textContent = avatarEmoji(i);
    for (const b of grid.querySelectorAll('.pl-av')) {
      const on = b === grid.children[i];
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', String(on));
    }
  });
  const form = el('form.pl-card.pl-join', { novalidate: true },
    brand(),
    el('label.pl-field', el('span.pl-label', T.nickLabel), el('span.pl-nick-row', preview, input)),
    el('p.pl-muted.pl-hint', T.nickHint),
    el('div.pl-field', el('span.pl-label', T.avatarLabel), grid),
    errorLine(),
    el('button.pl-btn', { type: 'submit', disabled: waiting }, T.join),
    el('button.pl-link', { type: 'button', onclick: () => restart(false) }, T.changePin));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    submitNick(input.value);
  });
  setTimeout(() => {
    if (waiting) return;
    if (st.error) {  // rad etilgan ismni tuzatish oson bo'lsin
      input.focus();
      input.select();
    } else if (!input.value) {
      input.focus();
    }
  }, 50);
  return form;
}

/** Uzun mavzu nomi kichikroq shriftda — sanoq va tugmalar ekrandan chiqib ketmasin (maks. 120 belgi). */
function topicSize(name) {
  return name.length > 80 ? '.xlong' : name.length > 40 ? '.long' : '';
}

/** Tanlangan/to'g'ri javob belgisi: rang + shakl, sakkizburchak ramkada. */
function shapeBadge(o, size, extra = '') {
  return el(`span.pl-shape.oc-fill.${shapeClass(o)}${extra}`, { role: 'img', 'aria-label': SHAPES[o].name }, shapeIcon(o, size));
}

/** Sakkizburchak nishon (kutish, natija, podium). */
function badge(kind, content) {
  return el(`div.pl-badge.oc-oct.${kind}`, content);
}

function timerLine() {
  return el('div.pl-timer', el('div.pl-timer-track', el('div.pl-timer-bar', { 'data-bar': '' })), el('span.pl-timer-num', { 'data-countdown': '' }, ''));
}

function countdown() {
  return el('div.pl-count', ring(), el('span', { 'data-countdown': '' }, String(secondsLeft(st.s) || '')));
}

/** Javob shakllari: o'qish paytida ko'rinadi, lekin bosib bo'lmaydi; savol faol bo'lganda — tugmalar. */
function shapesGrid(s, active) {
  return el(`div.pl-grid.n${s.o}${active ? '' : '.wait'}`, { role: 'group', 'aria-label': T.chooseShape, 'aria-disabled': active ? null : 'true' },
    Array.from({ length: s.o }, (_, o) => el(`button.pl-answer.oc-fill.${shapeClass(o)}`, {
      type: 'button', 'aria-label': T.answer(SHAPES[o].name), disabled: !active, onclick: active ? () => pick(o) : null,
    }, shapeIcon(o, 120))));
}

function viewGame() {
  const s = st.s;
  if (!s) return el('div.pl-card.pl-center', octagonLoader());
  const total = st.game ? st.game.n : 0;
  const qLabel = s.q != null ? T.question(s.q + 1, total) : '';
  switch (s.phase) {
    case 'lobby':
      return el('div.pl-wait',
        el('div.pl-me-big', el('span.pl-avatar.xl', { 'aria-hidden': 'true' }, avatarEmoji(st.me && st.me.av))),
        el('h1', T.lobbyTitle),
        el('p.pl-big-nick', st.me ? st.me.nick : ''),
        el('p.pl-muted', T.lobbyText),
        st.picking
          ? el('div.pl-card.pl-picker', avatarGrid(st.me ? st.me.av : null, changeAvatar),
            el('button.pl-btn.ghost', { type: 'button', onclick: () => { st.picking = false; render(); } }, T.avatarDone))
          : el('button.pl-btn.ghost', { type: 'button', onclick: () => { st.picking = true; render(); } }, T.avatarChange));
    case 'topic_intro':
      return el('div.pl-intro',
        el('p.pl-intro-label', T.topic),
        el(`h1.pl-intro-topic${topicSize(st.game ? st.game.tn : '')}`, st.game ? st.game.tn : ''),
        countdown(),
        el('p.pl-muted', T.starting));
    case 'question_read':
      return el('div.pl-question.pl-reading',
        el('div.pl-qhead', el('span.pl-qlabel', qLabel), el('span.pl-read-count', countdown())),
        el('div.pl-read-note', el('h1', T.readTitle), el('p.pl-muted', T.readText)),
        shapesGrid(s, false));
    case 'question_active': {
      const chosen = s.a != null ? s.a : st.picked ? st.picked.o : null;
      if (chosen != null) {
        const confirmed = s.a != null;
        return el('div.pl-locked',
          el('div.pl-qhead', el('span.pl-qlabel', qLabel), timerLine()),
          el('div.pl-locked-card',
            shapeBadge(chosen, 96, '.big'),
            el(`p.pl-lock-tag${confirmed ? '.on' : ''}`, glyph(confirmed ? 'lock' : 'clock', 18), confirmed ? T.lockedTag : T.sending),
            el('h1', confirmed ? T.locked : T.sent),
            el('p.pl-muted', st.queued ? T.queued : T.waitOthers)));
      }
      if (st.late) {
        return el('div.pl-wait', el('p.pl-qlabel', qLabel), badge('none', glyph('clock', 52)), el('h1', T.late));
      }
      return el('div.pl-question', el('div.pl-qhead', el('span.pl-qlabel', qLabel), timerLine()), shapesGrid(s, true));
    }
    case 'question_result':
    case 'leaderboard': {
      const r = s.res;
      if (!r) return el('div.pl-wait', badge('wait', octagonLoader()), el('h1', T.joinedLate), rankLine(s));
      const ok = r.ok === true;
      const kind = ok ? 'good' : r.ok === false ? 'bad' : 'none';
      return el(`div.pl-result.${kind}`,
        el('p.pl-qlabel', qLabel),
        badge(kind, glyph(ok ? 'check' : r.ok === false ? 'cross' : 'clock', 56)),
        el('h1', ok ? T.correct : r.ok === false ? T.wrong : T.noAnswer),
        ok ? el('p.pl-points', T.points(r.pts)) : el('div.pl-correct-was', el('span', T.correctWas), shapeBadge(r.co, 34)),
        rankLine(s),
        el('p.pl-muted', s.q + 1 >= total ? T.waitFinal : T.waitNext));
    }
    case 'podium': {
      const medal = s.k === 1 ? 'gold' : s.k === 2 ? 'silver' : s.k === 3 ? 'bronze' : 'rest';
      return el('div.pl-final',
        el('h1', T.finished),
        el(`div.pl-medal.oc-oct.${medal}`, el('b', String(s.k)), el('small', T.placeShort)),
        el('p.pl-place', avatar(st.me && st.me.av), T.place(s.k)),
        el('p.pl-points', `${fmt(s.sc)} ${T.score}`),
        el('p.pl-muted', T.rank(s.k, s.pl)),
        s.top && s.top.length ? el('ol.pl-top3', { 'aria-label': T.winners }, s.top.map(([nick, score, av], i) => el('li', { class: st.me && nick === st.me.nick ? 'me' : null },
          el(`span.pl-top3-n.oc-oct.m${i + 1}`, String(i + 1)), avatar(av), el('span.pl-top3-nick', nick), el('b', fmt(score))))) : null,
        el('button.pl-btn.ghost', { type: 'button', onclick: () => { forgetMe(st.pin); restart(false); } }, T.otherGame));
    }
    default:
      return el('div.pl-card.pl-center', octagonLoader());
  }
}

function rankLine(s) {
  return el('p.pl-rank', avatar(st.me && st.me.av), el('b', `${fmt(s.sc)} ${T.score}`), el('span', T.rank(s.k, s.pl)));
}

function viewClosed() {
  const reason = st.closed;
  if (reason === 'reload') {
    return el('div.pl-card.pl-center', badge('wait', glyph('refresh', 48)), el('h1', T.reloadTitle), el('p.pl-muted', T.reloadText),
      el('button.pl-btn', { type: 'button', onclick: () => location.reload() }, T.reload));
  }
  if (reason === 'replaced') {
    return el('div.pl-card.pl-center', badge('wait', glyph('tabs', 48)), el('h1', T.replaced), el('p.pl-muted', T.replacedText),
      el('button.pl-btn', { type: 'button', onclick: continueHere }, T.continueHere));
  }
  if (reason === 'kicked') {
    return el('div.pl-card.pl-center', badge('bad', glyph('cross', 48)), el('h1', T.kicked), el('p.pl-muted', T.kickedText),
      el('button.pl-btn', { type: 'button', onclick: () => restart(true) }, T.rejoin));
  }
  return el('div.pl-card.pl-center', octagonMark(64), el('h1', T.ended), el('p.pl-muted', T.endedText),
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
  const res = s && s.res && (s.phase === 'question_result' || s.phase === 'leaderboard') ? ` pl-res-${s.res.ok ? 'good' : s.res.ok === false ? 'bad' : 'none'}` : '';
  root.className = `pl-view-${st.view}${s ? ` pl-phase-${s.phase}` : ''}${res}`;
  root.replaceChildren(...topBar(), el('section.pl-stage', body));
  tick();
}

// Taymer: serverdan kelgan mutlaq vaqtlar (ps/pe) va soatlar farqi bo'yicha — faqat ko'rsatish uchun
function msLeft(s) {
  return s && typeof s.pe === 'number' ? Math.max(0, s.pe - clock.now()) : 0;
}

function secondsLeft(s) {
  return s && typeof s.pe === 'number' ? Math.ceil(msLeft(s) / 1000) : 0;
}

function tick() {
  const s = st.s;
  if (!s || st.view !== 'game' || typeof s.pe !== 'number') return;
  const left = msLeft(s);
  const span = Math.max(1, s.pe - (s.ps || s.pe));
  const secs = String(s.phase === 'question_active' ? Math.ceil(left / 1000) : Math.max(1, Math.ceil(left / 1000)));
  for (const n of root.querySelectorAll('[data-countdown]')) {
    if (n.textContent !== secs) n.textContent = secs;
  }
  const bar = root.querySelector('[data-bar]');
  if (bar) {
    bar.style.transform = `scaleX(${Math.min(1, left / span)})`;
    bar.classList.toggle('low', left < 5000);
  }
  const ringBar = root.querySelector('[data-ring]');
  if (ringBar) ringBar.style.strokeDashoffset = String(100 - Math.min(1, left / span) * 100);
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
      pending = { t: 'check', d: { v: PROTOCOL_VERSION, pin } };
    }
  }
  render();
  connect();
}

boot();
