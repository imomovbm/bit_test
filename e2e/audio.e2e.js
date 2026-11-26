// Octagon ovozi — brauzerda (Playwright, haqiqiy Chromium Web Audio) Web Audio "josus"i bilan:
//
//   node e2e/audio.e2e.js            (FONTCONFIG_FILE=$PWD/e2e/fonts-ci.conf — CI dagi shriftlar bilan; yo'l to'liq bo'lsin)
//
// Josus (init script) har bir AudioContext yaratilishini (o'sha paytda sahifa bosilganmi — navigator.userActivation),
// manbalar start() vaqtini, chiziqli so'nishlarni va balandlik o'zgarishlarini yozadi; dvigatelning «octagon-audio»
// hodisalari va o'qituvchi ekrani bosqichlari console.debug orqali Node'ga keladi. page.evaluate, lokatorlar va
// exposeBinding javoblari sahifaga «bosish» (user activation) beradi — sahifa yangilangandan keyin ishlatilmaydi.
//
// A) Yuklash: ovoz kodi faqat Octagon o'qituvchi sahifasida (Duel, sozlash sahifasi — «Sinab ko'rish» bosilmaguncha yo'q).
// B) O'yin: musiqa savol ko'ringanda boshlanadi (trek — o'yin urug'idan, savol raqami bo'yicha), vaqt tugaganda yoki hamma
//    javob berganda 300 ms da so'nadi; natija ovozi serverdagi foizdan (ko'p to'g'ri / aralash / ko'p xato / hech kim);
//    tez ketma-ket bosqichlar — ovozlar ustma-ust emas; yashirin oyna; o'chirish va balandlik (saqlanadi); sahifa
//    yangilansa — bosilmaguncha jim, so'ng o'sha trek; muddatidan oldin tugatish; sahifadan chiqish — kontekst yopiladi.
// C) Brauzer ovozni bloklasa: «Ovozni yoqish» (joylashuvni surmaydi), tor ekranlar, sekin protsessor (4x) — uzun vazifa yo'q.
// D) O'quvchi sahifasi: AudioContext yo'q, ovoz kodi yuklanmaydi.
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.OUT || path.join(__dirname, 'screenshots');
const PORT = Number(process.env.PORT || 8781);
const BASE = `http://127.0.0.1:${PORT}`;
const TIME = 8;          // savol vaqti (soniya): oxirgi 5 soniya — 3-soniyadan
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let checks = 0;
function ok(cond, msg) {
  if (!cond) throw new Error(`FAIL: ${msg}`);
  checks += 1;
  console.log(`  ✓ ${msg}`);
}

const QUESTIONS = [
  ['Oʻzbekistonning poytaxti?', ['Toshkent', 'Samarqand', 'Buxoro', 'Xiva'], 0],
  ['2 + 2 × 2 = ?', ['8', '6', '4', '10'], 1],
  ['HTML nima?', ['Dasturlash tili', 'Maʼlumotlar bazasi', 'Belgilash tili', 'Operatsion tizim'], 2],
  ['Eng katta okean?', ['Atlantika', 'Hind', 'Shimoliy Muz', 'Tinch'], 3],
  ['Quyosh qayerdan chiqadi?', ['Sharq', 'Gʻarb', 'Shimol', 'Janub'], 0],
];
const TOPIC = 'Ovoz E2E';
const TOPIC_FILE = QUESTIONS.map(([q, opts, c]) => [q, ...opts.map((o, i) => (i === c ? `#${o}` : o))].join('\n====\n')).join('\n++++\n');

