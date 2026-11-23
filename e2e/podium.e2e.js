// Octagon: savoldan keyingi o'rin o'zgarishi va g'oliblarni e'lon qilish — brauzerda (Playwright), haqiqiy WebSocket
// trafigi bilan.
//
//   node e2e/podium.e2e.js            (FONTCONFIG_FILE=e2e/fonts-ci.conf — CI dagi shriftlar bilan)
//
// A server — standart ochilish vaqtlari (podium_intro 3 s, 3- va 2-o'rin 3,5 s, 1-o'rin 6 s):
//   * 7 o'quvchi, o'rinlar savoldan savolga o'zgaradi: o'qituvchi reytingida ▲/▼/–/YANGI va son API bilan bir xil,
//     qatorlar eski joyidan yangisiga suriladi (FLIP: Web Animations chaqiruvlari yozib olinadi), «Eng katta sakrash»;
//   * har bir telefonda o'z o'rni va o'zgarishi («▲ 2 → 1-o'rin»), yaqin bo'lsa "N ball oldinda";
//   * oxirgi savol natijasida o'rin yo'q; e'lon 3 -> 2 -> 1 -> natijalar hamma ekranda to'g'ri tartib va vaqtda;
//   * sizib chiqmaslik: har bir kadr (o'quvchilar va o'qituvchi) va har bir qadam oldidan DOM — e'lon qilinmagan o'rin
//     hech qayerda yo'q; podiumdagilar o'z o'rnini faqat e'lon qilinganda, qolganlar — natijalarda ko'radi;
//   * e'lon paytida kech qo'shilgan o'quvchi — faqat e'lon qilinganlarni ko'radi, oxirgi o'rinda.
// B server — uzun qadamlar («Keyingi» bilan o'tiladi):
//   * har bir e'lon bosqichida o'quvchi va o'qituvchi sahifani yangilaydi — o'sha qadam, ortig'i yo'q, dublikat yo'q;
//   * «kamroq harakat»: qatorlar siljimaydi, konfetti yo'q, ustunlar darhol joyida; juda uzun ism «…» bilan, to'liq
//     ism title da; CSV (formula xavfsiz); skrinshotlar.
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.OUT || path.join(__dirname, 'screenshots');
const PORT = Number(process.env.PORT || 8775);
const A = `http://127.0.0.1:${PORT}`;
const B = `http://127.0.0.1:${PORT + 1}`;
const PHASES = ['lobby', 'topic_intro', 'question_read', 'question_active', 'question_result', 'leaderboard',
  'podium_intro', 'reveal_3rd', 'reveal_2nd', 'reveal_1st', 'final_results'];
const FINALE = ['podium_intro', 'reveal_3rd', 'reveal_2nd', 'reveal_1st', 'final_results'];
const TIMINGS = { podium_intro: 3000, reveal_3rd: 3500, reveal_2nd: 3500, reveal_1st: 6000 }; // app/config.py standartlari
const STEP_PLACE = { reveal_3rd: 3, reveal_2nd: 2, reveal_1st: 1 };
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let checks = 0;
function ok(cond, msg) {
  if (!cond) throw new Error(`FAIL: ${msg}`);
  checks += 1;
  console.log(`  ✓ ${msg}`);
}

/** Shu bosqichda e'lon qilingan o'rinlar (app/octagon_flow.revealed_places bilan bir xil qoida). */
function revealed(phase, places) {
  const upto = phase === 'final_results' ? 1 : STEP_PLACE[phase];
  if (!upto) return [];
  return [3, 2, 1].filter((k) => upto <= k && k <= places);
}

const QUESTIONS = [
  ['Oʻzbekistonning poytaxti qaysi shahar?', ['Toshkent', 'Samarqand', 'Buxoro', 'Xiva'], 0],
  ['2 + 2 × 2 nechaga teng?', ['8', '6', '4', '10'], 1],
  ['HTML nima?', ['Dasturlash tili', 'Maʼlumotlar bazasi', 'Belgilash (markup) tili', 'Operatsion tizim'], 2],
];
const TOPIC = 'Podium E2E';
const TOPIC_FILE = QUESTIONS.map(([q, opts, c]) => [q, ...opts.map((o, i) => (i === c ? `#${o}` : o))].join('\n====\n')).join('\n++++\n');

