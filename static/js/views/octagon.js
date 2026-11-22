// Octagon — o'qituvchi ekrani (proyektor yoki telefon): sozlash -> lobbi (PIN + QR) -> mavzu -> savolni o'qish -> savol
// -> natija -> reyting -> ... -> podium. O'yin holati serverda: sahifa yangilansa yoki aloqa uzilsa, o'qituvchi o'sha
// o'yinni boshqarishda davom etadi. Sanoqlar serverdagi mutlaq vaqtlardan (phaseStart/phaseEnd) ko'rsatiladi.
import { h, icon, toast, confirmDialog, spinner, emptyState, beep, confetti } from '../lib.js';
import { api } from '../api.js';
import {
  GAME_NAME, OCTAGON_RING, PROTOCOL_VERSION, SHAPES, avatarEmoji, formatPin, octagonLoader, octagonMark, serverClock, shapeClass, shapeIcon,
} from '../octagon/common.js';

const T = {
  back: 'Oʻyinlar',
  lead: 'Jonli viktorina: savollar shu ekranda (proyektorda), oʻquvchilar esa telefonda PIN kod bilan qoʻshilib, rangli shakllarni bosib javob beradi.',
  setupTitle: 'Oʻyinni sozlash',
  topic: 'Mavzu',
  topicsLoading: 'Mavzular yuklanmoqda…',
  noTopics: 'Hozircha mavzular yoʻq',
  noTopicsHint: 'Avval «Boshqaruv» boʻlimida mavzu va savollar qoʻshing.',
  topicInfo: (n) => `${n} ta savol`,
  longInfo: (n) => `${n} ta savolda 4 tadan koʻp variant bor (oʻyinda koʻpi bilan 4 ta shakl).`,
  longTrim: 'Qisqartirish',
  longTrimHint: 'toʻgʻri javob + tasodifiy 3 ta notoʻgʻri variant',
  longSkip: 'Oʻyinga olmaslik',
  longSkipHint: 'faqat 2–4 variantli savollar beriladi',
  count: 'Savollar soni',
  all: (n) => `Hammasi (${n})`,
  time: 'Har bir savol uchun vaqt',
  custom: 'Boshqa',
  seconds: 'soniya',
  timeHint: (min, max) => `${min}–${max} soniya. Oʻyin boshlangach oʻzgartirib boʻlmaydi.`,
  timeBad: (min, max) => `Vaqt ${min}–${max} soniya oraligʻida boʻlsin`,
  shuffleQ: 'Savollar tartibini aralashtirish',
  shuffleA: 'Javob variantlarini aralashtirish',
  open: 'Lobbini ochish',
  chooseTopic: 'Mavzuni tanlang',
  activeTitle: 'Davom etayotgan oʻyinlar',
  resume: 'Davom ettirish',
  close: 'Yopish',
  closeConfirm: (pin) => `PIN ${formatPin(pin)} oʻyini yopiladi va oʻquvchilar undan chiqariladi.`,
  howTitle: 'Qanday oʻynaladi',
  how: [
    ['Lobbi', 'Ekranda PIN kod va QR kod chiqadi. Oʻquvchilar telefonda QR kodni skanerlaydi yoki sahifani ochib PIN kiritadi, soʻng ism va avatar tanlaydi — roʻyxatdan oʻtish shart emas.'],
    ['Boshlash', 'Hamma qoʻshilgach «Boshlash» tugmasini bosing: avval mavzu nomi hamma ekranda koʻrinadi. Siz bosmaguningizcha oʻyin boshlanmaydi; kechikkanlar oʻyin davomida ham qoʻshila oladi.'],
    ['Savol', 'Har bir savol avval bir necha soniya faqat shu ekranda oʻqiladi, soʻng javoblar ochiladi: oʻquvchilar telefonida rangli shakllar. Hamma javob bersa yoki vaqt tugasa, savol yopiladi.'],
    ['Ball', 'Toʻgʻri javob: 500 ball + tezlik uchun 500 gacha. 0,5 soniyada javob — 1000 ball, vaqt oxirida — 500. Notoʻgʻri yoki javobsiz — 0.'],
    ['Natijalar', 'Har savoldan keyin javoblar taqsimoti va eng yaxshi 5 talik, oxirida — podium.'],
  ],
  pin: 'PIN',
  joinAt: 'Qoʻshilish:',
  scan: 'Telefon kamerasi bilan skanerlang',
  stepOpen: 'Telefonda saytni oching',
  stepPin: 'PIN kodni kiriting',
  stepNick: 'Ismingizni yozing — tayyor!',
  backTitle: 'Octagon: yangi oʻyin sozlamalari',
  loading: 'Yuklanmoqda…',
  soundOn: 'Ovozni yoqish (standart — oʻchiq)',
  soundOff: 'Ovozni oʻchirish',
  waitingPlayers: 'Oʻquvchilar kutilmoqda…',
  playersJoined: (n) => `${n} ta oʻquvchi`,
  online: (n, total) => `${n}/${total} onlayn`,
  start: 'Boshlash',
  startNeedPlayers: 'Kamida bitta oʻquvchi qoʻshilishi kerak',
  kick: (nick) => `${nick} ni oʻyindan chiqarish`,
  offline: 'aloqa uzilgan',
  kickConfirm: (nick) => `«${nick}» oʻyindan chiqariladi. U boshqa ism bilan qayta qoʻshilishi mumkin.`,
  kickOk: 'Chiqarish',
  settingsLine: (n, t) => `${n} ta savol · har biriga ${t} soniya`,
  timeLocked: 'Vaqt oʻyin boshlangach qulflanadi',
  question: (i, n) => `Savol ${i} / ${n}`,
  starting: 'Oʻyin boshlanmoqda…',
  readHint: 'Savolni oʻqing — javoblar tez orada ochiladi',
  skipIntro: 'Oʻtkazib yuborish',
  openAnswers: 'Javoblarni hozir ochish',
  reloadTitle: 'Sayt yangilandi',
  reloadText: 'Oʻyinni boshqarishda davom etish uchun sahifani yangilang — oʻyin serverda saqlanadi.',
  reload: 'Sahifani yangilash',
  answered: (a, n) => `${a}/${n} javob`,
  skip: 'Savolni yakunlash',
  next: 'Keyingi',
  showBoard: 'Reyting',
  nextQuestion: 'Keyingi savol',
  finalResults: 'Yakuniy natijalar',
  correctCount: (c, n) => `${c} ta oʻquvchi toʻgʻri javob berdi (${n} ta javobdan)`,
  leaderboard: 'Eng yaxshi 5 talik',
  noPlayers: 'Hali oʻyinchi yoʻq',
  podium: 'Gʻoliblar',
  endedEarly: 'Oʻyin muddatidan oldin yakunlandi',
  played: (p, n) => `${p}/${n} ta savol oʻynaldi`,
  fullRanking: 'Barcha natijalar',
  correctShort: (c) => `${c} ta toʻgʻri`,
  newGame: 'Yangi oʻyin',
  toGames: 'Oʻyinlar paneli',
  end: 'Tugatish',
  endConfirmTitle: 'Oʻyinni tugatasizmi?',
  endConfirmLobby: 'Oʻyin bekor qilinadi va oʻquvchilar undan chiqariladi.',
  endConfirmGame: 'Hozirgacha toʻplangan ballar bilan yakuniy natijalar (podium) koʻrsatiladi.',
  endOk: 'Tugatish',
  fullscreen: 'Toʻliq ekran (F)',
  reconnecting: 'Aloqa uzildi — qayta ulanmoqda…',
  closedTitle: 'Oʻyin yopildi',
  closedText: 'Bu oʻyin endi mavjud emas.',
  notFound: 'Oʻyin topilmadi',
  keysHint: 'Probel yoki Enter — keyingi bosqich',
  lockOpen: 'Qoʻshilish ochiq',
  lockClosed: 'Qoʻshilish yopiq',
  lockTitle: (locked) => (locked ? 'Yangi oʻquvchilarga qoʻshilishga ruxsat berish' : 'Yangi oʻquvchilar qoʻshilishini toʻxtatish (qayta ulanish ishlayveradi)'),
  lockedNote: 'Qoʻshilish yopiq: yangi oʻquvchilar kira olmaydi. Oʻyindagilar qayta ulana oladi.',
  points: 'ball',
  qrAlt: (url) => `QR kod: ${url}`,
};