// ------------------------------------------------------------------ server
let server = null;
async function startServer() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'audio-e2e-'));
  const proc = spawn('python3', ['run.py', '--port', String(PORT), '--host', '127.0.0.1', '--db', path.join(dir, 'e2e.db')], {
    cwd: ROOT,
    env: {
      ...process.env, TD_SUPERADMIN_PASSWORD: 'owner123', TD_OCTAGON_INTRO: '1', TD_OCTAGON_READ: '2',
      TD_OCTAGON_PODIUM_INTRO: '2', TD_OCTAGON_REVEAL_STEP: '1.5', TD_OCTAGON_REVEAL_WINNER: '2',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  proc.stdout.on('data', (d) => { log += d; });
  proc.stderr.on('data', (d) => { log += d; });
  server = { proc, log: () => log };
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${BASE}/healthz`)).ok) break;
    } catch {
      /* hali ishga tushmagan */
    }
    await sleep(100);
  }
  const call = async (cookie, method, url, body) => {
    const r = await fetch(BASE + url, { method, headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, cookie: (r.headers.get('set-cookie') || '').split(';')[0] };
  };
  const owner = (await call('', 'POST', '/api/auth/login', { login: 'admin', password: 'owner123' })).cookie;
  if ((await call(owner, 'POST', '/api/admin/users', { login: 'oqituvchi', password: '1234', isTeacher: true })).status !== 201) throw new Error('teacher');
  if ((await call(owner, 'POST', '/api/admin/topics', { name: TOPIC, content: TOPIC_FILE, shuffle: false })).status !== 201) throw new Error('topic');
}

// ------------------------------------------------------------- josus
/** Sahifada ishlaydi (init script): Web Audio chaqiruvlari, dvigatel hodisalari, bosqichlar, uzun vazifalar. */
function audioSpy(block) {
  const S = { contexts: [], starts: [], ramps: [], targets: [], created: 0, closed: 0, long: [], shifts: [] };
  window.__wa = S;
  window.__blockAudio = block;
  // bir tomonlama kanal (console.debug): exposeBinding javobi sahifada evaluate qilinadi — bu sahifaga «bosish» beradi
  const debug = console.debug.bind(console);
  const send = (d) => debug(`[octagon-audio]${JSON.stringify(d)}`);
  window.addEventListener('octagon-audio', (e) => send(e.detail));
  let lastPhase = '';
  let enableShown = false;
  const watch = () => {
    const host = document.querySelector('.oct-host');
    const m = host && host.className.match(/(?:^|\s)phase-([a-z_0-9]+)/);
    if (m && m[1] !== lastPhase) {
      lastPhase = m[1];
      send({ type: 'phase', phase: m[1] });
    }
    const btn = document.querySelector('[data-enable-sound]');
    const shown = !!btn && !btn.hidden;
    if (shown !== enableShown) {
      enableShown = shown;
      send({ type: 'enable-button', shown });
    }
  };
  new MutationObserver(watch).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'hidden'] });
  try {
    new PerformanceObserver((list) => { for (const e of list.getEntries()) S.long.push({ at: e.startTime, ms: e.duration }); }).observe({ type: 'longtask', buffered: true });
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        const el = (n) => (n.nodeType === 1 ? n : n.parentElement);
        // ovoz elementi joyidan surildi (birinchi paydo bo'lishi emas), foydalanuvchi harakatisiz (CLS qoidasi)
        const moved = (e.sources || []).some((x) => x.node && el(x.node) && el(x.node).closest('.oct-sound-box, .oct-enable-sound')
          && x.previousRect && x.previousRect.width > 0 && x.previousRect.height > 0);
        S.shifts.push({
          at: e.startTime, value: e.value, input: e.hadRecentInput, w: innerWidth,
          sound: moved && !e.hadRecentInput,
          src: (e.sources || []).map((x) => `${x.node && el(x.node) ? el(x.node).className : '?'} ${JSON.stringify(x.previousRect)}->${JSON.stringify(x.currentRect)}`),
        });
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch {
    /* kuzatuvchi yo'q — tekshiruv o'tkazib yuboriladi */
  }
  const Real = window.AudioContext;
  if (!Real) return;
  class Spy extends Real {
    constructor(...args) {
      super(...args);
      this.__blocked = !!window.__blockAudio;     // «brauzer ruxsat bermadi»: bosishdan keyin ham to'xtab turadi
      // Octagon dvigateli — latencyHint: 'playback'; boshqasi — ilovaning umumiy tugma ovozlari (lib.js initAudio)
      this.__octagon = !!(args[0] && args[0].latencyHint === 'playback');
      S.created += 1;
      S.contexts.push(this);
      this.__id = S.contexts.length;
      send({ type: 'spy-context', id: this.__id, octagon: this.__octagon, activated: navigator.userActivation ? navigator.userActivation.hasBeenActive : null, opts: args[0] || null });
    }

    get state() {
      return this.__blocked ? 'suspended' : super.state;
    }

    resume() {
      if (window.__blockAudio) return Promise.resolve();
      this.__blocked = false;
      return super.resume();
    }

    close() {
      if (this.__octagon) S.closed += 1;
      send({ type: 'spy-close', id: this.__id });
      return super.close();
    }
  }
  window.AudioContext = Spy;
  const createOsc = BaseAudioContext.prototype.createOscillator;
  BaseAudioContext.prototype.createOscillator = function createOscillator() {
    const n = createOsc.call(this);
    const set = n.frequency.setValueAtTime;
    n.frequency.setValueAtTime = function setValueAtTime(v, t) {
      if (n.__f == null) n.__f = v;
      return set.call(this, v, t);
    };
    return n;
  };
  const start = AudioScheduledSourceNode.prototype.start;
  AudioScheduledSourceNode.prototype.start = function startSpy(when = 0, ...rest) {
    S.starts.push({ ctx: this.context.__id, at: when, now: this.context.currentTime, kind: this instanceof OscillatorNode ? this.type : 'noise', f: this.__f == null ? null : this.__f });
    return start.call(this, when, ...rest);
  };
  const lin = AudioParam.prototype.linearRampToValueAtTime;
  AudioParam.prototype.linearRampToValueAtTime = function linSpy(v, t) {
    S.ramps.push({ v, t });
    return lin.call(this, v, t);
  };
  const target = AudioParam.prototype.setTargetAtTime;
  AudioParam.prototype.setTargetAtTime = function targetSpy(v, t, c) {
    S.targets.push({ v, t });
    return target.call(this, v, t, c);
  };
}

// ------------------------------------------------------------- brauzer
const consoleProblems = [];
const otherWarnings = [];
async function openPage(browser, tag, { width = 1280, mobile = false, block = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 700 ? 760 : 900 }, isMobile: mobile, hasTouch: mobile });
  await ctx.addInitScript(audioSpy, block);
  const page = await ctx.newPage();
  page.tag = tag;
  page.audioLog = [];
  page.requests = [];
  page.frames = [];
  page.on('request', (r) => page.requests.push(r.url()));
  page.on('console', (m) => {
    const text = m.text();
    if (m.type() === 'debug' && text.startsWith('[octagon-audio]')) {
      page.audioLog.push({ ...JSON.parse(text.slice(15)), wall: Date.now() });
      return;
    }
    if (/AudioContext|autoplay|user gesture/i.test(text)) consoleProblems.push(`[${tag}] ${m.type()}: ${text}`);
    else if (m.type() === 'error' && !/status of 40[134]/.test(text)) consoleProblems.push(`[${tag}] ${text}`);
    else if (m.type() === 'warning') otherWarnings.push(`[${tag}] ${text}`);
  });
  page.on('pageerror', (e) => consoleProblems.push(`[${tag}] pageerror ${e.message}`));
  page.on('websocket', (ws) => ws.on('framereceived', (f) => {
    try {
      const msg = JSON.parse(String(f.payload));
      if (msg.t === 'h') page.frames.push({ at: Date.now(), d: msg.d });
    } catch {
      /* JSON emas */
    }
  }));
  return page;
}

const events = (p, type, since = 0) => p.audioLog.filter((e) => e.type === type && e.wall >= since);
async function waitEvent(p, pred, what, timeout = 15000, since = 0) {
  const end = Date.now() + timeout;
  for (;;) {
    const hit = p.audioLog.find((e) => e.wall >= since && pred(e));
    if (hit) return hit;
    if (Date.now() > end) throw new Error(`FAIL: kutilgan hodisa kelmadi — ${what}\n${JSON.stringify(p.audioLog.slice(-12), null, 1)}`);
    await sleep(40);
  }
}
const waitPhase = (p, phase, since = 0, timeout = 20000) => waitEvent(p, (e) => e.type === 'phase' && e.phase === phase, `bosqich ${phase}`, timeout, since);
/** Josus holati; created/closed/states — faqat Octagon kontekstlari (ilovaning umumiy tugma ovozi konteksti — all). */
const spy = (p) => p.evaluate(() => {
  const S = window.__wa;
  const mine = S.contexts.filter((c) => c.__octagon);
  return { all: S.created, created: mine.length, closed: S.closed, starts: S.starts, ramps: S.ramps, targets: S.targets, long: S.long, shifts: S.shifts, states: mine.map((c) => c.state) };
});
const audioRequests = (p) => p.requests.filter((u) => /\/js\/octagon\/audio\.js/.test(u));
const shot = (page, name) => page.screenshot({ path: path.join(OUT, `${name}.png`) });

async function login(page) {
  await page.goto(`${BASE}/#/login`);
  const st = await page.evaluate(async () => (await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login: 'oqituvchi', password: '1234' }),
  })).status);
  if (st !== 200) throw new Error(`login ${st}`);
}