// ------------------------------------------------------------------ server
const servers = [];
async function startServer(port, env) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'podium-e2e-'));
  const proc = spawn('python3', ['run.py', '--port', String(port), '--host', '127.0.0.1', '--db', path.join(dir, 'e2e.db')], {
    cwd: ROOT,
    env: { ...process.env, TD_SUPERADMIN_PASSWORD: 'owner123', TD_OCTAGON_INTRO: '2', TD_OCTAGON_READ: '2', ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  proc.stdout.on('data', (d) => { log += d; });
  proc.stderr.on('data', (d) => { log += d; });
  const base = `http://127.0.0.1:${port}`;
  servers.push({ proc, base, log: () => log });
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${base}/healthz`)).ok) break;
    } catch {
      /* hali ishga tushmagan */
    }
    await sleep(100);
  }
  const call = async (cookie, method, url, body) => {
    const r = await fetch(base + url, { method, headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, cookie: (r.headers.get('set-cookie') || '').split(';')[0] };
  };
  const owner = (await call('', 'POST', '/api/auth/login', { login: 'admin', password: 'owner123' })).cookie;
  if ((await call(owner, 'POST', '/api/admin/users', { login: 'oqituvchi', password: '1234', isTeacher: true })).status !== 201) throw new Error('teacher');
  if ((await call(owner, 'POST', '/api/admin/topics', { name: TOPIC, content: TOPIC_FILE, shuffle: false })).status !== 201) throw new Error('topic');
  return base;
}

// ------------------------------------------------------------- brauzer
const errors = [];
const pages = [];
/** Har bir sahifa: konsol xatolari, barcha WebSocket kadrlari (vaqt bilan), bosqich almashishlari (vaqt bilan) va
 * Web Animations chaqiruvlari (FLIP) yozib olinadi. */
async function openPage(browser, tag, { width = 1280, reduced = false, mobile = false } = {}) {
  const ctx = await browser.newContext({
    viewport: { width, height: width < 700 ? 760 : 900 }, isMobile: mobile, hasTouch: mobile, reducedMotion: reduced ? 'reduce' : 'no-preference', acceptDownloads: true,
  });
  await ctx.addInitScript(() => {
    window.__phases = [];
    window.__anims = [];
    let last = '';
    const seen = () => {
      const el = document.querySelector('#play, .oct-host');
      const m = el && el.className.match(/(?:^|\s)(?:pl-phase-|phase-)([a-z_0-9]+)/);
      if (m && m[1] !== last) {
        last = m[1];
        window.__phases.push([m[1], Date.now()]);
      }
    };
    new MutationObserver(seen).observe(document, { subtree: true, attributes: true, attributeFilter: ['class'], childList: true });
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (keyframes, options) {
      window.__anims.push({ id: this.dataset ? this.dataset.id : null, keyframes: JSON.parse(JSON.stringify(keyframes)), options, at: Date.now() });
      return animate.call(this, keyframes, options);
    };
  });
  const page = await ctx.newPage();
  page.tag = tag;
  page.frames = [];
  page.on('console', (m) => {
    if (m.type() === 'error' && !/status of 40[134]/.test(m.text())) errors.push(`[${tag}] ${m.text()}`);
  });
  page.on('pageerror', (e) => errors.push(`[${tag}] pageerror ${e.message}`));
  page.on('websocket', (ws) => ws.on('framereceived', (f) => page.frames.push({ at: Date.now(), raw: String(f.payload) })));
  pages.push(page);
  return page;
}

async function teacherPage(browser, base, pin, opts = {}) {
  const page = await openPage(browser, opts.tag || 'oqituvchi', opts);
  await page.goto(`${base}/#/login`);
  const st = await page.evaluate(async () => (await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login: 'oqituvchi', password: '1234' }),
  })).status);
  if (st !== 200) throw new Error(`login ${st}`);
  if (pin) {
    await page.goto(`${base}/?app#/games/octagon/${pin}`);
    await page.waitForSelector('.oct-host');
  }
  return page;
}

async function createGame(page, settings) {
  return page.evaluate(async ([name, s]) => {
    const { topics } = await (await fetch('/api/octagon/topics')).json();
    const id = topics.find((x) => x.name === name).id;
    const r = await fetch('/api/octagon/games', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topicId: id, ...s }) });
    return (await r.json()).game;
  }, [TOPIC, settings]);
}

async function student(browser, base, pin, nick, av, width = 375, opts = {}) {
  const page = await openPage(browser, nick, { width, mobile: width < 700, ...opts });
  await page.goto(`${base}/play/${pin}`);
  await page.waitForSelector('input[autocomplete=nickname]');
  await page.fill('input[autocomplete=nickname]', nick);
  await page.click(`.pl-avatars .pl-av >> nth=${av}`);
  await page.click('.pl-join button[type=submit]');
  await page.waitForSelector('#play.pl-view-game');
  page.nick = nick;
  return page;
}

const hostPhase = (p, phase, timeout = 20000) => p.waitForSelector(`.oct-host.phase-${phase}`, { timeout });
const studentPhase = (p, phase, timeout = 20000) => p.waitForSelector(`#play.pl-phase-${phase}`, { timeout });
const apiGame = (p, pin) => p.evaluate(async (x) => (await (await fetch(`/api/octagon/games/${x}`)).json()).game, pin);

async function answer(p, option) {
  await p.click(`.pl-answer >> nth=${option}`);
  await p.waitForSelector('.pl-lock-tag.on, .pl-phase-question_result', { timeout: 5000 });
}

async function noOverflow(page, label) {
  await page.evaluate(() => Promise.all(document.getAnimations().filter((a) => a.effect && a.effect.getTiming().iterations !== Infinity).map((a) => a.finished.catch(() => null))));
  const extra = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ok(extra <= 0, `${label}: gorizontal siljish yoʻq (${extra}px)`);
}

const shot = (page, name) => page.screenshot({ path: path.join(OUT, `${name}.png`) });

function markOf(r) {
  if (r.new) return 'YANGI';
  if (r.d == null) return '';
  if (r.d === 0) return '–';
  return r.d > 0 ? `▲${r.d}` : `▼${-r.d}`;
}