const PREFS_KEY = 'td-octagon-setup';
const TIME_PRESETS = [10, 20, 30, 60];
const COUNT_PRESETS = [5, 10, 15, 20, 30];

export function octagonView(root, params, ctx) {
  if (params.pin) return hostView(root, params.pin);
  return setupView(root, ctx);
}

function loadPrefs() {
  // count/time: null — serverdagi standart qiymatlar (limits.defaultQuestions / defaultTime) ishlatiladi
  const prefs = { topicId: null, count: null, time: null, shuffleQuestions: true, shuffleAnswers: true, longOptions: 'trim' };
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) || 'null');
    if (p && typeof p === 'object') Object.assign(prefs, p);
  } catch {
    /* e'tiborsiz */
  }
  return prefs;
}

function savePrefs(p) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* saqlab bo'lmasa ham ishlayveradi */
  }
}

function chips(values, selected, label, onPick) {
  const box = h('div.oct-chips', { role: 'radiogroup', 'aria-label': label });
  const paint = (current) => box.replaceChildren(...values.map(([v, text, disabled]) => h('button', {
    type: 'button',
    class: `oct-chip${v === current ? ' selected' : ''}`,
    role: 'radio',
    'aria-checked': String(v === current),
    disabled: !!disabled,
    onclick: () => {
      onPick(v);
      paint(v);
    },
  }, text)));
  paint(selected);
  return { el: box, paint };
}