async function createGame(page, settings) {
  return page.evaluate(async ([name, s]) => {
    const { topics } = await (await fetch('/api/octagon/topics')).json();
    const id = topics.find((x) => x.name === name).id;
    const r = await fetch('/api/octagon/games', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topicId: id, ...s }) });
    return (await r.json()).game;
  }, [TOPIC, settings]);
}

async function student(browser, pin, nick, av) {
  const page = await openPage(browser, nick, { width: 375, mobile: true });
  await page.goto(`${BASE}/play/${pin}`);
  await page.waitForSelector('input[autocomplete=nickname]');
  await page.fill('input[autocomplete=nickname]', nick);
  await page.click(`.pl-avatars .pl-av >> nth=${av}`);
  await page.click('.pl-join button[type=submit]');
  await page.waitForSelector('#play.pl-view-game');
  page.nick = nick;
  return page;
}

async function answer(p, option) {
  await p.waitForSelector('#play.pl-phase-question_active', { timeout: 15000 });
  await p.click(`.pl-answer >> nth=${option}`);
  await p.waitForSelector('.pl-lock-tag.on, .pl-phase-question_result', { timeout: 5000 });
}

const lastHost = (p) => {
  const merged = {};
  for (const f of p.frames) Object.assign(merged, f.d);
  return merged;
};
const resultFrame = (p, index) => [...p.frames].reverse().find((f) => f.d.phase === 'question_result' && f.d.index === index);

