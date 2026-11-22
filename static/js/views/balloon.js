// Balloon Pop — jamoaviy sinf o'yini: sozlash (lobbi), o'yin ekrani, natija va tarix.
// O'yin bitta ekranda (proyektor/doska) o'tkaziladi; holat serverda saqlanadi, sahifa yangilansa ham davom etadi.
import { h, icon, toast, confirmDialog, spinner, emptyState, fmtDate, beep, sfx, confetti, LETTERS } from '../lib.js';
import { api } from '../api.js';
import { live } from '../live.js';
import { Scene, Dice, TEAM_COLORS, teamColor, teamStyle, miniBunch, mix, wait } from '../balloon-scene.js';

const PREFS_KEY = 'td-balloon-setup';
const BALLOON_CHOICES = [10, 15, 20, 25, 30];
const MIN_BALLOONS = 5;
const MAX_BALLOONS = 50; // serverdagi app/balloon.py bilan bir xil
const TIME_CHOICES = [[0, 'Cheklovsiz'], [20, '20 s'], [30, '30 s'], [60, '60 s']];
const DEFAULT_PREFS = {
  topicId: null,
  teams: [{ name: '', color: 'red' }, { name: '', color: 'blue' }],
  balloons: 20,
  answerTime: 30,
};

const defaultName = (color) => `${teamColor(color).name} jamoa`;

// Yordamlar: har bir jamoa har biridan o'yinda bir marta foydalanadi (serverdagi app/balloon.py bilan bir xil).
const LIFELINES = [
  { id: 'ai', icon: 'bot', label: 'AIʼdan soʻrash', note: 'savolni telefondagi AI yordamchiga yozing yoki ekranni rasmga olib yuboring.' },
  { id: 'group', icon: 'users', label: 'Guruhdan soʻrash', note: 'guruhdoshlaringiz fikrini soʻrang — masalan, qoʻl koʻtarib ovoz berish orqali.' },
  { id: 'fifty', icon: null, label: '50:50', note: 'notoʻgʻri javoblar olib tashlandi.' },
];
const LIFELINE_BONUS_SECONDS = 30;

function lifelineIcon(l, size) {
  return l.icon ? icon(l.icon, size) : h('b.bp-ll-ff', '50:50');
}

export function balloonView(root, params, ctx) {
  if (params.id) return gameView(root, Number(params.id), ctx);
  return lobbyView(root, ctx);
}

function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) || 'null');
    if (p && Array.isArray(p.teams) && p.teams.length === 2 && p.teams.every((t) => t && TEAM_COLORS[t.color])) {
      const prefs = { ...DEFAULT_PREFS, ...p, teams: p.teams.map((t) => ({ color: t.color, name: String(t.name || '') })) };
      if (!Number.isInteger(prefs.balloons) || prefs.balloons < MIN_BALLOONS || prefs.balloons > MAX_BALLOONS) prefs.balloons = DEFAULT_PREFS.balloons;
      if (!TIME_CHOICES.some(([v]) => v === prefs.answerTime)) prefs.answerTime = DEFAULT_PREFS.answerTime;
      return prefs;
    }
  } catch {
    /* e'tiborsiz */
  }
  return structuredClone(DEFAULT_PREFS);
}

function savePrefs(p) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* saqlab bo'lmasa ham ishlayveradi */
  }
}

function teamDot(color) {
  return h('span.bp-dot', { style: teamStyle(color) });
}

function teamLabel(t) {
  return h('span.bp-team-label', { style: teamStyle(t.color) }, h('span.bp-dot'), h('span', t.name));
}