// ================================================================= sozlash
function setupView(root, ctx) {
  const prefs = loadPrefs();
  let topics = [];
  let limits = { minTime: 5, maxTime: 120, defaultTime: 20, maxQuestions: 100, defaultQuestions: 10 }; // serverdan yangilanadi
  let alive = true;
  const topicSelect = h('select', { 'aria-label': T.topic }, h('option', { value: '' }, T.topicsLoading));
  const topicInfo = h('span.field-hint');
  const longBox = h('div.oct-long', { hidden: true });
  const countBox = h('div');
  const timeBox = h('div');
  const err = h('div.field-error', { role: 'alert' });
  const openBtn = h('button.btn.primary.lg.block', { type: 'button', onclick: create }, icon('play', 18), T.open);
  const activeBox = h('div');
  const shuffleQ = h('input', { type: 'checkbox', checked: prefs.shuffleQuestions !== false });
  const shuffleA = h('input', { type: 'checkbox', checked: prefs.shuffleAnswers !== false });

  const customTime = h('input.oct-custom-time', { type: 'number', min: 5, max: 120, step: 1, inputmode: 'numeric', 'aria-label': `${T.time} (${T.seconds})` });

  function currentTopic() {
    return topics.find((t) => t.id === Number(topicSelect.value)) || null;
  }

  function paintTopic() {
    const t = currentTopic();
    topicInfo.textContent = t ? T.topicInfo(t.questionCount) : '';
    if (t && t.longCount > 0) {
      const group = `long-${Math.random().toString(36).slice(2)}`;
      const radio = (value, title, hint) => {
        const input = h('input', { type: 'radio', name: group, value, checked: prefs.longOptions === value });
        input.addEventListener('change', () => {
          prefs.longOptions = value;
          paintCount();
        });
        return h('label.check', input, h('span', h('b', title), h('span.muted', ` — ${hint}`)));
      };
      longBox.replaceChildren(
        h('div.alert.info', icon('alert', 18), h('span', T.longInfo(t.longCount))),
        radio('trim', T.longTrim, T.longTrimHint),
        radio('skip', T.longSkip, T.longSkipHint));
      longBox.hidden = false;
    } else {
      longBox.hidden = true;
      longBox.replaceChildren();
    }
    paintCount();
  }

  function available() {
    const t = currentTopic();
    if (!t) return 0;
    return prefs.longOptions === 'skip' ? t.questionCount - t.longCount : t.questionCount;
  }

  function paintCount() {
    const n = Math.min(available(), limits.maxQuestions);
    const values = COUNT_PRESETS.filter((v) => v < n).map((v) => [v, String(v)]);
    values.push([n, T.all(n)]);
    if (!values.some(([v]) => v === prefs.count)) prefs.count = Math.min(limits.defaultQuestions, n) || n;
    countBox.replaceChildren(h('label.field', h('span.field-label', T.count),
      chips(values, prefs.count, T.count, (v) => {
        prefs.count = v;
      }).el));
    openBtn.disabled = !n;
  }

  function paintTime() {
    if (!Number.isInteger(prefs.time)) prefs.time = limits.defaultTime;
    const isPreset = TIME_PRESETS.includes(prefs.time);
    customTime.value = isPreset ? '' : String(prefs.time);
    const presets = chips(TIME_PRESETS.map((v) => [v, `${v} s`]), isPreset ? prefs.time : null, T.time, (v) => {
      prefs.time = v;
      customTime.value = '';
    });
    customTime.oninput = () => {
      const v = Number(customTime.value);
      if (Number.isInteger(v)) {
        prefs.time = v;
        presets.paint(TIME_PRESETS.includes(v) ? v : null);
      }
    };
    timeBox.replaceChildren(h('div.field',
      h('span.field-label', T.time),
      h('div.oct-time-row', presets.el, h('label.oct-custom', h('span.small.muted', T.custom), customTime, h('span.small.muted', 's'))),
      h('span.field-hint', T.timeHint(limits.minTime, limits.maxTime))));
  }

  topicSelect.addEventListener('change', () => {
    prefs.topicId = Number(topicSelect.value) || null;
    paintTopic();
  });

  const setupCard = h('div.card.oct-setup',
    h('h2.card-title', icon('sliders', 18), T.setupTitle),
    h('label.field', h('span.field-label', T.topic), topicSelect, topicInfo),
    longBox,
    countBox,
    timeBox,
    h('label.check', shuffleQ, h('span', T.shuffleQ)),
    h('label.check', shuffleA, h('span', T.shuffleA)),
    err,
    openBtn);

  const howCard = h('div.card.oct-how',
    h('h2.card-title', icon('help', 18), T.howTitle),
    h('ol.bp-steps', T.how.map(([title, text], i) => h('li', h('span.bp-step-n', String(i + 1)), h('div', h('b', title), h('p.muted', text))))),
    h('div.oct-art.sm', SHAPES.map((s, i) => h(`span.oc-fill.${shapeClass(i)}`, { role: 'img', 'aria-label': s.name, title: s.name }, shapeIcon(i, 22)))));

  root.append(h('section.screen.oct-lobby-page',
    h('a.back-link.games-back', { href: '#/games' }, icon('left', 16), T.back),
    h('div.page-head.oct-head', octagonMark(48), h('div', h('h1', GAME_NAME), h('p.muted', T.lead))),
    activeBox,
    h('div.bp-lobby-grid', setupCard, howCard)));
  paintTime();

  async function loadTopics() {
    try {
      const data = await api('/api/octagon/topics');
      topics = data.topics;
      limits = data.limits || limits;
    } catch (e) {
      if (!alive) return;
      topicSelect.replaceChildren(h('option', { value: '' }, e.message));
      return;
    }
    if (!alive) return;
    customTime.min = limits.minTime;
    customTime.max = limits.maxTime;
    paintTime();
    if (!topics.length) {
      topicSelect.replaceChildren(h('option', { value: '' }, T.noTopics));
      topicSelect.disabled = true;
      topicInfo.textContent = T.noTopicsHint;
      openBtn.disabled = true;
      return;
    }
    const keep = topics.some((t) => t.id === prefs.topicId) ? prefs.topicId : topics[0].id;
    topicSelect.disabled = false;
    topicSelect.replaceChildren(...topics.map((t) => h('option', { value: String(t.id) }, `${t.name} (${t.questionCount})`)));
    topicSelect.value = String(keep);
    prefs.topicId = keep;
    paintTopic();
  }

  async function loadActive() {
    let games;
    try {
      games = (await api('/api/octagon/games')).games;
    } catch {
      return;
    }
    if (!alive) return;
    const active = games.filter((g) => g.phase !== 'podium');
    activeBox.replaceChildren(active.length ? h('div.card.games-active',
      h('h2.card-title', icon('activity', 18), T.activeTitle),
      h('ul.adm-list', active.map((g) => h('li.adm-row',
        h('span.adm-act-ic', icon('octagon', 18)),
        h('div.adm-row-main',
          h('div.adm-row-title', `PIN ${formatPin(g.pin)} · ${g.topicName}`),
          h('div.adm-row-sub', `${T.playersJoined(g.players)} · ${g.index >= 0 ? T.question(g.index + 1, g.total) : 'lobbi'}`)),
        h('a.btn.primary.sm', { href: `#/games/octagon/${g.pin}` }, icon('play', 14), T.resume),
        h('button.icon-btn.danger', { type: 'button', title: T.close, 'aria-label': `${T.close}: ${g.pin}`, onclick: () => closeGame(g) }, icon('x', 16)))))) : '');
  }

  async function closeGame(g) {
    if (!(await confirmDialog({ title: T.close, message: T.closeConfirm(g.pin), okText: T.close, danger: true }))) return;
    try {
      await api(`/api/octagon/games/${g.pin}`, { method: 'DELETE' });
    } catch (e) {
      toast(e.message, 'error');
    }
    loadActive();
  }

  async function create() {
    err.textContent = '';
    const topic = currentTopic();
    if (!topic) {
      err.textContent = T.chooseTopic;
      topicSelect.focus();
      return;
    }
    const time = Number(customTime.value || prefs.time);
    if (!Number.isInteger(time) || time < limits.minTime || time > limits.maxTime) {
      err.textContent = T.timeBad(limits.minTime, limits.maxTime);
      customTime.focus();
      return;
    }
    prefs.time = time;
    prefs.shuffleQuestions = shuffleQ.checked;
    prefs.shuffleAnswers = shuffleA.checked;
    savePrefs(prefs);
    openBtn.disabled = true;
    try {
      const res = await api('/api/octagon/games', {
        method: 'POST',
        body: {
          topicId: topic.id,
          timeLimit: time,
          questionCount: prefs.count,
          shuffleQuestions: prefs.shuffleQuestions,
          shuffleAnswers: prefs.shuffleAnswers,
          longOptions: prefs.longOptions,
        },
      });
      ctx.navigate(`/games/octagon/${res.game.pin}`);
    } catch (e) {
      err.textContent = e.message;
      openBtn.disabled = false;
    }
  }

  loadTopics();
  loadActive();
  return () => {
    alive = false;
  };
}