// ------------------------------------------------------------------ test
(async () => {
  await startServer();
  const audio = await import(pathToFileURL(path.join(ROOT, 'static/js/octagon/audio.js')).href);
  const browser = await chromium.launch();
  try {
    // ================================================================= A
    console.log('A) ovoz kodi faqat kerak boʻlganda yuklanadi; sozlash sahifasi');
    const t = await openPage(browser, 'oqituvchi');
    await login(t);
    await t.goto(`${BASE}/?app#/duel`);
    await t.waitForSelector('.app-header');
    await sleep(500);
    ok(audioRequests(t).length === 0, 'Duel sahifasida ovoz kodi yuklanmadi');
    await t.evaluate(() => { location.hash = '#/games/octagon'; });
    await t.waitForSelector('.oct-setup .oct-sound-field');
    await sleep(400);
    ok(audioRequests(t).length === 0, 'sozlash sahifasi: «Sinab koʻrish» bosilmaguncha ovoz kodi yuklanmaydi');
    const setup = await t.evaluate(() => ({
      pressed: document.querySelector('.oct-sound-box.in-setup [data-sound]').getAttribute('aria-pressed'),
      volume: document.querySelector('.oct-sound-box.in-setup [data-volume]').value,
      label: document.querySelector('.oct-sound-box.in-setup [data-sound]').textContent,
    }));
    ok(setup.pressed === 'true' && setup.volume === '60', `standart: ovoz yoqilgan, balandlik oʻrtacha (${setup.volume}%) — «${setup.label}»`);
    ok(await t.getByRole('button', { name: 'Musiqa va effektlar', exact: false }).count() === 1,
      'sozlash: ovoz tugmasining nomi koʻrinadigan matnini oʻz ichiga oladi (ovozli boshqaruv uchun, A-2)');
    await t.click('[data-sound-test]');
    const test = await waitEvent(t, (e) => e.type === 'sfx', '«Sinab koʻrish» ovozi');
    ok(test.name === 'cheer' && audioRequests(t).length === 1, `«Sinab koʻrish»: ovoz kodi bir marta yuklandi va «${test.name}» chalindi`);
    await t.locator('.oct-sound-box.in-setup [data-volume]').fill('40');
    await sleep(150);
    ok(await t.evaluate(() => localStorage.getItem('td-octagon-volume')) === '40', 'balandlik qurilmada saqlandi (40)');
    ok((await spy(t)).targets.some((x) => Math.abs(x.v - 0.16) < 1e-6), 'balandlik 40% -> kuchaytirish 0,16 (0,4²) — sinov dvigatelida');
    await t.click('.oct-sound-box.in-setup [data-sound]');
    ok(await t.evaluate(() => localStorage.getItem('td-octagon-sound')) === 'off' && await t.isDisabled('[data-sound-test]'), 'oʻchirildi: saqlandi, «Sinab koʻrish» oʻchiq');
    await t.click('.oct-sound-box.in-setup [data-sound]');
    ok(await t.evaluate(() => localStorage.getItem('td-octagon-sound')) === 'on', 'qayta yoqildi');
    await shot(t, 'audio-e2e-setup-1280');

    // ================================================================= B
    console.log('B) oʻyin: 4 oʻquvchi, 5 savol, savol vaqti 8 s');
    const game = await createGame(t, { timeLimit: TIME, questionCount: 5, shuffleQuestions: false, shuffleAnswers: false });
    const pin = game.pin;
    await t.evaluate((p) => { location.hash = `#/games/octagon/${p}`; }, pin);
    await t.waitForSelector('.oct-lobby');
    const ctxOnSetup = (await spy(t)).created;
    const statesAfterSetup = (await spy(t)).states;
    ok(statesAfterSetup.every((s) => s === 'closed'), `sozlash sahifasidan chiqildi: sinov AudioContext yopildi (${statesAfterSetup.join(', ')})`);
    const kids = [];
    for (const [i, n] of ['Anvar', 'Bobur', 'Dilnoza', 'Elyor'].entries()) kids.push(await student(browser, pin, n, i + 2));
    const [anvar, bobur, dilnoza, elyor] = kids;
    await t.waitForFunction(() => document.querySelectorAll('.oct-player').length === 4);
    ok(await t.isVisible('.oct-sound-box.in-bar [data-volume]') && !(await t.isVisible('.oct-sound-box.in-lobby')), '1280px: ovoz tugmasi va slayder panelda (lobbida takrorlanmaydi)');
    ok(!(await t.isVisible('[data-enable-sound]')), 'lobbida «Ovozni yoqish» tugmasi yoʻq (Boshlash bosilishi kutiladi)');
    const host0 = lastHost(t);
    const seed = audio.gameSeed(pin, host0.createdAt);
    const expected = audio.trackOrder(seed, 5);
    ok(JSON.stringify(host0.sounds) === JSON.stringify({ bands: [[60, 'cheer'], [30, 'hmm'], [0, 'oops']], nobody: 'soft' }), 'natija ovozi jadvali serverdan (app/config.py) bir marta keldi');
    ok(expected.every((x, i) => i === 0 || x !== expected[i - 1]), `bu oʻyindagi treklar tartibi: ${expected.join(', ')} (ketma-ket takror yoʻq)`);

    let since = Date.now();
    await t.click('.oct-start');
    const ctxEvent = await waitEvent(t, (e) => e.type === 'spy-context' && e.octagon, 'AudioContext «Boshlash»da', 5000, since);
    ok(ctxEvent.activated === true && ctxEvent.opts && ctxEvent.opts.latencyHint === 'playback', `AudioContext «Boshlash» bosilganda yaratildi (sahifa bosilgan: ${ctxEvent.activated}, latencyHint: playback)`);

    // ---- 1-savol: ko'pchilik to'g'ri, hamma javob berdi -> musiqa darhol so'nadi, «cheer»
    const read1 = await waitPhase(t, 'question_read', since);
    const m1 = await waitEvent(t, (e) => e.type === 'music-start', '1-savol musiqasi', 5000, since);
    ok(m1.index === 0 && m1.track === expected[0], `musiqa savol koʻrinishi bilan boshlandi: ${m1.wall - read1.wall} ms, trek ${m1.track} (${m1.name})`);
    ok(m1.wall - read1.wall < 600, 'musiqa oʻqish bosqichi boshida (600 ms ichida)');
    await sleep(700);
    ok((await spy(t)).starts.filter((s) => s.at >= m1.at - 1e-6).length > 4, 'haqiqiy Web Audio manbalari ishga tushirilmoqda (notalar)');
    await waitPhase(t, 'question_active', since);
    ok(events(t, 'music-start', since).length === 1, 'oʻqishdan javobga oʻtishda musiqa qayta boshlanmadi (uzluksiz)');
    for (const [p, o] of [[anvar, 0], [bobur, 0], [dilnoza, 0], [elyor, 1]]) await answer(p, o);
    await waitPhase(t, 'question_result', since);
    const stop1 = await waitEvent(t, (e) => e.type === 'music-stop', '1-savol musiqasi toʻxtadi', 5000, since);
    const sfx1 = await waitEvent(t, (e) => e.type === 'sfx', '1-savol natija ovozi', 5000, since);
    const r1 = resultFrame(t, 0).d;
    ok(r1.correctPct === 75 && r1.answerRate === 100, `server foizi: ${r1.correctPct}% toʻgʻri, ${r1.answerRate}% javob berdi`);
    ok(stop1.reason === 'phase' && Math.abs(stop1.end - stop1.at - 0.3) < 1e-6, 'hamma javob berdi: musiqa darhol 300 ms da soʻndi');
    ok(sfx1.name === 'cheer' && sfx1.name === audio.pickResultSound(r1, host0.sounds), `≥ 60% -> «${sfx1.name}»`);
    ok(sfx1.at >= stop1.end - 1e-6, `natija ovozi soʻnish tugagach (${sfx1.at.toFixed(3)} ≥ ${stop1.end.toFixed(3)}) — ustma-ust emas`);
    let s1 = await spy(t);
    ok(s1.ramps.some((r) => Math.abs(r.t - stop1.end) < 1e-6 && r.v <= 0.001), 'Web Audio: musiqa yoʻlagida 300 ms chiziqli soʻnish (josus)');
    // natija ovozida shovqin manbai yo'q (cheer/hmm/oops/soft) — so'nishdan keyingi shovqin (baraban) musiqa bo'lardi
    ok(s1.starts.filter((s) => s.kind === 'noise' && s.at >= stop1.end + 0.02 && s.at < stop1.end + 1).length === 0, 'soʻnish tugagach musiqa (baraban) yoʻq');
    ok(s1.starts.some((s) => Math.abs(s.at - sfx1.at) < 0.01), 'natija ovozining manbalari oʻz vaqtida ishga tushdi');

    // ---- 2-savol: aralash, bittasi javob bermaydi -> vaqt tugaydi
    since = Date.now();
    await t.click('[data-next]');
    await waitPhase(t, 'leaderboard', since);
    ok((await waitEvent(t, (e) => e.type === 'sfx', 'reyting ovozi', 3000, since)).name === 'board', 'reyting ekrani: «board» ovozi');
    await sleep(800);
    since = Date.now();
    await t.click('[data-next]');
    const m2 = await waitEvent(t, (e) => e.type === 'music-start', '2-savol musiqasi', 5000, since);
    ok(m2.index === 1 && m2.track === expected[1] && m2.track !== m1.track, `2-savol: trek ${m2.track} (${m2.name}) — oldingisidan boshqa`);
    await waitPhase(t, 'question_active', since);
    const activeAt = Date.now();
    for (const [p, o] of [[anvar, 1], [bobur, 2], [dilnoza, 3]]) await answer(p, o); // Elyor javob bermaydi
    const tense = await waitEvent(t, (e) => e.type === 'tense', 'oxirgi 5 soniya', 9000, since);
    ok(tense.wall - activeAt > 2000 && tense.wall - activeAt < 4200, `oxirgi 5 soniya: temp va «tik» (${tense.wall - activeAt} ms dan keyin)`);
    const stop2 = await waitEvent(t, (e) => e.type === 'music-stop', 'vaqt tugadi', 9000, since);
    const res2 = await waitPhase(t, 'question_result', since, 9000);
    ok(stop2.reason === 'timer' && Math.abs(stop2.end - stop2.at - 0.3) < 1e-6, `vaqt tugadi: musiqa 300 ms da soʻndi (sabab: ${stop2.reason})`);
    ok(Math.abs(res2.wall - (stop2.wall + (stop2.at - stop2.t) * 1000)) < 400, 'soʻnish aynan javob vaqti tugaganda boshlandi (natija ekrani bilan bir vaqtda)');
    const sfx2 = await waitEvent(t, (e) => e.type === 'sfx', '2-savol natija ovozi', 3000, since);
    const r2 = resultFrame(t, 1).d;
    ok(r2.correctPct === 33 && r2.answerRate === 75 && sfx2.name === 'hmm', `${r2.correctPct}% (30–59) -> «${sfx2.name}»; ${r2.answerRate}% javob berdi`);
    s1 = await spy(t);
    ok(s1.ramps.some((r) => Math.abs(r.t - stop2.end) < 1e-6 && r.v <= 0.001), 'Web Audio: vaqt tugashidagi chiziqli soʻnish (josus)');
    ok(s1.starts.filter((s) => s.kind === 'noise' && s.at >= stop2.end + 0.02 && s.at < stop2.end + 1).length === 0, 'soʻnish tugagach musiqa (baraban) yoʻq');

    // ---- tez ketma-ket ikki bosqich: reyting -> darhol keyingi savol
    console.log('B2) tez ketma-ket bosqichlar, yashirin oyna, koʻp xato');
    since = Date.now();
    await t.click('[data-next]');
    await waitPhase(t, 'leaderboard', since);
    await t.click('[data-next]');                         // reyting ovozi tugamasdan
    const m3 = await waitEvent(t, (e) => e.type === 'music-start', '3-savol musiqasi', 5000, since);
    const cut = events(t, 'sfx-cut', since);
    const board = events(t, 'sfx', since).find((e) => e.name === 'board');
    ok(cut.length >= 1 && cut.some((c) => c.name === 'board'), `oldingi ovozlar tez oʻchirildi: ${cut.map((c) => c.name).join(', ')}`);
    ok(m3.at >= Math.max(...cut.map((c) => c.end)) - 1e-6 && m3.at >= board.at, 'yangi musiqa oldingi ovoz oʻchgandan keyin boshlandi (ustma-ust emas)');
    ok(m3.index === 2 && m3.track === expected[2], `3-savol: trek ${m3.track} (${m3.name})`);
    await waitPhase(t, 'question_active', since);
    // yashirin oyna (fon): kontekst to'xtatiladi, tugma chiqmaydi; qaytganda davom etadi
    await t.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await sleep(400);
    let st = await spy(t);
    ok(st.states.at(-1) === 'suspended' && !(await t.isVisible('[data-enable-sound]')), 'oyna yashirildi: ovoz toʻxtatildi (jim, tugmasiz)');
    const startsHidden = st.starts.length;
    await sleep(800);
    ok((await spy(t)).starts.length === startsHidden, 'yashirin oynada nota rejalashtirilmaydi');
    await t.evaluate(() => {
      delete document.hidden;
      delete document.visibilityState;
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await sleep(500);
    st = await spy(t);
    ok(st.states.at(-1) === 'running' && st.starts.length > startsHidden, 'oyna qaytdi: ovoz davom etdi');
    ok(events(t, 'music-start', since).length === 1, 'oʻsha trek davom etdi (qayta boshlanmadi)');
    const before3 = Date.now();
    for (const [p, o] of [[anvar, 2], [bobur, 0], [dilnoza, 1], [elyor, 3]]) await answer(p, o);
    await waitPhase(t, 'question_result', since);
    const sfx3 = await waitEvent(t, (e) => e.type === 'sfx', '3-savol natija ovozi', 3000, before3);
    const r3 = resultFrame(t, 2).d;
    ok(r3.correctPct === 25 && sfx3.name === 'oops', `${r3.correctPct}% (< 30) -> «${sfx3.name}»`);

    // ---- 4-savol: o'chirish va balandlik (saqlanadi), hech kim javob bermaydi
    console.log('B3) ovozni oʻchirish/balandlik, hech kim javob bermadi');
    since = Date.now();
    await t.click('[data-next]');
    await waitPhase(t, 'leaderboard', since);
    await t.click('[data-next]');
    const m4 = await waitEvent(t, (e) => e.type === 'music-start', '4-savol musiqasi', 5000, since);
    await waitPhase(t, 'question_active', since);
    await t.click('.oct-sound-box.in-bar [data-sound]');
    const muted = await waitEvent(t, (e) => e.type === 'music-stop' && e.reason === 'mute', 'oʻchirish', 3000, since);
    ok(!!muted && await t.getAttribute('.oct-sound-box.in-bar [data-sound]', 'aria-pressed') === 'false', 'ovoz oʻchirildi: musiqa toʻxtadi, tugma holati');
    st = await spy(t);
    ok(st.targets.some((x) => x.v === 0), 'Web Audio: umumiy kuchaytirish 0 ga');
    const startsMuted = st.starts.length;
    await sleep(1200);
    ok((await spy(t)).starts.length === startsMuted, 'oʻchirilganda yangi nota yoʻq');
    ok(await t.evaluate(() => localStorage.getItem('td-octagon-sound')) === 'off', 'tanlov qurilmada saqlandi (off)');
    await t.locator('.oct-sound-box.in-bar [data-volume]').fill('30');
    const back = await waitEvent(t, (e) => e.type === 'music-start' && e.wall > muted.wall, 'slayder ovozni yoqdi', 3000, since);
    ok(back.track === m4.track && back.index === 3, `slayder surildi: ovoz yoqildi, oʻsha trek (${back.track}) qaytdi`);
    ok((await spy(t)).targets.some((x) => Math.abs(x.v - 0.09) < 1e-6), 'balandlik 30% -> 0,09 (Web Audio)');
    ok(await t.evaluate(() => [localStorage.getItem('td-octagon-sound'), localStorage.getItem('td-octagon-volume')].join()) === 'on,30', 'saqlandi: on, 30');
    const before4 = Date.now();
    await t.click('button:has-text("Savolni yakunlash")');  // hech kim javob bermadi
    await waitPhase(t, 'question_result', since);
    const sfx4 = await waitEvent(t, (e) => e.type === 'sfx', '4-savol natija ovozi', 3000, before4);
    const r4 = resultFrame(t, 3).d;
    ok(r4.correctPct === null && r4.answerRate === 0 && sfx4.name === 'soft', `hech kim javob bermadi (foiz: ${r4.correctPct}) -> «${sfx4.name}»`);

    // ---- 5-savol: sahifa yangilanadi (bosilmaguncha jim), so'ng muddatidan oldin tugatish
    console.log('B4) savol oʻrtasida sahifa yangilanadi; muddatidan oldin tugatish');
    since = Date.now();
    await t.click('[data-next]');
    await waitPhase(t, 'leaderboard', since);
    await t.click('[data-next]');
    const m5 = await waitEvent(t, (e) => e.type === 'music-start', '5-savol musiqasi', 5000, since);
    await waitPhase(t, 'question_active', since);
    await answer(anvar, 0);
    const reloadAt = Date.now();
    await t.reload(); // bu yerdan «bosish»gacha page.evaluate/locator yo'q — ular sahifaga bosish (activation) beradi
    await waitPhase(t, 'question_active', reloadAt);
    await waitEvent(t, (e) => e.type === 'enable-button' && e.shown, '«Ovozni yoqish» tugmasi', 5000, reloadAt);
    await sleep(600);
    if (events(t, 'spy-context', reloadAt).length || events(t, 'music-start', reloadAt).length) console.log(JSON.stringify(t.audioLog.filter((e) => e.wall >= reloadAt), null, 1));
    ok(events(t, 'spy-context', reloadAt).length === 0 && events(t, 'music-start', reloadAt).length === 0, // hech qanday kontekst
      'yangilangan sahifa: bosilmaguncha AudioContext yoʻq, jim; «Ovozni yoqish» koʻrsatildi');
    ok(!consoleProblems.some((x) => /AudioContext|autoplay/i.test(x)), 'brauzer konsolida autoplay ogohlantirishi yoʻq');
    await t.click('[data-enable-sound]');
    const after = await waitEvent(t, (e) => e.type === 'music-start', 'yangilangandan keyin musiqa', 5000, reloadAt);
    const ctxAfter = events(t, 'spy-context', reloadAt).filter((e) => e.octagon);
    ok(ctxAfter.length === 1 && ctxAfter[0].activated === true, 'AudioContext faqat bosishdan keyin yaratildi');
    ok(after.index === 4 && after.track === m5.track, `oʻsha savol — oʻsha trek (${after.track}, ${after.name})`);
    await waitEvent(t, (e) => e.type === 'enable-button' && !e.shown, 'tugma yashirildi', 3000, reloadAt);
    ok(await t.evaluate(() => [localStorage.getItem('td-octagon-sound'), document.querySelector('.oct-sound-box.in-bar [data-volume]').value].join()) === 'on,30',
      'yangilangandan keyin ham saqlangan sozlama: on, 30%');
    since = Date.now();
    await t.click('.oct-end');
    await t.click('.modal-overlay.show .btn.danger');
    await waitPhase(t, 'podium_intro', since);
    const endStop = await waitEvent(t, (e) => e.type === 'music-stop', 'tugatishda musiqa', 3000, since);
    const roll = await waitEvent(t, (e) => e.type === 'sfx' && e.name === 'roll', 'baraban', 3000, since);
    // tugatish: server savolni yopadi (natija) va darhol g'oliblarga o'tadi — natija ovozi boshlanmasidan o'chiriladi
    const silent = (e) => events(t, 'sfx-cut', since).some((c) => c.name === e.name && c.wall >= e.wall && c.end <= e.at + 1e-6);
    const beforeRoll = events(t, 'sfx', since).filter((e) => e.wall <= roll.wall && e !== roll);
    ok(endStop.reason === 'phase' && beforeRoll.every(silent),
      `muddatidan oldin tugatildi: musiqa soʻndi, «Va gʻoliblar…» baraban sadosi${beforeRoll.length ? ` (yopilgan savol ovozi «${beforeRoll.map((e) => e.name)}» boshlanmasdan oʻchirildi)` : ''}`);
    await waitPhase(t, 'final_results', since, 15000);
    const finalAt = Date.now();
    const fan = events(t, 'sfx', since).filter((e) => !silent(e)).map((e) => e.name);
    ok(fan.join() === 'roll,fanfare3,fanfare2,fanfare1', `eshitilgan ovozlar: ${fan.join(' -> ')}`);
    ok(events(t, 'sfx-cut', since).some((e) => e.name === 'fanfare1'), 'oʻyin tugadi: 1-oʻrin fanfarasi tez oʻchirildi (hammasi jim)');
    await sleep(1500);
    ok(events(t, 'sfx', finalAt).length === 0 && events(t, 'music-start', finalAt).length === 0, 'yakuniy natijalarda yangi ovoz yoʻq');

    // ---- sahifadan chiqish
    since = Date.now();
    await t.evaluate(() => { location.hash = '#/games'; });
    await waitEvent(t, (e) => e.type === 'dispose', 'dvigatel yopildi', 3000, since);
    await sleep(300);
    st = await spy(t);
    ok(st.states.every((s) => s === 'closed') && st.closed === st.created, `sahifadan chiqildi: barcha AudioContext yopildi (${st.closed}/${st.created})`);
    const n = st.starts.length;
    await sleep(800);
    ok((await spy(t)).starts.length === n, 'chiqilgandan keyin nota yoʻq (taymerlar toʻxtagan)');
    ok(ctxOnSetup >= 1, 'jami kontekstlar: sinov + oʻyin + yangilangandan keyingi');
    ok(events(t, 'spy-context').every((e) => e.activated === true), 'har bir AudioContext foydalanuvchi bosgandan keyin yaratilgan');

    // ================================================================= C
    console.log('C) brauzer ovozni bloklaydi; tor ekranlar; sekin protsessor');
    const t2 = await openPage(browser, 'oqituvchi-375', { width: 375, mobile: true, block: true });
    await login(t2);
    const g2 = await createGame(t2, { timeLimit: 20, questionCount: 2, shuffleQuestions: false, shuffleAnswers: false });
    await t2.goto(`${BASE}/?app#/games/octagon/${g2.pin}`);
    await t2.waitForSelector('.oct-lobby');
    const solo = await student(browser, g2.pin, 'Yolgiz', 5);
    await t2.waitForFunction(() => document.querySelectorAll('.oct-player').length === 1);
    ok(!(await t2.isVisible('.oct-sound-box.in-bar [data-volume]')) && await t2.isVisible('.oct-sound-box.in-lobby [data-volume]'),
      '375px: panelda faqat ovoz tugmasi, slayder — lobbida');
    const overflow = async (p) => p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    ok(await overflow(t2) <= 0, '375px lobbi: gorizontal siljish yoʻq');
    await shot(t2, 'audio-e2e-lobby-375');
    for (const w of [360, 768]) {
      await t2.setViewportSize({ width: w, height: w < 700 ? 760 : 900 });
      await sleep(200);
      const bar = await t2.isVisible('.oct-sound-box.in-bar [data-volume]');
      const lobby = await t2.isVisible('.oct-sound-box.in-lobby');
      ok(bar === (w >= 640) && lobby === (w < 640) && await overflow(t2) <= 0, `${w}px: slayder ${bar ? 'panelda' : 'lobbida'}, siljish yoʻq`);
      await shot(t2, `audio-e2e-lobby-${w}`);
    }
    await t2.setViewportSize({ width: 375, height: 760 });
    since = Date.now();
    await t2.click('.oct-start');
    await waitPhase(t2, 'question_read', since);
    await waitEvent(t2, (e) => e.type === 'enable-button' && e.shown, '«Ovozni yoqish» (bloklangan)', 5000, since);
    ok(events(t2, 'music-start', since).length === 0 && events(t2, 'spy-context', since).filter((e) => e.octagon).length === 1, 'brauzer ovozni bloklagan: jim, xato yoʻq, «Ovozni yoqish» tugmasi');
    const layout = await t2.evaluate(() => {
      const btn = document.querySelector('[data-enable-sound]');
      const stage = document.querySelector('.oct-stage').getBoundingClientRect();
      btn.hidden = true;
      const hiddenRect = document.querySelector('.oct-stage').getBoundingClientRect();
      btn.hidden = false;
      return { position: getComputedStyle(btn).position, same: stage.top === hiddenRect.top && stage.height === hiddenRect.height, bottom: btn.getBoundingClientRect().bottom, vh: innerHeight };
    });
    ok(layout.position === 'fixed' && layout.same && layout.bottom <= layout.vh, '«Ovozni yoqish» suzuvchi: sahifa joylashuvi surilmaydi');
    await shot(t2, 'audio-e2e-enable-375');
    await t2.evaluate(() => { window.__blockAudio = false; });
    since = Date.now();
    await t2.click('[data-enable-sound]');
    const unblocked = await waitEvent(t2, (e) => e.type === 'music-start', 'ruxsatdan keyin musiqa', 5000, since);
    ok(unblocked.index === 0, 'ruxsat berildi («Ovozni yoqish»): musiqa boshlandi');
    await waitEvent(t2, (e) => e.type === 'enable-button' && !e.shown, 'tugma yashirildi', 3000, since);
    // sekin noutbuk: protsessor 4 marta sekin — musiqa paytida uzun vazifa (> 50 ms) yo'q
    await waitPhase(t2, 'question_active', since);
    const cdp = await t2.context().newCDPSession(t2);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    const longBefore = (await spy(t2)).long.length;
    const startsBefore = (await spy(t2)).starts.length;
    await sleep(4000);
    const slow = await spy(t2);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
    const longs = slow.long.slice(longBefore);
    const notes = slow.starts.slice(startsBefore).filter((x) => x.ctx === slow.starts.at(-1).ctx);
    const times = [...new Set(notes.map((x) => x.at.toFixed(4)))].map(Number).sort((a, b) => a - b);
    const gap = Math.max(...times.slice(1).map((x, i) => x - times[i]));
    const late = notes.filter((x) => x.at < x.now - 0.005);
    ok(times.length > 12 && times.at(-1) - times[0] > 3, `4x sekin protsessor: musiqa uzluksiz (${notes.length} ta manba, ${times.length} ta zarb, ${(times.at(-1) - times[0]).toFixed(1)} s)`);
    ok(gap < 0.6 && late.length === 0, `notalar oldindan rejalashtirildi: kechikkan yoʻq (${late.length}), eng katta oraliq ${gap.toFixed(2)} s`);
    ok(longs.length === 0, `musiqa paytida uzun vazifa (> 50 ms) yoʻq${longs.length ? `: ${longs.map((x) => Math.round(x.ms)).join(', ')} ms` : ''}`);
    const soundShifts = slow.shifts.filter((x) => x.sound);
    if (soundShifts.length) console.log(JSON.stringify(soundShifts, null, 1));
    ok(soundShifts.length === 0, 'ovoz elementlari sababli joylashuv siljishi (layout shift) yoʻq');
    await answer(solo, 0);
    await waitPhase(t2, 'question_result', since);
    ok((await waitEvent(t2, (e) => e.type === 'sfx', 'bitta oʻyinchi natijasi', 3000, since)).name === 'cheer', 'bitta oʻyinchi, toʻgʻri -> «cheer»');

    // ================================================================= D
    console.log('D) oʻquvchi sahifasi jim');
    for (const k of [...kids, solo]) {
      const s = await spy(k);
      ok(s.created === 0 && k.audioLog.filter((e) => e.type !== 'phase' && e.type !== 'enable-button').length === 0 && audioRequests(k).length === 0,
        `${k.nick}: AudioContext yoʻq, ovoz kodi yuklanmadi`);
    }

    ok(!/Traceback/.test(server.log()), 'server jurnalida xato yoʻq');
    console.log(`\nboshqa ogohlantirishlar: ${otherWarnings.length ? `\n${otherWarnings.join('\n')}` : 'yoʻq'}`);
    console.log(`brauzer xatolari / autoplay ogohlantirishlari: ${consoleProblems.length ? `\n${consoleProblems.join('\n')}` : 'yoʻq'}`);
    if (consoleProblems.length) throw new Error('brauzer konsolida xato yoki autoplay ogohlantirishi bor');
    console.log(`\nHAMMASI OʻTDI: ${checks} ta tekshiruv. Skrinshotlar: ${OUT}`);
  } finally {
    await browser.close();
    if (server) server.proc.kill();
  }
})().catch((e) => {
  console.error(e);
  if (server && /Traceback/.test(server.log())) console.error(`--- server jurnali ---\n${server.log().slice(-4000)}`);
  if (server) server.proc.kill();
  process.exit(1);
});