// =================================================================== lobbi
function lobbyView(root, ctx) {
  const prefs = loadPrefs();
  prefs.teams = prefs.teams.map((t) => ({ color: t.color, name: t.name || defaultName(t.color) }));
  const resumeBox = h('div');
  const historyBox = h('div', spinner('Oʻyinlar yuklanmoqda…'));
  const topicSelect = h('select', { id: 'bp-topic', 'aria-label': 'Mavzu' }, h('option', { value: '' }, 'Mavzular yuklanmoqda…'));
  const topicHint = h('span.field-hint');
  const err = h('div.field-error');
  const startBtn = h('button.btn.accent.lg.block', { type: 'button', onclick: start }, icon('play', 18), 'Oʻyinni boshlash');
  let topics = [];
  let alive = true;

  // ---- jamoalar
  const editors = [0, 1].map((i) => teamEditor(i));
  function teamEditor(i) {
    const t = prefs.teams[i];
    const preview = h('div.bp-te-preview');
    const input = h('input', { type: 'text', maxlength: 30, value: t.name, placeholder: `${i + 1}-jamoa nomi`, 'aria-label': `${i + 1}-jamoa nomi` });
    const swatches = h('div.bp-swatches', { role: 'radiogroup', 'aria-label': `${i + 1}-jamoa rangi` });
    const box = h('div.bp-team-edit', h('div.bp-te-head', preview, h('div.bp-te-title', h('span.small.muted', `${i + 1}-jamoa`), input)), swatches);
    input.addEventListener('input', () => {
      prefs.teams[i].name = input.value;
    });
    input.addEventListener('blur', () => {
      if (!input.value.trim()) {
        prefs.teams[i].name = defaultName(prefs.teams[i].color);
        input.value = prefs.teams[i].name;
      }
    });
    function paint() {
      const cur = prefs.teams[i];
      const other = prefs.teams[1 - i];
      Object.entries(teamStyle(cur.color)).forEach(([k, v]) => box.style.setProperty(k, v));
      preview.replaceChildren(miniBunch(cur.color, prefs.balloons));
      swatches.replaceChildren(...Object.entries(TEAM_COLORS).map(([key, c]) => {
        const taken = key === other.color;
        return h('button', {
          type: 'button',
          class: `bp-swatch${key === cur.color ? ' selected' : ''}`,
          style: { background: c.hex },
          title: taken ? `${c.name} — boshqa jamoa tanlagan` : c.name,
          'aria-label': c.name,
          role: 'radio',
          'aria-checked': String(key === cur.color),
          disabled: taken,
          onclick: () => pick(key),
        });
      }));
    }
    function pick(key) {
      const cur = prefs.teams[i];
      const wasDefault = !cur.name.trim() || cur.name.trim() === defaultName(cur.color);
      cur.color = key;
      if (wasDefault) {
        cur.name = defaultName(key);
        input.value = cur.name;
      }
      editors.forEach((e) => e.paint());
    }
    return { el: box, paint, input };
  }
  editors.forEach((e) => e.paint());

  // ---- sharlar soni: istalgan sonni yozish, −/+ tugmalari yoki tayyor variantlar
  function balloonCounter() {
    const valid = (n) => Number.isInteger(n) && n >= MIN_BALLOONS && n <= MAX_BALLOONS;
    if (!valid(prefs.balloons)) prefs.balloons = DEFAULT_PREFS.balloons;
    const input = h('input.bp-count-input', {
      type: 'number', min: MIN_BALLOONS, max: MAX_BALLOONS, step: 1, inputmode: 'numeric',
      value: String(prefs.balloons), 'aria-label': 'Har bir jamoaga sharlar soni',
    });
    const minus = h('button.bp-step-btn', { type: 'button', 'aria-label': 'Bitta kamaytirish', onclick: () => set(prefs.balloons - 1) }, icon('minus', 18));
    const plus = h('button.bp-step-btn', { type: 'button', 'aria-label': 'Bitta koʻpaytirish', onclick: () => set(prefs.balloons + 1) }, icon('plus', 18));
    const presets = h('div.bp-chips', { 'aria-label': 'Tayyor variantlar' });
    function set(raw) {
      // bo'sh yoki son bo'lmagan qiymat — avvalgi son qoladi
      let n = String(raw).trim() === '' ? NaN : Math.round(Number(raw));
      if (!Number.isFinite(n)) n = prefs.balloons;
      prefs.balloons = Math.max(MIN_BALLOONS, Math.min(MAX_BALLOONS, n));
      input.value = String(prefs.balloons);
      paint();
    }
    function paint() {
      minus.disabled = prefs.balloons <= MIN_BALLOONS;
      plus.disabled = prefs.balloons >= MAX_BALLOONS;
      presets.replaceChildren(...BALLOON_CHOICES.map((n) => h('button', {
        type: 'button',
        class: `bp-chip${n === prefs.balloons ? ' selected' : ''}`,
        'aria-pressed': String(n === prefs.balloons),
        onclick: () => set(n),
      }, String(n))));
      editors.forEach((e) => e.paint()); // bog'lam ko'rinishi tanlangan sonni ko'rsatadi
    }
    input.addEventListener('input', () => {
      const n = Number(input.value);
      if (valid(n)) {
        prefs.balloons = n;
        paint();
      }
    });
    input.addEventListener('change', () => set(input.value)); // chegaradan chiqsa — eng yaqin ruxsat etilgan son
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        set(input.value);
      }
    });
    paint();
    return { el: h('div.bp-counter', h('div.bp-stepper', minus, input, plus), presets), input, set };
  }

  // ---- tanlovlar (javob vaqti)
  const chipGroup = (options, current, onPick, label) => {
    const group = h('div.bp-chips', { role: 'radiogroup', 'aria-label': label });
    const paint = (value) => group.replaceChildren(...options.map(([v, text]) => h('button', {
      type: 'button',
      class: `bp-chip${v === value ? ' selected' : ''}`,
      role: 'radio',
      'aria-checked': String(v === value),
      onclick: () => {
        onPick(v);
        paint(v);
      },
    }, text)));
    paint(current);
    return group;
  };
  const counter = balloonCounter();
  const timeChips = chipGroup(TIME_CHOICES, prefs.answerTime, (v) => { prefs.answerTime = v; }, 'Javob vaqti');

  const setupCard = h('div.card.bp-setup',
    h('h2.card-title', icon('sparkles', 20), 'Yangi oʻyin'),
    h('label.field', h('span.field-label', 'Mavzu (savollar shu mavzudan beriladi)'), topicSelect, topicHint),
    h('div.field', h('span.field-label', 'Jamoalar'), h('div.bp-teams-setup', editors[0].el, h('span.bp-vs', 'VS'), editors[1].el)),
    h('div.bp-setup-row',
      h('div.field', h('span.field-label', 'Har bir jamoaga sharlar soni'), counter.el,
        h('span.field-hint', `${MIN_BALLOONS} dan ${MAX_BALLOONS} gacha istalgan son. Koʻproq shar — uzunroq oʻyin.`)),
      h('div.field', h('span.field-label', 'Savolga javob vaqti'), timeChips)),
    err,
    startBtn);

  const step = (n, title, text) => h('li', h('span.bp-step', String(n)), h('div', h('b', title), h('span', text)));
  const rulesCard = h('div.card.bp-rules',
    h('h2.card-title', icon('help', 20), 'Qanday oʻynaladi?'),
    h('ol.bp-steps',
      step(1, 'Tosh, qaychi, qogʻoz', 'Jamoalar sinfda oʻynaydi, oʻqituvchi yutgan jamoani belgilaydi.'),
      step(2, 'Savol', 'Yutqazgan jamoa tanlangan mavzudan bitta savolga javob beradi.'),
      step(3, 'Zar', 'Yutgan jamoa birinchi boʻlib zar tashlaydi va raqibning tushgan son miqdoricha sharini portlatadi.'),
      step(4, 'Imkoniyat', 'Yutqazgan jamoa toʻgʻri javob bergan boʻlsa, u ham zar tashlaydi.'),
      step(5, 'Akulalar!', 'Sharlari tugagan jamoa suvga tushadi va akulaga yem boʻladi. Havoda qolgan jamoa gʻolib!'),
      step(6, 'Yordamlar', `Har bir jamoa oʻyinda bir martadan: AIʼdan soʻrash, guruhdan soʻrash (ikkalasi +${LIFELINE_BONUS_SECONDS} soniya) va 50:50 — ikkita notoʻgʻri javob olib tashlanadi.`)),
    h('p.small.muted.bp-tip', icon('maximize', 14), 'Maslahat: oʻyinni proyektor yoki interaktiv doskada toʻliq ekran rejimida oʻtkazing. Sharlarni sichqoncha yoki barmoq bilan bosib portlatish mumkin.'));

  root.append(h('section.screen.bp-lobby',
    h('a.back-link.games-back', { href: '#/games' }, icon('left', 16), 'Oʻyinlar'),
    h('div.page-head', h('div',
      h('h1.bp-title', 'Balloon Pop'),
      h('p.muted', 'Jamoaviy sinf oʻyini: savollarga javob bering, zar tashlang va raqib sharlarini portlating. Sharlari tugagan jamoa akulalarga yem boʻladi!'))),
    resumeBox,
    h('div.bp-lobby-grid', setupCard, rulesCard),
    h('h2.section-title', 'Oʻyinlar tarixi'),
    historyBox));

  async function loadTopics() {
    try {
      topics = (await api('/api/topics')).topics;
    } catch (e) {
      if (!alive) return;
      topicSelect.replaceChildren(h('option', { value: '' }, 'Mavzularni yuklab boʻlmadi'));
      err.textContent = e.message;
      return;
    }
    if (!alive) return;
    if (!topics.length) {
      topicSelect.replaceChildren(h('option', { value: '' }, 'Hozircha mavzular yoʻq'));
      topicSelect.disabled = true;
      startBtn.disabled = true;
      topicHint.replaceChildren(ctx.user.isAdmin
        ? h('span', 'Avval ', h('a', { href: '#/admin' }, 'Boshqaruv'), ' boʻlimida test faylini yuklang.')
        : 'Administrator test faylini yuklaganidan keyin oʻynash mumkin.');
      return;
    }
    const keep = topics.some((t) => t.id === prefs.topicId) ? prefs.topicId : topics[0].id;
    topicSelect.disabled = false;
    startBtn.disabled = false;
    topicHint.textContent = '';
    topicSelect.replaceChildren(...topics.map((t) => h('option', { value: String(t.id), selected: t.id === keep }, `${t.name} (${t.questionCount} ta savol)`)));
    topicSelect.value = String(keep);
  }

  async function loadGames() {
    let games;
    try {
      games = (await api('/api/balloon/games')).games;
    } catch (e) {
      if (alive) historyBox.replaceChildren(emptyState('wifiOff', 'Oʻyinlar tarixini yuklab boʻlmadi', e.message));
      return;
    }
    if (!alive) return;
    const active = games.find((g) => g.phase !== 'finished');
    resumeBox.replaceChildren(active ? h('div.card.resume-card.bp-resume',
      h('span.resume-ic', icon('balloon', 20)),
      h('div.resume-text',
        h('b', 'Tugallanmagan oʻyin'),
        h('span.muted', `${active.topicName} · ${active.round}-raund · `, ...vsLine(active))),
      h('a.btn.primary.sm', { href: `#/games/balloon/${active.id}` }, icon('play', 14), 'Davom ettirish')) : '');
    if (!games.length) {
      historyBox.replaceChildren(h('div.card.muted.center', 'Hali oʻyin oʻtkazilmagan. Birinchi oʻyinni boshlang!'));
      return;
    }
    historyBox.replaceChildren(h('div.bp-history', games.map((g) => h('div.card.bp-hrow',
      h('div.bp-hrow-main',
        h('div.bp-vs-cell', ...vsLine(g)),
        h('div.small.muted', `${g.topicName} · ${g.round}-raund · ${g.balloons} tadan shar · ${fmtDate(g.updatedAt)}`)),
      h('div.bp-hrow-side',
        resultBadge(g),
        h('a.btn.ghost.sm', { href: `#/games/balloon/${g.id}` }, g.phase === 'finished' ? 'Koʻrish' : 'Davom ettirish'),
        h('button.icon-btn.danger', { type: 'button', title: 'Oʻchirish', 'aria-label': 'Oʻyinni oʻchirish', onclick: () => remove(g) }, icon('trash', 16)))))));
  }

  function vsLine(g) {
    return [teamLabel(g.teams[0]), h('b.bp-score', ` ${g.teams[0].left} : ${g.teams[1].left} `), teamLabel(g.teams[1])];
  }

  function resultBadge(g) {
    if (g.phase !== 'finished') return h('span.badge.warn', 'Davom etmoqda');
    if (g.winner === null) return h('span.badge.neutral', 'Durang');
    return h('span.badge.bp-win', { style: teamStyle(g.teams[g.winner].color) }, icon('trophy', 12), `${g.teams[g.winner].name} gʻolib`);
  }

  async function remove(g) {
    const ok = await confirmDialog({
      title: 'Oʻyinni oʻchirasizmi?',
      message: `${g.topicName}: ${g.teams[0].name} va ${g.teams[1].name} oʻyini tarixdan butunlay oʻchiriladi.`,
      okText: 'Oʻchirish',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/balloon/games/${g.id}`, { method: 'DELETE' });
      toast('Oʻyin oʻchirildi', 'success');
      loadGames();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function start() {
    err.textContent = '';
    counter.set(counter.input.value); // yozilgan, lekin hali tasdiqlanmagan sonni ham hisobga olamiz
    const topicId = Number(topicSelect.value);
    if (!topicId) {
      err.textContent = 'Mavzuni tanlang';
      topicSelect.focus();
      return;
    }
    const teams = prefs.teams.map((t) => ({ color: t.color, name: t.name.trim() || defaultName(t.color) }));
    if (teams[0].name.toLocaleLowerCase() === teams[1].name.toLocaleLowerCase()) {
      err.textContent = 'Jamoalarga turli nom bering';
      editors[1].input.focus();
      return;
    }
    prefs.topicId = topicId;
    savePrefs({ ...prefs, teams });
    startBtn.disabled = true;
    try {
      const res = await api('/api/balloon/games', { method: 'POST', body: { topicId, teams, balloons: prefs.balloons, answerTime: prefs.answerTime } });
      ctx.navigate(`/games/balloon/${res.game.id}`);
    } catch (e) {
      err.textContent = e.message;
      startBtn.disabled = false;
    }
  }

  loadTopics();
  loadGames();
  const off = live.on('topics', loadTopics);
  return () => {
    alive = false;
    off();
  };
}

// ============================================================ o'yin ekrani
function gameView(root, gameId, ctx) {
  root.classList.add('wide');
  let alive = true;
  let game = null;
  let chain = Promise.resolve();
  let busy = false;        // zar tashlanmoqda yoki avtomatik portlatish animatsiyasi
  let ending = false;      // yakuniy animatsiya (odamcha suvga tushmoqda)
  let reveal = null;       // javobdan keyingi ko'rinish (to'g'ri javob ko'rsatiladi)
  let pickedChoice = null; // yuborilgan, lekin hali natijasi kelmagan javob
  let popGoal = 0;
  const optimistic = new Set(); // serverga yuborilgan, lekin hali tasdiqlanmagan portlatishlar
  let shownPhase = '';
  let phaseSince = 0;      // bosqich almashgan vaqt: tugmani ikki marta bosish keyingi bosqichga "o'tib ketmasin"
  let timerHandle = null;
  let deadline = 0;
  let lastTick = null;
  let wakeLock = null;

  const scene = new Scene();
  scene.onPick = onPick;
  const dice = new Dice();
  const hudRound = h('div.bp-hud-round');
  const hudText = h('div.bp-hud-text', { 'aria-live': 'polite' });
  const hudDice = h('div.bp-hud-dice', dice.el);
  const hud = h('div.bp-hud', hudRound, hudDice, hudText);
  const stage = h('div.bp-stage', scene.el, hud);
  const board = h('div.bp-board');
  const panel = h('div.bp-panel');
  const logBox = h('details.card.bp-log');
  const fsBtn = h('button.icon-btn', { type: 'button', title: 'Toʻliq ekran (F)', 'aria-label': 'Toʻliq ekran', onclick: toggleFullscreen }, icon('maximize', 18));
  const endBtn = h('button.btn.ghost.sm', { type: 'button', onclick: endGame }, icon('flag', 14), h('span.hide-sm', 'Yakunlash'));
  const title = h('div.practice-title.bp-topic-title');
  const top = h('div.practice-top.bp-top',
    h('a.back-link', { href: '#/games/balloon' }, icon('left', 16), h('span.hide-sm', 'Balloon Pop')),
    title,
    h('div.bp-tools', fsBtn, endBtn));
  const section = h('section.screen.bp-game', top, board, stage, panel);
  root.append(h('div.card', spinner('Oʻyin yuklanmoqda…')));

  const ro = new ResizeObserver(() => fit());
  function fit() {
    const r = stage.getBoundingClientRect();
    if (!r.width || !r.height) return;
    scene.layout(r.width, r.height);
    stage.style.setProperty('--ds', `${Math.round(Math.max(46, Math.min(132, 150 * scene.px)))}px`);
    stage.style.setProperty('--fs', `${Math.max(13, Math.min(30, 40 * scene.px)).toFixed(1)}px`);
  }

  async function load() {
    try {
      const res = await api(`/api/balloon/games/${gameId}`);
      if (!alive) return;
      game = res.game;
    } catch (e) {
      if (!alive) return;
      root.replaceChildren(emptyState('alert', 'Oʻyinni ochib boʻlmadi', e.message, h('a.btn.primary', { href: '#/games/balloon' }, 'Balloon Pop')));
      return;
    }
    root.replaceChildren(section, logBox);
    title.textContent = game.topicName;
    scene.build(game);
    ro.observe(stage);
    fit();
    if (game.dice) {
      dice.setColor(game.teams[game.dice.team].color);
      dice.show(game.dice.value);
    }
    popGoal = lastRollPopped();
    render();
    requestWakeLock();
  }

  // ------------------------------------------------------------ server
  function send(action) {
    const p = chain.then(async () => {
      if (!alive || !game) return null;
      try {
        const res = await api(`/api/balloon/games/${gameId}/action`, { method: 'POST', body: { ...action, rev: game.rev } });
        if (alive) game = res.game;
        return alive ? res : null;
      } catch (e) {
        if (!alive) return null;
        toast(e.message, 'error');
        if (e.data && e.data.game) {
          game = e.data.game;
          resync();
        } else {
          setTimeout(refresh, 1500); // aloqa uzildi — keyinroq serverdagi holatni qayta olamiz
        }
        return null;
      }
    });
    chain = p.catch(() => null);
    return p;
  }

  async function refresh() {
    if (!alive) return;
    try {
      const res = await api(`/api/balloon/games/${gameId}`);
      if (!alive) return;
      game = res.game;
      resync();
    } catch {
      if (alive) setTimeout(refresh, 4000);
    }
  }

  function resync() {
    optimistic.clear();
    reveal = null;
    pickedChoice = null;
    busy = false;
    scene.build(game);
    fit();
    if (game.dice) {
      dice.setColor(game.teams[game.dice.team].color);
      dice.show(game.dice.value);
    }
    popGoal = lastRollPopped();
    render();
  }

  function lastRollPopped() {
    for (let i = game.log.length - 1; i >= 0; i--) {
      if (game.log[i].t === 'roll') return game.log[i].popped;
    }
    return game.pending;
  }

  // ------------------------------------------------------------- amallar
  async function chooseRps(winner) {
    if (busy || game.phase !== 'rps') return;
    busy = true;
    render();
    const res = await send({ type: 'rps', winner });
    busy = false;
    if (res) beep('match');
    render();
  }

  async function answer(choice, timedOut = false) {
    if (busy || game.phase !== 'question' || reveal) return;
    busy = true;
    pickedChoice = choice;
    stopTimer();
    renderPanel();
    const asked = game.question;
    const res = await send({ type: 'answer', choice, timeout: timedOut });
    busy = false;
    pickedChoice = null;
    if (!res) return render();
    reveal = { question: { ...asked, correct: res.event.correctIndex }, ev: res.event };
    beep(res.event.correct ? 'correct' : 'wrong');
    render();
  }

  async function simpleAction(type) {
    if (busy) return;
    busy = true;
    stopTimer();
    renderPanel();
    await send({ type });
    busy = false;
    render();
  }

  function continueAfterReveal() {
    if (!reveal) return;
    reveal = null;
    render();
  }

  async function roll() {
    if (busy || ending || game.phase !== 'roll') return;
    busy = true;
    const team = game.turn.team;
    dice.setColor(game.teams[team].color);
    dice.shake();
    sfx('roll');
    render();
    const res = await send({ type: 'roll' });
    if (!res) {
      busy = false;
      return render();
    }
    await dice.roll(res.event.value);
    if (!alive) return;
    sfx('land');
    popGoal = res.event.pending;
    busy = false;
    render();
  }

  function onPick(teamIndex, i) {
    if (!game || busy || ending || game.phase !== 'pop') return;
    const target = 1 - game.turn.team;
    if (teamIndex !== target || game.pending - optimistic.size <= 0) return;
    if (!scene.teams[target].pop(i)) return;
    optimistic.add(i);
    sfx('pop');
    scene.teams[target].update(game.teams[target].left - optimistic.size);
    renderBoard();
    renderHud();
    renderPanel();
    send({ type: 'pop', balloons: [i] }).then((res) => {
      optimistic.delete(i);
      if (res) afterPop(res);
    });
  }

  async function autoPop() {
    if (busy || ending || game.phase !== 'pop') return;
    busy = true;
    render();
    const res = await send({ type: 'pop', auto: true });
    if (res) {
      const target = res.event.target;
      let shown = game.teams[target].left + res.event.popped.length;
      for (const i of res.event.popped) {
        if (!alive) return;
        if (scene.teams[target].pop(i)) sfx('pop');
        shown -= 1;
        scene.teams[target].update(shown);
        await wait(280);
      }
    }
    busy = false;
    if (res) afterPop(res);
    else render();
  }

  function afterPop(res) {
    if (!alive) return;
    if (res.event.finished) {
      endSequence();
      return;
    }
    if (optimistic.size) {
      renderBoard();
      renderPanel();
      return;
    }
    scene.teams.forEach((t, i) => t.update(game.teams[i].left));
    if (game.phase !== 'pop') {
      // navbat almashdi: portlash animatsiyasi tugashini kutamiz
      busy = true;
      renderPanel();
      setTimeout(() => {
        busy = false;
        render();
      }, 650);
    } else {
      render();
    }
  }

  async function endSequence() {
    ending = true;
    render();
    const loser = game.winner === null ? null : 1 - game.winner;
    await wait(450);
    if (loser !== null && game.endReason === 'popped') {
      setTimeout(() => sfx('splash'), 800);
      setTimeout(() => sfx('chomp'), 1250);
      await scene.teams[loser].fall();
      await wait(500);
    }
    if (!alive) return;
    ending = false;
    celebrate();
    render();
  }

  function celebrate() {
    if (game.winner === null) {
      beep('draw');
      return;
    }
    const c = teamColor(game.teams[game.winner].color);
    confetti([c.hex, c.dark, mix(c.hex, '#ffffff', 0.5), '#f7b500', '#ffffff']);
    beep('win');
  }

  async function endGame() {
    if (!game || game.phase === 'finished' || ending) return;
    const ok = await confirmDialog({
      title: 'Oʻyinni yakunlaysizmi?',
      message: 'Oʻyin hozir toʻxtatiladi. Koʻproq shari qolgan jamoa gʻolib deb topiladi (teng boʻlsa — durang).',
      okText: 'Yakunlash',
      cancelText: 'Davom etish',
    });
    if (!ok || !alive) return;
    stopTimer();
    const res = await send({ type: 'end' });
    if (!res) return;
    reveal = null;
    celebrate();
    render();
  }

  async function rematch() {
    try {
      const res = await api('/api/balloon/games', {
        method: 'POST',
        body: { topicId: game.topicId, teams: game.teams.map((t) => ({ name: t.name, color: t.color })), balloons: game.balloons, answerTime: game.answerTime },
      });
      ctx.navigate(`/games/balloon/${res.game.id}`);
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  // ------------------------------------------------------------ chizish
  function uiPhase() {
    if (ending) return 'ending';
    if (reveal) return 'reveal';
    return game.phase;
  }

  function render() {
    if (!alive || !game) return;
    const phase = uiPhase();
    if (phase !== shownPhase) {
      shownPhase = phase;
      phaseSince = performance.now();
    }
    section.className = `screen bp-game phase-${phase}`;
    renderBoard();
    renderHud();
    renderPanel();
    renderLog();
    const target = game.turn ? 1 - game.turn.team : -1;
    scene.teams.forEach((t, i) => t.setPickable(game.phase === 'pop' && !busy && !ending && i === target));
    endBtn.hidden = game.phase === 'finished';
    if (game.phase === 'question' && !reveal && !busy) startTimer();
    else if (game.phase !== 'question') stopTimer();
  }

  function shownLeft(i) {
    const target = game.turn ? 1 - game.turn.team : -1;
    return game.teams[i].left - (i === target ? optimistic.size : 0);
  }

  function activeTeam() {
    if (reveal) return reveal.question.team;
    if (game.phase === 'question') return game.question.team;
    if (game.phase === 'roll' || game.phase === 'pop') return game.turn.team;
    if (game.phase === 'finished') return game.winner;
    return null;
  }

  function renderBoard() {
    const act = activeTeam();
    const side = (i) => {
      const t = game.teams[i];
      const left = shownLeft(i);
      const pct = Math.max(0, (left / game.balloons) * 100);
      return h('div', { class: `bp-sb-team side-${i}${act === i ? ' active' : ''}${left <= 0 ? ' out' : ''}`, style: teamStyle(t.color) },
        h('div.bp-sb-row',
          h('span.bp-sb-name', h('span.bp-dot'), h('b', t.name)),
          h('span.bp-sb-count', icon('balloon', 18), h('b', String(Math.max(0, left))), h('small', `/${game.balloons}`))),
        h('div.bp-sb-bar', h('span', { style: { width: `${pct}%` } })),
        h('div.bp-sb-foot',
          h('span.bp-sb-meta', `Savollar: ${t.correct}/${t.asked} toʻgʻri · zar: ${t.rolls} marta`),
          h('span.bp-sb-lls', LIFELINES.map((l) => {
            const used = !!(t.lifelines || {})[l.id];
            return h('span', { class: `bp-ll-dot${used ? ' used' : ''}`, title: `${l.label}${used ? ' — ishlatilgan' : ' — bor'}` }, lifelineIcon(l, 13));
          }))));
    };
    board.replaceChildren(side(0), h('div.bp-sb-mid', h('b', String(game.round)), h('span', 'raund')), side(1));
  }

  function renderHud() {
    const T = (i) => game.teams[i];
    const phase = uiPhase();
    hudRound.textContent = phase === 'finished' ? 'Oʻyin tugadi' : `${game.round}-raund`;
    hudDice.hidden = !['roll', 'pop'].includes(phase);
    hudDice.classList.toggle('waiting', phase === 'roll' && !busy);
    let text = null;
    if (phase === 'rps') {
      text = h('div.bp-hud-rps', h('span', '✊'), h('span', '✋'), h('span', '✌️'));
      hudText.replaceChildren(text, h('div.bp-hud-line', 'Tosh, qaychi, qogʻoz!'));
      return;
    }
    if (phase === 'reveal') {
      const ok = reveal.ev.correct;
      hudText.replaceChildren(h(`div.bp-hud-line.big.${ok ? 'good' : 'bad'}`, ok ? '✓ Toʻgʻri javob!' : reveal.ev.timedOut ? '⏰ Vaqt tugadi' : '✗ Notoʻgʻri'));
      return;
    }
    if (phase === 'question') {
      const t = T(game.question.team);
      const helping = (game.question.used || []).filter((id) => id !== 'fifty').map((id) => LIFELINES.find((l) => l.id === id));
      hudText.replaceChildren(
        h('div.bp-hud-line', { style: teamStyle(t.color) }, h('span.bp-dot'), `${t.name} javob bermoqda`),
        ...helping.map((l) => h('div.bp-hud-line.ll', lifelineIcon(l, 18), l.label)));
      return;
    }
    if (phase === 'roll') {
      const t = T(game.turn.team);
      hudText.replaceChildren(h('div.bp-hud-line', { style: teamStyle(t.color) }, h('span.bp-dot'), busy ? `${t.name} zar tashlamoqda…` : `${t.name} navbati`));
      if (!busy) {
        dice.setColor(t.color);
        if (!game.dice || game.dice.team !== game.turn.team) dice.show(6);
      }
      return;
    }
    if (phase === 'pop') {
      const left = game.pending - optimistic.size;
      const opp = T(1 - game.turn.team);
      hudText.replaceChildren(h('div.bp-hud-line.big', { style: teamStyle(opp.color) },
        left > 0 ? `💥 ${left} ta shar qoldi` : 'Barakalla!'));
      return;
    }
    if (phase === 'ending') {
      hudText.replaceChildren(h('div.bp-hud-line.big', game.endReason === 'popped' ? 'Ehtiyot boʻling, akula!' : 'Oʻyin tugadi'));
      return;
    }
    if (phase === 'finished') {
      hudText.replaceChildren(game.winner === null
        ? h('div.bp-hud-line.big', '🤝 Durang!')
        : h('div.bp-hud-line.big', { style: teamStyle(T(game.winner).color) }, '🏆 ', h('span', `${T(game.winner).name} gʻolib!`)));
    }
  }

  function renderPanel() {
    const phase = uiPhase();
    let content;
    if (phase === 'finished') content = panelResult();
    else if (phase === 'ending') content = h('div.bp-panel-card.center', h('h2', 'Oxirgi shar portladi…'));
    else if (phase === 'reveal') content = panelQuestion(true);
    else if (phase === 'rps') content = panelRps();
    else if (phase === 'question') content = panelQuestion(false);
    else if (phase === 'roll') content = panelRoll();
    else content = panelPop();
    const key = `${phase}:${game.round}:${game.turn ? `${game.turn.team}${game.turn.bonus}` : ''}:${game.question ? game.question.id : ''}`;
    if (key === panelKey) content.classList.add('still'); // bir xil bosqichda qayta chizilganda "sakramasin"
    panelKey = key;
    panel.replaceChildren(content);
  }
  let panelKey = '';

  function panelRps() {
    return h('div.bp-panel-card.bp-rps',
      h('h2', 'Tosh, qaychi, qogʻoz!'),
      h('p.muted', 'Jamoalar sinfda oʻynaydi. Qaysi jamoa yutdi?'),
      h('div.bp-team-btns', [0, 1].map((i) => h('button', {
        type: 'button',
        class: 'bp-team-btn',
        style: teamStyle(game.teams[i].color),
        disabled: busy,
        onclick: () => chooseRps(i),
      }, h('span.bp-kbd', String(i + 1)), h('span.bp-team-btn-text', h('b', game.teams[i].name), h('span', 'yutdi'))))),
      h('p.small.muted', 'Durang boʻlsa — qaytadan oʻynang. Yutqazgan jamoa savolga javob beradi, yutgan jamoa birinchi boʻlib zar tashlaydi.'));
  }

  function panelQuestion(revealed) {
    const q = revealed ? reveal.question : game.question;
    const ev = revealed ? reveal.ev : null;
    const t = game.teams[q.team];
    const hidden = new Set(q.hidden || []);
    const options = q.options.map((text, j) => {
      let cls = 'option';
      if (revealed) cls += j === q.correct ? ' correct' : j === ev.choice ? ' wrong' : ' dim';
      else if (pickedChoice === j) cls += ' picked';
      if (hidden.has(j) && j !== q.correct) cls += ' eliminated';
      return h('button', { type: 'button', class: cls, disabled: revealed || busy || hidden.has(j), onclick: () => answer(j), title: hidden.has(j) ? '50:50 bilan olib tashlangan' : null },
        h('span.opt-key', LETTERS[j] || String(j + 1)), h('span.opt-text', text), h('span.opt-mark'));
    });
    const short = q.options.length >= 3 && q.options.every((o) => o.length <= 90);
    let foot;
    if (revealed) {
      const correctText = h('span.fb-correct', `${LETTERS[q.correct]}) ${q.options[q.correct]}`);
      const fb = ev.correct
        ? h('div.feedback.good', icon('check', 18), h('div', h('b', 'Toʻgʻri javob! '), `${t.name} ham zar tashlaydi.`))
        : h('div.feedback.bad', icon(ev.timedOut ? 'clock' : 'x', 18), h('div',
          h('b', ev.timedOut ? 'Vaqt tugadi! ' : ev.choice === null ? 'Javob berilmadi. ' : 'Notoʻgʻri. '),
          'Toʻgʻri javob: ', correctText));
      const roller = game.teams[game.turn ? game.turn.team : 1 - q.team];
      foot = [fb, h('div.bp-q-next',
        h('button.btn.primary.lg', { type: 'button', onclick: continueAfterReveal, style: teamStyle(roller.color), class: 'bp-team-solid' },
          icon('dice', 18), `${roller.name} zar tashlaydi`, icon('right', 16)))];
    } else {
      foot = [lifelineBar(q, t), h('div.bp-q-actions',
        h('button.btn.ghost.sm', { type: 'button', disabled: busy, onclick: () => simpleAction('back'), title: 'Tosh-qaychi-qogʻoz natijasi xato belgilangan boʻlsa' }, icon('left', 14), 'Orqaga'),
        h('button.btn.ghost.sm', { type: 'button', disabled: busy, onclick: () => simpleAction('skip'), title: 'Savolni boshqasiga almashtirish' }, icon('refresh', 14), 'Boshqa savol'),
        h('button.btn.ghost.sm', { type: 'button', disabled: busy, onclick: () => answer(null) }, icon('x', 14), 'Javob bera olmadi'))];
    }
    const head = h('div.bp-q-head',
      h('span.bp-team-tag', h('span.bp-dot'), `${t.name} javob beradi`),
      !revealed && game.answerTime ? timerRing().el : null);
    return h('div.qcard.bp-qcard.anim-in', { style: teamStyle(t.color) },
      head,
      h('div.q-text', q.text),
      h(`div.options.bp-options${short ? '.two' : ''}`, options),
      lifelineNotes(q),
      foot);
  }

  /** Javob berayotgan jamoaning yordam tugmalari. */
  function lifelineBar(q, t) {
    const used = t.lifelines || {};
    const visible = q.options.length - (q.hidden || []).length;
    return h('div.bp-lifelines', { role: 'group', 'aria-label': 'Yordamlar' },
      h('span.bp-ll-label', 'Yordam:'),
      LIFELINES.map((l) => {
        const spent = !!used[l.id];
        const impossible = l.id === 'fifty' && visible <= 2;
        const title = spent
          ? `${t.name} bu yordamdan foydalanib boʻlgan`
          : impossible ? 'Bu savolda olib tashlanadigan variant yoʻq' : `${l.label} — oʻyinda bir marta`;
        return h('button', {
          type: 'button',
          class: `bp-ll${spent ? ' used' : ''}`,
          disabled: spent || impossible || busy,
          title,
          'aria-label': title,
          onclick: () => useLifeline(l.id),
        }, lifelineIcon(l, 17), l.id === 'fifty' ? null : h('span', l.label));
      }));
  }

  function lifelineNotes(q) {
    const used = q.used || [];
    if (!used.length) return null;
    return h('div.bp-ll-notes', used.map((id) => {
      const l = LIFELINES.find((x) => x.id === id);
      if (!l) return null;
      const removed = (q.hidden || []).length;
      const text = id === 'fifty' ? `${removed === 1 ? 'bitta' : 'ikkita'} notoʻgʻri javob olib tashlandi.` : l.note;
      const bonus = id !== 'fifty' && game.answerTime ? h('b.bp-ll-bonus', ` +${LIFELINE_BONUS_SECONDS} soniya`) : null;
      return h('div.bp-ll-note', lifelineIcon(l, 16), h('div', h('b', `${l.label}: `), text, bonus));
    }));
  }

  async function useLifeline(kind) {
    if (busy || ending || reveal || game.phase !== 'question') return;
    const l = LIFELINES.find((x) => x.id === kind);
    const team = game.teams[game.question.team];
    const ok = await confirmDialog({
      title: l.label,
      message: `${team.name} «${l.label}» yordamidan foydalanadimi? Har bir yordamdan oʻyinda faqat bir marta foydalanish mumkin.`
        + (kind !== 'fifty' && game.answerTime ? ` Savol vaqtiga ${LIFELINE_BONUS_SECONDS} soniya qoʻshiladi.` : ''),
      okText: 'Ha, foydalanamiz',
      cancelText: 'Bekor qilish',
    });
    if (!ok || !alive || busy || reveal || game.phase !== 'question') return;
    busy = true;
    renderPanel();
    const res = await send({ type: 'lifeline', kind });
    busy = false;
    if (res) {
      beep('match');
      stopTimer(); // qo'shilgan vaqt bilan taymer qaytadan boshlanadi
    }
    render();
  }

  function answerNote() {
    const a = game.answer;
    if (!a || game.turn.bonus) return null;
    const t = game.teams[a.team];
    return a.correct
      ? h('div.bp-note.good', icon('check', 16), `${t.name} savolga toʻgʻri javob berdi — keyin u ham zar tashlaydi.`)
      : h('div.bp-note.bad', icon('x', 16), `${t.name} ${a.timedOut ? 'vaqtida javob bermadi' : a.choice === null ? 'javob bera olmadi' : 'notoʻgʻri javob berdi'} — bu raundda zar tashlay olmaydi.`);
  }

  function panelRoll() {
    const t = game.teams[game.turn.team];
    const opp = game.teams[1 - game.turn.team];
    return h('div.bp-panel-card.bp-roll', { style: teamStyle(t.color) },
      game.turn.bonus ? h('span.bp-bonus', icon('sparkles', 14), 'Toʻgʻri javob uchun zar') : null,
      h('h2', h('span.bp-dot'), `${t.name} zar tashlaydi`),
      h('p.muted', `Tushgan son qancha boʻlsa, ${opp.name}ning shuncha sharini portlatasiz.`),
      h('button.bp-roll-btn', { type: 'button', disabled: busy, onclick: roll }, icon('dice', 26), busy ? 'Zar aylanmoqda…' : 'Zar tashlash'),
      answerNote(),
      h('p.small.muted.kbd-hint', 'Klaviatura: Probel yoki Enter — zar tashlash'));
  }

  function panelPop() {
    const t = game.teams[game.turn.team];
    const opp = game.teams[1 - game.turn.team];
    const left = game.pending - optimistic.size;
    const total = Math.max(popGoal, left);
    const done = total - left;
    return h('div.bp-panel-card.bp-pop', { style: teamStyle(t.color) },
      h('h2', h('span.bp-dot'), `${t.name}: ${opp.name}ning ${total} ta sharini portlating!`),
      h('p.muted', left > 0 ? 'Sahnadagi raqib sharlarini bosing (sichqoncha yoki barmoq bilan).' : 'Ajoyib!'),
      h('div.bp-pop-dots', { style: teamStyle(opp.color) }, Array.from({ length: total }, (_, i) => h('span', { class: i < done ? 'done' : '' }))),
      h('button.btn.ghost', { type: 'button', disabled: busy || left <= 0, onclick: autoPop }, icon('zap', 16), 'Avtomatik portlatish'),
      h('p.small.muted.kbd-hint', 'Klaviatura: Enter — avtomatik portlatish'));
  }

  function panelResult() {
    const w = game.winner;
    const T = game.teams;
    let titleText;
    let sub;
    if (w === null) {
      titleText = 'Durang!';
      sub = 'Ikkala jamoada teng miqdorda shar qoldi.';
    } else if (game.endReason === 'popped') {
      titleText = `${T[w].name} gʻolib!`;
      sub = `${T[1 - w].name}ning sharlari tugadi — akula uni yeb qoʻydi! 🦈`;
    } else {
      titleText = `${T[w].name} gʻolib!`;
      sub = 'Oʻyin muddatidan oldin yakunlandi: koʻproq shari qolgan jamoa gʻolib.';
    }
    const col = (i) => h('div', { class: `stat-col bp-stat${w === i ? ' winner' : ''}`, style: teamStyle(T[i].color) },
      w === i ? h('span.crown', icon('trophy', 12), 'gʻolib') : null,
      h('span.bp-stat-dot'),
      h('div.stat-name', T[i].name),
      h('div.stat-big', String(T[i].left), h('small', ` / ${game.balloons}`)),
      h('div.stat-label', 'qolgan shar'),
      h('div.bp-stat-line', icon('check', 14), `${T[i].correct} / ${T[i].asked} toʻgʻri javob`),
      h('div.bp-stat-line', icon('dice', 14), `${T[i].rolls} marta zar · jami ${T[i].rolled}`),
      h('div.bp-stat-line', icon('help', 14), `yordamlar: ${LIFELINES.filter((l) => (T[i].lifelines || {})[l.id]).length} / ${LIFELINES.length}`));
    return h('div.result.bp-result.anim-in',
      h('div.result-hero',
        h('div.result-icon', { style: w === null ? {} : teamStyle(T[w].color), class: w === null ? 'draw' : 'win' }, icon(w === null ? 'users' : 'trophy', 36)),
        h('h1', titleText),
        h('p.result-reason', sub),
        h('p.small.muted', `${game.topicName} · ${game.round} raund`)),
      h('div.result-compare', col(0), h('span.vs-badge', 'VS'), col(1)),
      h('div.result-actions',
        h('button.btn.accent', { type: 'button', onclick: rematch }, icon('refresh', 16), 'Qayta oʻynash'),
        h('a.btn.primary', { href: '#/games/balloon' }, icon('sparkles', 16), 'Yangi oʻyin')));
  }

  function logText(e) {
    const T = (i) => (i === null || i === undefined ? '' : game.teams[i].name);
    switch (e.t) {
      case 'rps': return [`${T(e.team)} tosh-qaychi-qogʻozda yutdi`, 'rps'];
      case 'skip': return [`${T(e.team)} uchun savol almashtirildi`, 'muted'];
      case 'answer':
        if (e.ok) return [`${T(e.team)} savolga toʻgʻri javob berdi`, 'good'];
        return [`${T(e.team)} ${e.timeout ? 'vaqtida javob bermadi' : e.skipped ? 'javob bera olmadi' : 'notoʻgʻri javob berdi'}`, 'bad'];
      case 'lifeline': {
        const l = LIFELINES.find((x) => x.id === e.lifeline);
        return [`${T(e.team)} «${l ? l.label : e.lifeline}» yordamidan foydalandi`, 'll'];
      }
      case 'roll': return [`${T(e.team)} zar tashladi: ${e.value} → ${T(1 - e.team)}ning ${e.popped} ta shari portladi${e.bonus ? ' (toʻgʻri javob uchun)' : ''}`, 'roll'];
      case 'end':
        if (e.reason === 'popped') return [`${T(1 - e.team)}ning sharlari tugadi — akula yeb qoʻydi! ${T(e.team)} gʻolib`, 'end'];
        return [e.team === null ? 'Oʻyin toʻxtatildi — durang' : `Oʻyin toʻxtatildi — ${T(e.team)} gʻolib`, 'end'];
      default: return ['', 'muted'];
    }
  }

  function renderLog() {
    const open = logBox.open;
    const rounds = new Map();
    for (const e of game.log) {
      if (!rounds.has(e.r)) rounds.set(e.r, []);
      rounds.get(e.r).push(e);
    }
    const items = [];
    for (const [r, list] of [...rounds].reverse()) { // eng so'nggi voqealar yuqorida
      items.push(h('li.bp-log-round', `${r}-raund`));
      for (const e of [...list].reverse()) {
        const [text, kind] = logText(e);
        items.push(h(`li.bp-log-item.${kind}`, e.team !== undefined && e.team !== null ? teamDot(game.teams[e.team].color) : h('span.bp-dot.none'), h('span', text)));
      }
    }
    logBox.replaceChildren(
      h('summary', icon('history', 16), 'Oʻyin jurnali', h('span.badge.neutral', String(game.log.length))),
      items.length ? h('ol.bp-log-list', items) : h('p.small.muted', 'Hali hech narsa sodir boʻlmadi.'));
    logBox.open = open;
  }

  // ------------------------------------------------------------- taymer
  function timerRing() {
    const R = 23;
    const C = 2 * Math.PI * R;
    const wrap = h('div.timer');
    wrap.innerHTML = `<svg viewBox="0 0 56 56" width="56" height="56" aria-hidden="true"><circle class="timer-track" cx="28" cy="28" r="${R}"/><circle class="timer-arc" cx="28" cy="28" r="${R}" stroke-dasharray="${C}" stroke-dashoffset="0" transform="rotate(-90 28 28)"/></svg><span class="timer-num"></span>`;
    const arc = wrap.querySelector('.timer-arc');
    const num = wrap.querySelector('.timer-num');
    ring = {
      el: wrap,
      set(frac, secs) {
        arc.style.strokeDashoffset = String(C * (1 - Math.max(0, Math.min(1, frac))));
        const sec = Math.ceil(secs);
        num.textContent = String(sec);
        wrap.classList.toggle('warn', sec <= 10 && sec > 5);
        wrap.classList.toggle('danger', sec <= 5);
      },
    };
    tick();
    return ring;
  }
  let ring = null;

  function startTimer() {
    if (timerHandle || !game.answerTime || !game.question || game.question.remainingMs === null) return;
    deadline = performance.now() + game.question.remainingMs;
    lastTick = null;
    tick();
    timerHandle = setInterval(tick, 200);
  }

  function stopTimer() {
    clearInterval(timerHandle);
    timerHandle = null;
  }

  function tick() {
    if (!ring || !game || game.phase !== 'question' || !game.answerTime) return;
    const secs = Math.max(0, (deadline - performance.now()) / 1000);
    const total = (game.question && game.question.timeLimitMs ? game.question.timeLimitMs / 1000 : game.answerTime);
    ring.set(secs / total, secs);
    const whole = Math.ceil(secs);
    if (timerHandle && whole <= 5 && whole > 0 && whole !== lastTick) {
      lastTick = whole;
      beep('tick');
    }
    if (timerHandle && secs <= 0) {
      stopTimer();
      answer(null, true);
    }
  }

  // ------------------------------------------------- to'liq ekran, klaviatura
  function setImmersive(on) {
    document.body.classList.toggle('bp-immersive', on);
    fsBtn.replaceChildren(icon(on ? 'minimize' : 'maximize', 18));
    requestAnimationFrame(fit);
  }

  async function toggleFullscreen() {
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => {});
      return;
    }
    if (document.body.classList.contains('bp-immersive')) {
      setImmersive(false);
      return;
    }
    setImmersive(true);
    if (document.fullscreenEnabled) {
      try {
        await document.documentElement.requestFullscreen({ navigationUI: 'hide' });
      } catch {
        /* to'liq ekran ruxsat etilmasa ham sarlavhasiz rejim ishlaydi */
      }
    }
  }

  function onFullscreenChange() {
    setImmersive(!!document.fullscreenElement);
  }

  function onKey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey || !game || document.querySelector('.modal-overlay.show')) return;
    const tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    const k = e.key.toLowerCase();
    if ((k === 'enter' || k === ' ') && (tag === 'BUTTON' || tag === 'A' || tag === 'SUMMARY')) return;
    if (k === 'f') {
      e.preventDefault();
      toggleFullscreen();
      return;
    }
    if (ending || busy || performance.now() - phaseSince < 450) return;
    if (reveal) {
      if (k === 'enter' || k === ' ') {
        e.preventDefault();
        continueAfterReveal();
      }
      return;
    }
    if (game.phase === 'rps') {
      if (k === '1' || k === 'arrowleft') chooseRps(0);
      else if (k === '2' || k === 'arrowright') chooseRps(1);
    } else if (game.phase === 'question') {
      let i = '123456789'.indexOf(k);
      if (i < 0) i = 'abcdefghij'.indexOf(k);
      if (i >= 0 && i < game.question.options.length) {
        e.preventDefault();
        answer(i);
      }
    } else if (game.phase === 'roll' && (k === ' ' || k === 'enter')) {
      e.preventDefault();
      roll();
    } else if (game.phase === 'pop' && k === 'enter') {
      e.preventDefault();
      autoPop();
    }
  }

  async function requestWakeLock() {
    try {
      if ('wakeLock' in navigator && document.visibilityState === 'visible') wakeLock = await navigator.wakeLock.request('screen');
    } catch {
      wakeLock = null;
    }
  }

  function onVisibility() {
    if (document.visibilityState === 'visible' && alive) {
      requestWakeLock();
      // boshqa oynada o'zgargan bo'lishi mumkin — jim holda yangilaymiz
      if (game && !busy && !ending && !optimistic.size && !reveal) {
        api(`/api/balloon/games/${gameId}`).then((res) => {
          if (alive && !busy && !ending && !optimistic.size && !reveal && res.game.rev !== game.rev) {
            game = res.game;
            resync();
          }
        }).catch(() => {});
      }
    }
  }

  document.addEventListener('keydown', onKey);
  document.addEventListener('fullscreenchange', onFullscreenChange);
  document.addEventListener('visibilitychange', onVisibility);
  load();

  return () => {
    alive = false;
    stopTimer();
    ro.disconnect();
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('fullscreenchange', onFullscreenChange);
    document.removeEventListener('visibilitychange', onVisibility);
    document.body.classList.remove('bp-immersive');
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    if (wakeLock) wakeLock.release().catch(() => {});
    root.classList.remove('wide');
  };
}