// ------------------------------------------------------------------ test
(async () => {
  await startServer(PORT, {});
  await startServer(PORT + 1, { TD_OCTAGON_PODIUM_INTRO: '60', TD_OCTAGON_REVEAL_STEP: '60', TD_OCTAGON_REVEAL_WINNER: '60' });
  const browser = await chromium.launch();
  try {
    // ================================================================= A
    console.log('A1) 7 oʻquvchi, 3 savol (standart ochilish vaqtlari)');
    const teacher = await teacherPage(browser, A);
    const game = await createGame(teacher, { timeLimit: 20, questionCount: 3, shuffleQuestions: false, shuffleAnswers: false });
    const pin = game.pin;
    await teacher.goto(`${A}/?app#/games/octagon/${pin}`);
    await teacher.waitForSelector('.oct-lobby');
    const names = ['Anvar', 'Bobur', 'Dilnoza', 'Elyor', 'Farida', 'Muhammadabdulazizbek'];
    const [anvar, bobur, dilnoza, elyor, farida, longNick] = await Promise.all(names.map((n, i) => student(browser, A, pin, n, i + 3, [360, 375, 768, 1280, 375, 360][i])));
    const kids = [anvar, bobur, dilnoza, elyor, farida, longNick];
    await teacher.waitForFunction(() => document.querySelectorAll('.oct-player').length === 6);
    await teacher.click('.oct-start');
    await hostPhase(teacher, 'question_active');
    for (const k of kids) await studentPhase(k, 'question_active');

    // 1-savol (to'g'ri — 0): Anvar, Bobur, Dilnoza to'g'ri (shu navbatda), Elyor va Farida xato, uzun ismli javob bermaydi
    for (const [p, o] of [[anvar, 0], [bobur, 0], [dilnoza, 0], [elyor, 1], [farida, 2]]) await answer(p, o);
    await teacher.click('button:has-text("Savolni yakunlash")');
    await hostPhase(teacher, 'question_result');
    for (const k of kids) await studentPhase(k, 'question_result');
    ok((await Promise.all(kids.map((k) => k.$('.pl-move.none')))).every(Boolean), '1-savoldan keyin telefonlarda strelka yoʻq (oldingi reyting yoʻq), faqat oʻrin');
    const ranks1 = await Promise.all(kids.map(async (k) => (await k.textContent('.pl-move-place')).trim()));
    ok(ranks1.join() === '1-oʻrin,2-oʻrin,3-oʻrin,4-oʻrin,5-oʻrin,6-oʻrin', `1-savoldan keyingi oʻrinlar: ${ranks1.join(', ')}`);
    await teacher.click('[data-next]');
    await hostPhase(teacher, 'leaderboard');
    ok(await teacher.$$eval('[data-board] .oct-move', (els) => els.every((e) => e.classList.contains('none') && !e.textContent.trim())) && !(await teacher.$('[data-jump]')),
      '1-savol reytingida strelka va «Eng katta sakrash» yoʻq');
    ok(await teacher.evaluate(() => window.__anims.length) === 0, '1-savol reytingida qatorlar siljimaydi (oʻzgarish yoʻq)');

    console.log('A2) 2-savol: oʻqish paytida kech qoʻshilish, oʻrinlar almashadi');
    await teacher.click('[data-next]');
    await hostPhase(teacher, 'question_read');
    const yangi = await student(browser, A, pin, 'Yangi', 20, 375);
    await studentPhase(yangi, 'question_read');
    await hostPhase(teacher, 'question_active');
    for (const k of [...kids, yangi]) await studentPhase(k, 'question_active');
    // Dilnoza darhol to'g'ri (2 ta to'g'ri — 1-o'ringa), 2,5 s dan keyin uzun ismli, Farida, Elyor to'g'ri; Anvar xato;
    // Bobur va Yangi javob bermaydi
    await answer(dilnoza, 1);
    await sleep(2500);
    for (const [p, o] of [[longNick, 1], [farida, 1], [elyor, 1], [anvar, 3]]) await answer(p, o);
    const boardAt = Date.now();
    await teacher.evaluate(() => { window.__anims = []; });
    await teacher.click('button:has-text("Savolni yakunlash")');
    await hostPhase(teacher, 'question_result');
    for (const k of [...kids, yangi]) await studentPhase(k, 'question_result');
    const expectPhone = {
      Dilnoza: ['▲ 2', '1-oʻrin', '2 oʻringa koʻtarildingiz'], Anvar: ['▼ 1', '2-oʻrin', '1 oʻringa tushdingiz'],
      Bobur: ['▼ 1', '3-oʻrin', '1 oʻringa tushdingiz'], Muhammadabdulazizbek: ['▲ 2', '4-oʻrin', '2 oʻringa koʻtarildingiz'],
      Farida: ['–', '5-oʻrin', 'Oʻrningiz oʻzgarmadi'], Elyor: ['▼ 2', '6-oʻrin', '2 oʻringa tushdingiz'], Yangi: ['YANGI', '7-oʻrin', 'Reytingda birinchi marta'],
    };
    for (const k of [...kids, yangi]) {
      const [mark, place, text] = expectPhone[k.nick];
      const got = await k.evaluate(() => ({
        mark: document.querySelector('.pl-move-mark') ? document.querySelector('.pl-move-mark').textContent : '',
        place: document.querySelector('.pl-move-place').textContent,
        text: document.querySelector('.pl-move-text') ? document.querySelector('.pl-move-text').textContent : '',
        cls: document.querySelector('.pl-move').className,
      }));
      ok(got.mark === mark && got.place === place && got.text === text, `${k.nick}: telefonda «${got.mark} → ${got.place}» — ${got.text}`);
    }
    // Farida uzun ismli o'quvchidan keyin javob bergan (≥ 100 ms) — farq aniq musbat; teng ball bo'lsa satr chiqmaydi
    const behind = await farida.textContent('.pl-behind');
    ok(/^Muhammadabdulazizbek sizdan \d+ ball oldinda$/.test(behind), `yaqin raqib: «${behind}»`);
    const bobBehind = await bobur.$('.pl-behind');
    ok(!bobBehind || /^Anvar sizdan [\d ]+ ball oldinda$/.test(await bobBehind.textContent()), 'Bobur: farq faqat yuqoridagi (Anvar) bilan, teng ballda koʻrsatilmaydi');
    ok(!(await dilnoza.$('.pl-behind')), '1-oʻrindagida "ball oldinda" yoʻq');
    await teacher.click('[data-next]');
    await hostPhase(teacher, 'leaderboard');
    await sleep(1400); // siljish tugasin
    const api2 = await apiGame(teacher, pin);
    const dom2 = await teacher.$$eval('[data-board] > li', (els) => els.map((li) => ({
      id: li.dataset.id, nick: li.querySelector('.oct-rank-nick').textContent, mark: li.querySelector('.oct-move').textContent,
      gain: li.querySelector('.oct-rank-gain').textContent, title: li.querySelector('.oct-rank-nick').title,
    })));
    ok(JSON.stringify(dom2.map((r) => `${r.nick}:${r.mark}`)) === JSON.stringify(api2.leaderboard.map((r) => `${r.nick}:${markOf(r)}`)),
      `oʻqituvchi reytingi API bilan bir xil: ${dom2.map((r) => `${r.nick} ${r.mark}`).join(', ')}`);
    ok(dom2.map((r) => `${r.nick}:${r.mark}`).join() === 'Dilnoza:▲2,Anvar:▼1,Bobur:▼1,Muhammadabdulazizbek:▲2,Farida:–', 'strelka va son: ▲2, ▼1, ▼1, ▲2, –');
    ok(dom2[0].gain.startsWith('+') && dom2[1].gain === '' && dom2[3].gain.startsWith('+'), 'shu savolda olingan ball (+N) koʻrsatildi');
    const jump = await teacher.textContent('[data-jump]');
    ok(/Eng katta sakrash/.test(jump) && /Dilnoza/.test(jump) && /▲2/.test(jump), `«Eng katta sakrash»: «${jump.trim()}» (teng sakrashda — yuqoridagi)`);
    const anims = await teacher.evaluate(() => window.__anims);
    const byId = Object.fromEntries(dom2.map((r) => [r.id, r.nick]));
    const moved = Object.fromEntries(anims.filter((a) => byId[a.id]).map((a) => [byId[a.id], a]));
    const ty = (a) => Number(/translateY\((-?[\d.]+)px\)/.exec(a.keyframes[0].transform)[1]);
    ok(Object.keys(moved).sort().join() === 'Anvar,Bobur,Dilnoza,Muhammadabdulazizbek', `siljigan qatorlar: ${Object.keys(moved).join(', ')} (Farida joyida)`);
    ok(ty(moved.Dilnoza) > 0 && ty(moved.Anvar) < 0 && ty(moved.Bobur) < 0 && ty(moved.Muhammadabdulazizbek) > 0,
      `qatorlar eski joyidan: Dilnoza ${ty(moved.Dilnoza)}px, Anvar ${ty(moved.Anvar)}px, uzun ism ${ty(moved.Muhammadabdulazizbek)}px`);
    ok(Math.abs(ty(moved.Dilnoza) + 2 * ty(moved.Anvar)) < 2, 'Dilnoza 2 qator pastdan, Anvar 1 qator yuqoridan keladi');
    ok(moved.Muhammadabdulazizbek.keyframes[0].opacity === 0, 'top 5 ga tashqaridan kirgan qator ro\'yxat ostidan chiqib keladi');
    ok(Object.values(moved).every((a) => a.options.duration >= 600 && a.options.duration <= 800), `siljish davomiyligi ${moved.Dilnoza.options.duration} ms (600–800)`);
    ok(dom2.find((r) => r.nick === 'Muhammadabdulazizbek').title === 'Muhammadabdulazizbek', 'uzun ism — title da toʻliq');
    await shot(teacher, 'podium-e2e-board-1280');
    ok(Date.now() - boardAt < 60000, 'reyting tez koʻrsatildi');

    console.log('A3) 3-savol (oxirgi): natijada oʻrin yoʻq, reytingsiz gʻoliblarga');
    await teacher.click('[data-next]');
    await hostPhase(teacher, 'question_active');
    for (const k of [...kids, yangi]) await studentPhase(k, 'question_active');
    for (const [p, o] of [[longNick, 2], [farida, 2], [anvar, 0], [bobur, 1]]) await answer(p, o);
    await teacher.click('button:has-text("Savolni yakunlash")');
    await hostPhase(teacher, 'question_result');
    for (const k of [...kids, yangi]) await studentPhase(k, 'question_result');
    const lastResult = await Promise.all([...kids, yangi].map((k) => k.evaluate(() => !document.querySelector('.pl-move, .pl-behind') && !/oʻrin/.test(document.querySelector('.pl-stage').textContent))));
    ok(lastResult.every(Boolean), 'oxirgi savol natijasida telefonlarda oʻrin ham, oʻzgarish ham yoʻq');
    ok(/Gʻoliblar/.test(await teacher.textContent('[data-next]')), 'oʻqituvchi tugmasi — «Gʻoliblar»');
    // e'lon boshlanadi; kutilgan podium: 1 — Dilnoza, 2 — uzun ism, 3 — Farida
    const PODIUM = { 1: 'Dilnoza', 2: 'Muhammadabdulazizbek', 3: 'Farida' };
    const placeOf = (nick) => Number(Object.keys(PODIUM).find((x) => PODIUM[x] === nick)) || 0;
    const everyone = [...kids, yangi];
    // kech qo'shiladigan o'quvchi: sahifa oldindan ochiladi, ism yoziladi — e'lon paytida faqat «kirish» bosiladi
    const late2 = await openPage(browser, 'Kechroq', { width: 375, mobile: true });
    late2.nick = 'Kechroq';
    await late2.goto(`${A}/play/${pin}`);
    await late2.waitForSelector('input[autocomplete=nickname]');
    await late2.fill('input[autocomplete=nickname]', 'Kechroq');
    /** Sahifaning o'z bosqichi va ekrani birga o'qiladi (qadamlar almashayotgan payt ham xato bermaydi): e'lon
     * qilinmagan ism yo'q; podiumdagilar o'z o'rnini faqat e'lon qilinganda ko'radi; ro'yxat — faqat e'lon qilinganlar. */
    const screenCheck = async (p) => {
      const s = await p.evaluate(() => {
        const root = document.querySelector('#play, .oct-host');
        const m = root && root.className.match(/(?:^|\s)(?:pl-phase-|phase-)([a-z_0-9]+)/);
        const top = document.querySelector('.pl-top');
        return {
          phase: m ? m[1] : '',
          text: (document.body.innerText || '').replace(top ? top.innerText : '', ''),
          me: !!document.querySelector('.pl-reveal-me'),
          place: !!document.querySelector('.pl-place'),
          list: [...document.querySelectorAll('.pl-top3 .pl-top3-nick')].map((e) => e.textContent).sort(),
          cols: [...document.querySelectorAll('.oct-col.shown')].map((e) => Number(e.dataset.place)).sort(),
        };
      });
      if (!FINALE.includes(s.phase)) return s;
      ok(!/\b(null|undefined|NaN)\b/.test(s.text), `${s.phase} ${p.tag}: ekranda «null/undefined/NaN» yoʻq`);
      const shown = revealed(s.phase, 3);
      const leak = [1, 2, 3].filter((k) => !shown.includes(k)).map((k) => PODIUM[k]).filter((n) => n !== p.nick && s.text.includes(n));
      ok(leak.length === 0, `${s.phase} ${p.tag}: eʼlon qilinmagan ism ekranda yoʻq${leak.length ? ` — ${leak}` : ''}`);
      if (p === teacher) {
        ok(s.cols.join() === shown.slice().sort().join(), `${s.phase} oʻqituvchi: ochiq oʻrinlar ${s.cols.join(',') || '—'}`);
      } else if (s.phase !== 'final_results') {
        const own = placeOf(p.nick);
        const mine = own > 0 && shown.includes(own);
        ok(s.me === mine && s.place === mine, `${s.phase} ${p.tag}: ${mine ? 'oʻz oʻrni eʼlon qilindi — telefonida' : 'oʻz natijasi hali sir'}`);
        ok(s.list.join() === shown.map((k) => PODIUM[k]).sort().join(), `${s.phase} ${p.tag}: roʻyxatda faqat eʼlon qilinganlar (${s.list.join(', ') || '—'})`);
      }
      return s;
    };
    const checkAll = async () => {
      for (const p of [teacher, ...everyone]) await screenCheck(p);
    };
    await teacher.click('[data-next]');
    await hostPhase(teacher, 'podium_intro');
    const t0 = Date.now();
    await checkAll();
    await hostPhase(teacher, 'reveal_3rd', 8000);
    await late2.click('.pl-join button[type=submit]');        // e'lon paytida qo'shilish
    await late2.waitForSelector('#play.pl-view-game');
    everyone.push(late2);
    const lateView = await screenCheck(late2);
    ok(['reveal_3rd', 'reveal_2nd'].includes(lateView.phase) && lateView.list.join() === revealed(lateView.phase, 3).map((k) => PODIUM[k]).sort().join(),
      `eʼlon paytida qoʻshilgan oʻquvchi (${lateView.phase}) faqat eʼlon qilinganlarni koʻradi: ${lateView.list.join(', ')}`);
    for (const phase of ['reveal_3rd', 'reveal_2nd', 'reveal_1st', 'final_results']) {
      await hostPhase(teacher, phase, 8000);
      for (const k of everyone) await studentPhase(k, phase, 8000);
      await checkAll();
      if (STEP_PLACE[phase]) {
        const place = STEP_PLACE[phase];
        const me = everyone.find((k) => k.nick === PODIUM[place]);
        ok((await me.textContent('.pl-medal b')) === String(place) && /Siz — \d-oʻrin!|gʻolibsiz/.test(await me.textContent('.pl-reveal-me h1')),
          `${phase}: ${me.nick} oʻz oʻrnini (${place}) telefonida koʻrdi`);
        await sleep(1500);
        await checkAll();                                         // qadam o'rtasida ham
      }
    }
    const total = Date.now() - t0;
    ok(total > 15000 && total < 18500, `eʼlon jami ${(total / 1000).toFixed(1)} s (3 + 3,5 + 3,5 + 6 = 16 s)`);

    console.log('A4) tartib va vaqt — hamma ekranda');
    const timelines = await Promise.all([teacher, ...kids, yangi].map(async (p) => [p.tag, (await p.evaluate(() => window.__phases))]));
    for (const [tag, tl] of timelines) {
      const fin = tl.filter(([ph]) => FINALE.includes(ph));
      ok(fin.map(([ph]) => ph).join() === FINALE.join(), `${tag}: ${fin.map(([ph]) => ph).join(' → ')}`);
      const gaps = fin.slice(1).map(([, t], i) => t - fin[i][1]);
      const want = [TIMINGS.podium_intro, TIMINGS.reveal_3rd, TIMINGS.reveal_2nd, TIMINGS.reveal_1st];
      ok(gaps.every((g, i) => Math.abs(g - want[i]) < 700), `${tag}: oraliqlar ${gaps.map((g) => (g / 1000).toFixed(1)).join(' / ')} s (≈ 3 / 3,5 / 3,5 / 6)`);
    }
    const starts = timelines.map(([, tl]) => (tl.find(([ph]) => ph === 'reveal_1st') || [0, 0])[1]);
    ok(Math.max(...starts) - Math.min(...starts) < 1000, `1-oʻrin hamma ekranda bir vaqtda eʼlon qilindi (farq ${Math.max(...starts) - Math.min(...starts)} ms)`);

    console.log('A5) sizib chiqmaslik: haqiqiy WebSocket kadrlari');
    for (const p of [teacher, ...everyone]) {
      const msgs = p.frames.map((f) => ({ ...f, m: JSON.parse(f.raw) }));
      const isTeacher = p === teacher;
      const startIdx = msgs.findIndex(({ m }) => (isTeacher ? m.t === 'h' && m.d.phase === 'question_result' && m.d.index === 2
        : m.t === 's' && PHASES[m.d.p] === 'question_result' && m.d.q === 2) || (m.t === 's' && FINALE.includes(PHASES[m.d.p])) || (m.t === 'h' && FINALE.includes(m.d.phase)));
      ok(startIdx >= 0, `${p.tag}: oxirgi savoldan keyingi kadrlar topildi (${msgs.length - startIdx} ta)`);
      let phase = 'question_result';
      let n = 0;
      for (const { m, raw } of msgs.slice(startIdx)) {
        if (m.t === 's') phase = PHASES[m.d.p];
        else if (m.t === 'h') phase = m.d.phase;
        else if (m.t === 'w') continue; // qayta ulanish/qo'shilish: faqat o'zining ismi
        const shown = revealed(phase, 3);
        for (const k of [1, 2, 3]) {
          if (!shown.includes(k)) ok(!raw.includes(PODIUM[k]) || PODIUM[k] === p.nick, `${p.tag} ${phase}: ${k}-oʻrin (${PODIUM[k]}) kadrda yoʻq`);
        }
        if (m.t === 's') {
          if (phase === 'question_result') ok(!('k' in m.d) && !('dk' in m.d) && !('bh' in m.d), `${p.tag}: oxirgi natija kadrida oʻrin yoʻq`);
          if (FINALE.includes(phase)) {
            ok((m.d.top || []).every((t) => shown.includes(t[0])), `${p.tag} ${phase}: kadrdagi podium faqat eʼlon qilinganlar (${(m.d.top || []).map((t) => t[0]).join(',') || '—'})`);
            if (phase !== 'final_results' && 'k' in m.d) ok(shown.includes(m.d.k) && PODIUM[m.d.k] === p.nick, `${p.tag} ${phase}: oʻz oʻrni (${m.d.k}) faqat eʼlon qilingandan keyin`);
          }
        }
        if (m.t === 'h' && FINALE.includes(phase)) {
          ok((m.d.podium || []).map((r) => r.place).sort().join() === shown.slice().sort().join() && !m.d.leaderboard && (!!m.d.ranking) === (phase === 'final_results'),
            `oʻqituvchi ${phase}: kadrda faqat eʼlon qilingan oʻrinlar`);
        }
        n += 1;
      }
      ok(n > 0, `${p.tag}: ${n} ta kadr tekshirildi`);
    }

    console.log('A6) yakuniy natijalar');
    const fin = await apiGame(teacher, pin);
    ok(fin.ranking.map((r) => r.nick).join() === 'Dilnoza,Muhammadabdulazizbek,Farida,Anvar,Bobur,Elyor,Yangi,Kechroq',
      `reyting: ${fin.ranking.map((r) => `${r.rank}. ${r.nick} ${r.score}`).join(', ')}`);
    for (const k of everyone) {
      const r = fin.ranking.find((x) => x.nick === k.nick);
      const txt = await k.textContent('.pl-place');
      ok(txt.endsWith(`${r.rank}-oʻrin`) && Number((await k.textContent('.pl-points')).replace(/\D/g, '')) === r.score, `${k.nick}: natijalarda ${r.rank}-oʻrin, ${r.score} ball`);
    }
    ok(await teacher.$$eval('[data-ranking] > li', (els) => els.length) === 8 && await teacher.$$eval('[data-ranking] > li.top', (els) => els.length) === 8, 'toʻliq reyting (birinchi 10 tasi ajratilgan)');

    // ================================================================= B
    console.log('B1) uzun qadamlar: har bir bosqichda qayta ulanish; «kamroq harakat»; CSV; uzun ism');
    const tb = await teacherPage(browser, B, null, { tag: 'B-oqituvchi' });
    const gb = await createGame(tb, { timeLimit: 30, questionCount: 3, shuffleQuestions: false, shuffleAnswers: false });
    await tb.goto(`${B}/?app#/games/octagon/${gb.pin}`);
    await tb.waitForSelector('.oct-lobby');
    const trm = await teacherPage(browser, B, gb.pin, { tag: 'B-oqituvchi-rm', reduced: true, width: 1280 });
    const bnames = [['Muhammadabdulazizbek', 360], ['Ali', 375], ['Vali', 360], ['Olim', 768], ['-Soli', 375]];
    const bs = [];
    for (const [n, w] of bnames) bs.push(await student(browser, B, gb.pin, n, bs.length + 7, w, { reduced: n === 'Ali' }));
    await tb.click('.oct-start');
    await hostPhase(tb, 'question_active');
    for (const p of bs) {
      await studentPhase(p, 'question_active');
      await answer(p, 3);                                    // 1-savol: hamma xato, shu navbatda
    }
    await hostPhase(tb, 'question_result');
    await tb.click('[data-next]');
    await hostPhase(tb, 'leaderboard');
    await tb.click('[data-next]');
    await hostPhase(tb, 'question_active');
    for (const p of bs) await studentPhase(p, 'question_active');
    await answer(bs[2], 1);                                  // 2-savol: faqat Vali — 3 -> 1
    await tb.evaluate(() => { window.__anims = []; });
    await trm.evaluate(() => { window.__anims = []; });
    await tb.click('button:has-text("Savolni yakunlash")');
    await tb.click('[data-next]');
    await hostPhase(tb, 'leaderboard');
    await hostPhase(trm, 'leaderboard');
    await sleep(1400);
    ok((await tb.evaluate(() => window.__anims.length)) >= 2, 'oddiy rejim: qatorlar suriladi');
    ok((await trm.evaluate(() => window.__anims.length)) === 0, '«kamroq harakat»: qatorlar surilmaydi');
    const rmMarks = await trm.$$eval('[data-board] .oct-move', (els) => els.map((e) => e.textContent));
    ok(rmMarks[0] === '▲2' && rmMarks[1] === '▼1', `«kamroq harakat»: yakuniy tartib va strelkalar baribir koʻrinadi (${rmMarks.join(' ')})`);
    await shot(trm, 'podium-e2e-board-reduced-motion-1280');
    await tb.click('[data-next]');
    await hostPhase(tb, 'question_active');
    for (const p of bs) await studentPhase(p, 'question_active');
    await sleep(2000);
    await answer(bs[0], 2);                                  // 3-savol: uzun ism 2 s da to'g'ri (≈ 950, Validan kam)
    await sleep(1500);
    await answer(bs[1], 2);                                  // Ali 3,5 s da to'g'ri (≈ 910)
    await tb.click('button:has-text("Savolni yakunlash")');
    await hostPhase(tb, 'question_result');
    await tb.click('[data-next]');
    // kutilgan: 1 — Vali (2-savol, tez), 2 — uzun ism, 3 — Ali
    const BPOD = { 1: 'Vali', 2: 'Muhammadabdulazizbek', 3: 'Ali' };
    let latecomer = null;
    for (const [i, phase] of FINALE.entries()) {
      await hostPhase(tb, phase);
      await hostPhase(trm, phase);
      for (const p of bs) await studentPhase(p, phase);
      const shown = revealed(phase, 3);
      // o'quvchi sahifani yangilaydi (har qadamda boshqasi)
      const p = bs[i % bs.length];
      await p.reload();
      await studentPhase(p, phase);
      const list = await p.$$eval('.pl-top3 li', (els) => els.map((li) => li.querySelector('.pl-top3-n').textContent).sort());
      const own = Number(Object.keys(BPOD).find((x) => BPOD[x] === p.nick));
      if (phase === 'final_results') {
        ok(list.join() === '1,2,3' && /\d+-oʻrin/.test(await p.textContent('.pl-place')), `${phase}: ${p.nick} qayta ulandi — oʻz oʻrni va gʻoliblar`);
      } else {
        ok(list.join() === shown.map(String).sort().join(), `${phase}: ${p.nick} qayta ulandi — faqat eʼlon qilinganlar (${list.join(',') || '—'})`);
        ok(!!(await p.$('.pl-reveal-me')) === !!(own && shown.includes(own)), `${phase}: ${p.nick} — oʻz oʻrni ${own && shown.includes(own) ? 'koʻrinadi' : 'hali sir'}`);
      }
      // o'qituvchi sahifani yangilaydi — o'sha qadam
      await tb.reload();
      await hostPhase(tb, phase);
      if (phase === 'final_results') {
        ok(await tb.$$eval('[data-ranking] > li', (els) => els.length) === bs.length, `${phase}: oʻqituvchi qayta ulandi — toʻliq reyting (${bs.length} ta)`);
      } else {
        const cols = await tb.$$eval('.oct-col.shown', (els) => els.map((e) => [Number(e.dataset.place), e.classList.contains('up')]));
        ok(cols.length === shown.length && cols.every(([k, up]) => !up || k === STEP_PLACE[phase]),
          `${phase}: oʻqituvchi qayta ulandi — ${shown.length} ta oʻrin joyida (oldingi qadamlar qayta koʻtarilmadi)`);
      }
      const g = await apiGame(tb, gb.pin);
      ok(g.phase === phase && g.playerCount === bs.length, `${phase}: qayta ulanishlar dublikat yaratmadi (${g.playerCount} oʻyinchi)`);
      if (phase === 'reveal_2nd') {
        latecomer = await student(browser, B, gb.pin, 'Kechikkan', 2, 375);
        await studentPhase(latecomer, 'reveal_2nd');
        const seen = await latecomer.$$eval('.pl-top3 li .pl-top3-nick', (els) => els.map((e) => e.textContent).sort());
        ok(seen.join() === 'Ali,Muhammadabdulazizbek', `reveal_2nd: kech qoʻshilgan — faqat eʼlon qilinganlar: ${seen.join(', ')}`);
        bs.push(latecomer);
      }
      if (phase === 'reveal_2nd' || phase === 'reveal_1st') {
        // juda uzun ism: «…» bilan, to'liq ism — title; sahifa kengligidan chiqmaydi
        const fit = await tb.$eval('.oct-col[data-place="2"] .oct-step-nick', (e) => ({ title: e.title, cut: e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1, w: e.getBoundingClientRect().right <= innerWidth }));
        ok(fit.title === 'Muhammadabdulazizbek' && fit.w, `uzun ism podiumda sigʻdi (kesilgan: ${fit.cut ? 'ha, «…»' : 'yoʻq'}), toʻliq ism title da`);
      }
      if (phase === 'reveal_1st') {
        ok(!!(await tb.$('.oct-col.place-1 .oc-burst')) || !!(await tb.$('.oct-col.place-1.landed')), '1-oʻrin: konfetti (oddiy rejim)');
        ok(!(await trm.$('.oc-burst')), '«kamroq harakat»: konfetti yoʻq');
        const winner = bs.find((x) => x.nick === 'Vali');
        await winner.waitForSelector('.pl-reveal-me');
        await shot(winner, 'podium-e2e-student-winner-360');
        await noOverflow(winner, 'gʻolib telefoni 360px (konfetti sahifani kengaytirmaydi)');
        await noOverflow(tb, 'oʻqituvchi 1-oʻrin (konfetti sahifani kengaytirmaydi)');
        await shot(trm, 'podium-e2e-reveal-1st-reduced-motion-1280');
        const ali = bs.find((x) => x.nick === 'Ali');
        ok(await ali.$eval('.pl-reveal-me .pl-medal', (e) => getComputedStyle(e).animationName === 'none'), '«kamroq harakat»: oʻquvchi kartasi animatsiyasiz');
        await noOverflow(bs[0], 'uzun ismli oʻquvchi 360px (2-oʻrin kartasi)');
        await shot(bs[0], 'podium-e2e-student-long-name-360');
      }
      if (phase !== 'final_results') await tb.click('[data-next]');
    }
    console.log('B2) CSV va qidiruv');
    const [download] = await Promise.all([tb.waitForEvent('download'), tb.click('[data-csv]')]);
    const csv = fs.readFileSync(await download.path(), 'utf8');
    const rows = csv.replace(/^﻿/, '').trim().split(/\r\n/);
    ok(rows[0] === 'Ism,Avatar,Ball,Oʻrin,Toʻgʻri javoblar' && rows.length === bs.length + 1, `CSV: sarlavha va ${rows.length - 1} ta qator`);
    ok(rows[1].startsWith('Vali,') && rows[1].endsWith(',1,1'), `CSV 1-qator: ${rows[1]}`);
    ok(rows.some((r) => r.startsWith("'-Soli,")), "CSV: formula sifatida ochilmaydi («-Soli» -> «'-Soli»)");
    const bfin = await apiGame(tb, gb.pin);
    for (const r of bfin.ranking) ok(rows.some((line) => line.includes(`,${r.score},${r.rank},${r.correct}`)), `CSV: ${r.nick} — ${r.score} ball, ${r.rank}-oʻrin`);

    console.log('B3) oʻquvchi chiqib ketsa — yakuniy natijalar qayta chizilmaydi (qidiruv, aylantirish va fokus saqlanadi)');
    await tb.evaluate(() => { document.querySelector('[data-ranking]').__keep = true; });
    const onlineBefore = await tb.getAttribute('.oct-count', 'title');
    const leaving = bs.find((x) => x.nick === 'Olim');
    await leaving.context().close();
    await tb.waitForFunction((t) => document.querySelector('.oct-count').title !== t, onlineBefore);
    ok(await tb.evaluate(() => document.querySelector('[data-ranking]').__keep === true),
      `oʻquvchi chiqib ketdi (${await tb.getAttribute('.oct-count', 'title')}): roʻyxat oʻsha element — qayta chizilmadi`);

    for (const s of servers) ok(!/Traceback/.test(s.log()), `${s.base}: server jurnalida xato yoʻq`);
    console.log(`\nbrauzer xatolari: ${errors.length ? `\n${errors.join('\n')}` : 'yoʻq'}`);
    if (errors.length) throw new Error('brauzer konsolida xatolar bor');
    console.log(`\nHAMMASI OʻTDI: ${checks} ta tekshiruv. Skrinshotlar: ${OUT}`);
  } finally {
    await browser.close();
    for (const s of servers) s.proc.kill();
  }
})().catch((e) => {
  console.error(e);
  for (const s of servers) {
    if (/Traceback/.test(s.log())) console.error(`--- ${s.base} jurnali ---\n${s.log().slice(-4000)}`);
  }
  process.exit(1);
});