// ========================================================== o'qituvchi ekrani
function hostSocket(pin, clock, { onMessage, onStatus }) {
  let ws = null;
  let retry = 0;
  let timer = 0;
  let stopped = false;
  function open() {
    clearTimeout(timer);
    if (ws || stopped) return;
    const sock = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/octagon`);
    ws = sock;
    sock.onopen = () => {
      retry = 0;
      onStatus('online');
      clock.request((t, d) => sock.send(JSON.stringify({ t, d })));
      sock.send(JSON.stringify({ t: 'host', d: { v: PROTOCOL_VERSION, pin } }));
    };
    sock.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg && typeof msg.t === 'string') onMessage(msg.t, msg.d || {});
    };
    sock.onclose = () => {
      if (ws !== sock) return;
      ws = null;
      if (stopped) return;
      onStatus('offline');
      timer = setTimeout(open, Math.min(5000, 400 * 2 ** retry) + Math.random() * 300);
      retry = Math.min(retry + 1, 6);
    };
  }
  const reconnect = () => {
    if (!document.hidden && !ws && !stopped) {
      retry = 0;
      open();
    }
  };
  const pingTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send('{"t":"ping","d":{}}');
  }, 20000);
  document.addEventListener('visibilitychange', reconnect);
  window.addEventListener('online', reconnect);
  open();
  return {
    send(t, d = {}) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ t, d }));
        return true;
      }
      toast(T.reconnecting, 'warning');
      return false;
    },
    close() {
      stopped = true;
      clearTimeout(timer);
      clearInterval(pingTimer);
      document.removeEventListener('visibilitychange', reconnect);
      window.removeEventListener('online', reconnect);
      if (ws) {
        const s = ws;
        ws = null;
        s.close();
      }
    },
  };
}

function qrSvg(qr, url) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${qr.size} ${qr.size}`);
  svg.setAttribute('shape-rendering', 'crispEdges');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', T.qrAlt(url));
  const bg = document.createElementNS(ns, 'rect');
  bg.setAttribute('width', String(qr.size));
  bg.setAttribute('height', String(qr.size));
  bg.setAttribute('class', 'oct-qr-bg');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', qr.path);
  path.setAttribute('class', 'oct-qr-dots');
  svg.append(bg, path);
  return svg;
}

/** Sakkizburchak taymer halqasi: yo'l uzunligi 100, qolgan vaqt — chiziq uzunligi. */
function octRing(extra = '') {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('aria-hidden', 'true');
  for (const cls of ['track', 'bar']) {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', OCTAGON_RING);
    path.setAttribute('pathLength', '100');
    path.setAttribute('class', cls);
    svg.append(path);
  }
  return h(`div.oct-ring${extra}`, { 'data-ring': '' }, svg, h('span', { 'data-countdown': '' }, ''));
}

function fmt(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

const SOUND_KEY = 'td-octagon-sound';

function soundOn() {
  try {
    return localStorage.getItem(SOUND_KEY) === 'on'; // standart — ovozsiz
  } catch {
    return false;
  }
}

const HOST_STATIC = ['qr', 'joinUrl', 'joinBase', 'topicName', 'createdAt']; // app/octagon.py: HOST_STATIC

function pick(obj, keys) {
  const out = {};
  for (const k of keys) if (obj[k] !== undefined) out[k] = obj[k];
  return out;
}

function hostView(root, pinParam) {
  const pin = String(pinParam).replace(/\D/g, '');
  const clock = serverClock();
  let game = null;
  let lastPhaseKey = '';
  let lastBoard = '';
  let alive = true;
  let sound = soundOn();
  root.classList.add('wide');

  const pinBox = h('div.oct-pin', h('span', T.pin), h('b', formatPin(pin)));
  const joinLine = h('div.oct-join-line');
  const countPill = h('span.oct-pill.oct-count', icon('users', 16), h('b', '0'));
  const connPill = h('span.oct-pill.warn', { hidden: true, role: 'status' }, icon('wifiOff', 14), h('span.hide-sm', T.reconnecting));
  const lockBtn = h('button.oct-tool.oct-lock', { type: 'button', 'aria-pressed': 'false', onclick: () => game && act('lock', { locked: !game.locked }) });
  const soundBtn = h('button.oct-tool.oct-sound', { type: 'button', onclick: toggleSound });
  const fsBtn = h('button.oct-tool.oct-fs', { type: 'button', title: T.fullscreen, 'aria-label': T.fullscreen, onclick: toggleFullscreen }, icon('maximize', 18));
  const endBtn = h('button.oct-tool.oct-end', { type: 'button', onclick: endGame }, icon('flag', 16), h('span.hide-sm', T.end));
  const bar = h('div.oct-bar',
    h('a.oct-back', { href: '#/games/octagon', title: T.backTitle, 'aria-label': T.backTitle }, icon('left', 18), octagonMark(28), h('span.hide-sm', GAME_NAME)),
    h('div.oct-bar-pin', pinBox, joinLine),
    h('div.oct-bar-tools', connPill, countPill, lockBtn, soundBtn, fsBtn, endBtn));
  const stage = h('div.oct-stage', h('div.oct-loading', octagonLoader(), h('span', T.loading)));
  const section = h('section.screen.oct-host', bar, stage);
  root.append(section);
  paintSound();

  const sock = hostSocket(pin, clock, {
    onStatus(s) {
      connPill.hidden = s === 'online';
    },
    onMessage(t, d) {
      if (!alive) return;
      if (t === 'h') {
        render(d);
      } else if (t === 'sync') {
        clock.onSync(d);
        tick();
      } else if (t === 'reload') { // server yangilangan: eski sahifa jim buzilmasin
        sock.close();
        stage.replaceChildren(emptyState('refresh', T.reloadTitle, T.reloadText,
          h('button.btn.primary', { type: 'button', onclick: () => location.reload() }, icon('refresh', 16), T.reload)));
      } else if (t === 'closed') {
        sock.close();
        showClosed();
      } else if (t === 'e') {
        if (d.status === 404 || d.status === 403) {
          sock.close();
          stage.replaceChildren(emptyState('alert', T.notFound, d.m, h('a.btn.primary', { href: '#/games/octagon' }, T.newGame)));
          endBtn.hidden = true;
          lockBtn.hidden = true;
        } else {
          toast(d.m, 'error');
        }
      }
    },
  });

  function act(action, extra = {}) {
    if (!game) return;
    sock.send(action, { phase: game.phase, q: game.index, ...extra });
  }

  function play(kind) {
    if (sound) beep(kind, true); // Octagon ovozi alohida, standart — o'chiq
  }

  function paintSound() {
    soundBtn.setAttribute('aria-pressed', String(sound));
    soundBtn.title = sound ? T.soundOff : T.soundOn;
    soundBtn.setAttribute('aria-label', soundBtn.title);
    soundBtn.replaceChildren(icon(sound ? 'volume' : 'mute', 18));
  }

  function toggleSound() {
    sound = !sound;
    try {
      localStorage.setItem(SOUND_KEY, sound ? 'on' : 'off');
    } catch {
      /* saqlab bo'lmasa ham ishlaydi */
    }
    paintSound();
    play('tick');
  }

  function render(next) {
    const prev = game;
    // yangilanishlarda o'zgarmas maydonlar (QR, havola, mavzu nomi) yuborilmaydi — oldingisidan olinadi
    const g = prev && prev.pin === next.pin ? { ...pick(prev, HOST_STATIC), ...next } : next;
    game = g;
    countPill.querySelector('b').textContent = String(g.playerCount);
    countPill.title = T.online(g.connectedCount, g.playerCount);
    joinLine.replaceChildren(h('span', T.joinAt), h('b', g.joinBase.replace(/^https?:\/\//, '') + '/play'));
    endBtn.hidden = g.phase === 'podium';
    paintLock(g);
    const key = `${g.phase}:${g.index}`;
    section.className = `screen oct-host phase-${g.phase}`;
    if (key === lastPhaseKey && prev) {
      update(g); // bosqich o'zgarmagan: faqat sonlarni yangilaymiz (lobbida — o'yinchilar ro'yxati)
      return;
    }
    lastPhaseKey = key;
    lastBoard = boardKey(g);
    if (g.phase === 'question_active') play('tick');
    if (g.phase === 'podium') {
      play('win');
      confetti(themeColors());
    }
    stage.replaceChildren(({
      lobby: lobbyScreen,
      topic_intro: introScreen,
      question_read: readScreen,
      question_active: questionScreen,
      question_result: revealScreen,
      leaderboard: boardScreen,
      podium: podiumScreen,
    }[g.phase] || (() => spinner()))(g));
    tick();
  }

  function paintLock(g) {
    lockBtn.hidden = g.phase === 'podium';
    lockBtn.classList.toggle('on', !!g.locked);
    lockBtn.setAttribute('aria-pressed', String(!!g.locked));
    lockBtn.title = T.lockTitle(!!g.locked);
    lockBtn.replaceChildren(icon(g.locked ? 'lock' : 'unlock', 16), h('span.hide-sm', g.locked ? T.lockClosed : T.lockOpen));
    const note = stage.querySelector('[data-locked]');
    if (note) note.hidden = !g.locked;
  }

  function update(g) {
    if (g.phase === 'lobby') {
      const list = stage.querySelector('[data-players]');
      if (list) list.replaceWith(playersList(g));
      const startBtn = stage.querySelector('[data-start]');
      if (startBtn) startBtn.disabled = !g.playerCount;
      const hint = stage.querySelector('[data-start-hint]');
      if (hint) hint.hidden = !!g.playerCount;
      const count = stage.querySelector('[data-count]');
      if (count) count.textContent = g.playerCount ? T.playersJoined(g.playerCount) : T.waitingPlayers;
      const timeRow = stage.querySelector('[data-time]');
      if (timeRow) timeRow.replaceWith(lobbyTime(g));
    } else if (g.phase === 'question_active') {
      const a = stage.querySelector('[data-answered]');
      if (a) a.textContent = T.answered(g.answered, g.connectedCount || g.playerCount);
    } else if ((g.phase === 'podium' || g.phase === 'leaderboard') && boardKey(g) !== lastBoard) {
      // faqat reyting o'zgarganda (kech qo'shilish, chiqarish) qayta chiziladi — animatsiyalar qaytadan o'ynamasin
      lastBoard = boardKey(g);
      stage.replaceChildren(g.phase === 'podium' ? podiumScreen(g) : boardScreen(g));
    }
  }

  function boardKey(g) {
    return JSON.stringify((g.ranking || g.leaderboard || []).map((r) => [r.id, r.score, r.rank]));
  }

  // ----------------------------------------------------------------- lobbi
  function lobbyScreen(g) {
    const site = g.joinBase.replace(/^https?:\/\//, '') + '/play';
    const startBtn = h('button.btn.accent.lg.oct-start', { type: 'button', 'data-start': '', disabled: !g.playerCount, onclick: () => act('start') },
      icon('play', 20), T.start);
    return h('div.oct-lobby',
      h('div.oct-join',
        h('div.oct-join-steps',
          h('p.oct-step-label', h('span.oct-step-n.oc-oct', '1'), T.stepOpen),
          h('p.oct-url', h('b', site)),
          h('p.oct-step-label', h('span.oct-step-n.oc-oct', '2'), T.stepPin),
          h('div.oct-hero-pin', { 'aria-label': `PIN ${formatPin(g.pin)}` }, formatPin(g.pin)),
          h('p.oct-step-label', h('span.oct-step-n.oc-oct', '3'), T.stepNick)),
        h('div.oct-qr-box',
          h('div.oct-qr', qrSvg(g.qr, g.joinUrl)),
          h('p.oct-scan', icon('maximize', 16), T.scan))),
      h('div.oct-players-card',
        h('div.oct-players-head',
          h('h2', { 'data-count': '' }, g.playerCount ? T.playersJoined(g.playerCount) : T.waitingPlayers),
          h('span.oct-topic', g.topicName)),
        playersList(g),
        h('p.oct-locked-note', { 'data-locked': '', hidden: !g.locked }, icon('lock', 16), h('span', T.lockedNote)),
        h('div.oct-lobby-foot',
          lobbyTime(g),
          h('div.oct-start-box', startBtn, h('span.small.oct-dim', { 'data-start-hint': '', hidden: !!g.playerCount }, T.startNeedPlayers)))));
  }

  function playersList(g) {
    if (!g.players || !g.players.length) {
      return h('div.oct-players.empty', { 'data-players': '' }, octagonLoader(), h('span', T.waitingPlayers));
    }
    return h('ul.oct-players', { 'data-players': '' }, g.players.map((p, i) => h(`li.oct-player${p.online ? '' : '.off'}`,
      { title: p.online ? null : `${p.nick} — ${T.offline}` },
      h(`span.oct-avatar.oc-oct.${shapeClass(i % SHAPES.length)}`, { 'aria-hidden': 'true' }, avatarEmoji(p.av)),
      p.online ? null : h('span.oct-off', { role: 'img', 'aria-label': T.offline }, icon('wifiOff', 14)),
      h('span.oct-player-nick', p.nick),
      h('button.oct-kick', { type: 'button', title: T.kick(p.nick), 'aria-label': T.kick(p.nick), onclick: () => kick(p) }, icon('x', 16)))));
  }

  function lobbyTime(g) {
    const box = h('div.oct-lobby-time', { 'data-time': '' },
      h('span.small.oct-dim', T.settingsLine(g.total, g.timeLimit)),
      chips(TIME_PRESETS.map((v) => [v, `${v} s`]), TIME_PRESETS.includes(g.timeLimit) ? g.timeLimit : null, T.time, (v) => act('settings', { timeLimit: v })).el);
    box.title = T.timeLocked;
    return box;
  }

  async function kick(p) {
    if (await confirmDialog({ title: T.kickOk, message: T.kickConfirm(p.nick), okText: T.kickOk, danger: true })) act('kick', { id: p.id });
  }

  // ------------------------------------------------------- savol bosqichlari
  function qHead(g, extra) {
    return h('div.oct-qhead',
      h('span.oct-qnum', T.question(g.index + 1, g.total)),
      extra || null);
  }

  function introScreen(g) {
    return h('div.oct-intro',
      h('p.oct-intro-label', T.topic),
      h('h1.oct-intro-topic', { class: g.topicName.length > 80 ? 'xlong' : g.topicName.length > 40 ? 'long' : null }, g.topicName),
      octRing('.big'),
      h('p.oct-dim', `${T.starting} · ${T.settingsLine(g.total, g.timeLimit)}`),
      h('div.oct-actions', h('button.btn.ghost', { type: 'button', onclick: () => act('skip') }, icon('skip', 16), T.skipIntro)));
  }

  function readScreen(g) {
    return h('div.oct-ready',
      qHead(g),
      h('div.oct-qtext', { class: g.question.text.length > 160 ? 'long' : null }, g.question.text),
      octRing('.big'),
      h('p.oct-dim', T.readHint),
      h('div.oct-actions', h('button.btn.ghost', { type: 'button', onclick: () => act('skip') }, icon('skip', 16), T.openAnswers)));
  }

  function tiles(g, reveal) {
    const total = Math.max(1, ...(g.counts || [0]));
    return h(`div.oct-tiles.n${g.question.options.length}`, g.question.options.map((text, i) => {
      const correct = reveal && i === g.question.correct;
      return h(`div.oct-tile.oc-fill.${shapeClass(i)}${reveal ? (correct ? '.correct' : '.dim') : ''}`,
        h('span.oct-tile-shape.oc-oct', { role: 'img', 'aria-label': SHAPES[i].name }, shapeIcon(i, 34)),
        h('span.oct-tile-text', text),
        reveal ? h('span.oct-tile-count', correct ? icon('check', 22) : null, h('b', String(g.counts[i]))) : null,
        reveal ? h('span.oct-tile-bar', { style: { transform: `scaleX(${g.counts[i] / total})` } }) : null);
    }));
  }

  function questionScreen(g) {
    return h('div.oct-question',
      qHead(g, h('span.oct-answered', { 'data-answered': '' }, T.answered(g.answered, g.connectedCount || g.playerCount))),
      h('div.oct-qrow',
        h('div.oct-qtext', { class: g.question.text.length > 160 ? 'long' : null }, g.question.text),
        octRing()),
      tiles(g, false),
      h('div.oct-actions', h('button.btn.ghost', { type: 'button', onclick: () => act('skip') }, icon('skip', 16), T.skip)));
  }

  function revealScreen(g) {
    return h('div.oct-reveal',
      qHead(g, h('span.oct-answered', T.correctCount(g.correctCount, g.answered))),
      h('div.oct-qtext.small', g.question.text),
      tiles(g, true),
      h('div.oct-actions', h('button.btn.primary.lg', { type: 'button', onclick: () => act('next') }, T.showBoard, icon('right', 18)),
        h('span.small.oct-dim.hide-sm', T.keysHint)));
  }

  function rankBadge(rank) {
    return h(`span.oct-rank-n.oc-oct${rank <= 3 ? `.m${rank}` : ''}`, String(rank));
  }

  function boardScreen(g) {
    const last = g.index + 1 >= g.total;
    return h('div.oct-board',
      qHead(g),
      h('h2.oct-board-title', octagonMark(34), T.leaderboard),
      g.leaderboard.length
        ? h('ol.oct-rank', g.leaderboard.map((r) => h('li',
          rankBadge(r.rank),
          h('span.oct-rank-av', { 'aria-hidden': 'true' }, avatarEmoji(r.av)),
          h('span.oct-rank-nick', r.nick),
          r.gained ? h('span.oct-rank-gain', `+${fmt(r.gained)}`) : null,
          h('b.oct-rank-score', fmt(r.score)))))
        : h('p.oct-dim', T.noPlayers),
      h('div.oct-actions', h('button.btn.primary.lg', { type: 'button', onclick: () => act('next') }, last ? T.finalResults : T.nextQuestion, icon('right', 18)),
        h('span.small.oct-dim.hide-sm', T.keysHint)));
  }

  function podiumScreen(g) {
    const top = g.ranking.slice(0, 3);
    const order = [1, 0, 2].filter((i) => top[i]);
    return h('div.oct-podium-wrap',
      h('h2.oct-board-title', octagonMark(38), T.podium),
      g.endedEarly ? h('p.oct-dim.center', `${T.endedEarly} · ${T.played(g.played, g.total)}`) : null,
      top.length ? h('div.oct-podium', order.map((i) => h(`div.oct-step.place-${i + 1}`,
        h(`div.oct-medal.oc-oct.m${i + 1}`, h('b', String(i + 1))),
        h('span.oct-step-av', { 'aria-hidden': 'true' }, avatarEmoji(top[i].av)),
        h('span.oct-step-nick', top[i].nick),
        h('span.oct-step-score', `${fmt(top[i].score)} ${T.points}`),
        h('div.oct-step-block')))) : h('p.oct-dim.center', T.noPlayers),
      g.ranking.length > 3 ? h('details.oct-all', { open: g.ranking.length <= 12 },
        h('summary', T.fullRanking),
        h('ol.oct-rank.compact', g.ranking.map((r) => h('li',
          rankBadge(r.rank),
          h('span.oct-rank-av', { 'aria-hidden': 'true' }, avatarEmoji(r.av)),
          h('span.oct-rank-nick', r.nick),
          h('span.small.oct-dim', T.correctShort(r.correct)),
          h('b.oct-rank-score', fmt(r.score)))))) : null,
      h('div.oct-actions',
        h('a.btn.primary', { href: '#/games/octagon' }, icon('sparkles', 16), T.newGame),
        h('a.btn.ghost', { href: '#/games' }, T.toGames)));
  }

  function showClosed() {
    lastPhaseKey = '';
    game = null;
    endBtn.hidden = true;
    lockBtn.hidden = true;
    stage.replaceChildren(emptyState('flag', T.closedTitle, T.closedText, h('a.btn.primary', { href: '#/games/octagon' }, T.newGame)));
  }

  async function endGame() {
    if (!game) return;
    const ok = await confirmDialog({
      title: T.endConfirmTitle,
      message: game.phase === 'lobby' ? T.endConfirmLobby : T.endConfirmGame,
      okText: T.endOk,
      danger: true,
    });
    if (ok) act('end');
  }

  // -------------------------------------------------------------- taymer
  function tick() {
    if (!game || typeof game.phaseEnd !== 'number') return;
    const left = Math.max(0, game.phaseEnd - clock.now());
    const span = Math.max(1, game.phaseEnd - (game.phaseStart || game.phaseEnd));
    const active = game.phase === 'question_active';
    const secs = active ? Math.ceil(left / 1000) : Math.max(1, Math.ceil(left / 1000));
    for (const n of stage.querySelectorAll('[data-countdown]')) {
      if (n.textContent !== String(secs)) n.textContent = String(secs);
    }
    const ring = stage.querySelector('[data-ring]');
    if (ring) {
      const p = Math.min(1, left / span);
      ring.querySelector('.bar').style.strokeDashoffset = String(100 - p * 100);
      ring.classList.toggle('low', active && left < 5000);
    }
  }
  const tickTimer = setInterval(tick, 200);

  // ------------------------------------------------- to'liq ekran, klaviatura
  function setImmersive(on) {
    document.body.classList.toggle('oct-immersive', on);
    fsBtn.replaceChildren(icon(on ? 'minimize' : 'maximize', 18));
  }

  async function toggleFullscreen() {
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => {});
      return;
    }
    if (document.body.classList.contains('oct-immersive')) {
      setImmersive(false);
      return;
    }
    setImmersive(true);
    if (document.fullscreenEnabled) {
      try {
        await document.documentElement.requestFullscreen({ navigationUI: 'hide' });
      } catch {
        /* ruxsat bo'lmasa ham sarlavhasiz rejim ishlaydi */
      }
    }
  }

  function onFullscreenChange() {
    setImmersive(!!document.fullscreenElement);
  }

  function onKey(e) {
    // e.repeat: tugma bosib turilganda OS takrorlaydi — bitta bosish bitta amal (aks holda boshlash → kirish va
    // o'qish vaqti ketma-ket o'tkazib yuboriladi; audit V2-F9)
    if (e.repeat || e.ctrlKey || e.metaKey || e.altKey || !game || document.querySelector('.modal-overlay.show')) return;
    const tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON' || tag === 'A') {
      if (e.key !== 'f' && e.key !== 'F') return;
    }
    if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      toggleFullscreen();
    } else if (e.key === ' ' || e.key === 'Enter') {
      if (game.phase === 'question_result' || game.phase === 'leaderboard') {
        e.preventDefault();
        act('next');
      } else if (game.phase === 'topic_intro' || game.phase === 'question_read') {
        e.preventDefault();
        act('skip');
      } else if (game.phase === 'lobby' && game.playerCount) {
        e.preventDefault();
        act('start');
      }
    }
  }

  document.addEventListener('fullscreenchange', onFullscreenChange);
  document.addEventListener('keydown', onKey);
  return () => {
    alive = false;
    sock.close();
    clearInterval(tickTimer);
    root.classList.remove('wide');
    document.removeEventListener('fullscreenchange', onFullscreenChange);
    document.removeEventListener('keydown', onKey);
    document.body.classList.remove('oct-immersive');
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  };
}

/** Konfetti uchun javob ranglari — mavzu faylidagi o'zgaruvchilardan (JS da hex qiymat yo'q). */
function themeColors() {
  const css = getComputedStyle(document.documentElement);
  return ['--oc-red', '--oc-blue', '--oc-yellow', '--oc-green'].map((v) => css.getPropertyValue(v).trim()).filter(Boolean);
}
