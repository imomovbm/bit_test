// Octagon (v2) va «O'yinlar» paneli — brauzerda to'liq tekshiruv (Playwright).
//
// Ishga tushirish (loyiha ildizidan):  node e2e/octagon.e2e.js
// Talab: Node.js va Playwright (npm i -D playwright && npx playwright install chromium). Ilovaning o'ziga kerak emas.
// Skript o'zi vaqtinchalik bazalar bilan ikkita server ishga tushiradi (asosiy — haqiqiy 5 s mavzu va 5 s o'qish
// vaqtlari bilan; dizayn — uzun bosqichlar bilan, skrinshotlar shoshilmasdan olinadi va «O'tkazib yuborish» bosiladi),
// akkauntlar va mavzular yaratadi, so'ng tekshiradi:
//   * rollar: o'qituvchi/admin «O'yinlar»ni ko'radi, oddiy foydalanuvchi ko'rmaydi va to'g'ridan-to'g'ri havoladan qaytariladi;
//   * qo'shilish: QR havola (ism maydoni darhol) va PIN orqali, ism + avatar (biri oldindan tanlangan), lobbida avatarni
//     almashtirish; band ism rad etilganda yozilgan ism va avatar saqlanadi (audit V2-F8);
//   * «Boshlash»dan keyin mavzu nomi o'qituvchi va hamma o'quvchilarda 5 s, har savol oldidan 5 s o'qish (savol matni
//     faqat o'qituvchida, tugmalar yopiq, soxta javob serverda «early»), so'ng javob taymeri; ballar va reyting to'g'ri;
//   * avatar hamma joyda: lobbi, o'quvchi ekrani, natija, reyting, g'oliblar va yakuniy natijalar (o'qituvchi va o'quvchi);
//   * kech qo'shilish va sahifani yangilash mavzu, o'qish va javob paytida — o'sha ism, avatar, ball, dublikatsiz;
//   * ikkinchi oyna, tarmoq uzilishi, qo'shilishni yopish, XSS, eskirgan yozuv, o'quvchiga kelgan xabarlarda matn yo'q;
//   * qurilmadagi ma'lumotni o'zgartirish (ism/avatar/ball/rol, boshqa o'yinchining ID si, soxta soat) hech narsani o'zgartirmaydi;
//   * statik fayllar haqiqiy trafikda: immutable kesh va gzip; o'quvchi sahifasi ilova kodini yuklamaydi;
//   * bosib turilgan Probel kirish/o'qishni o'tkazib yubormaydi (V2-F9); uzun mavzu nomi (V2-F10); «O'yinlar» panelidagi
//     bosqich nomlari (V2-F11);
//   * 360, 375, 768 va 1280 px: barcha bosqichlar (lobbi, mavzu, o'qish, javob, natija, reyting strelkalar bilan,
//     g'oliblarni e'lon qilishning har bir qadami, yakuniy natijalar) o'qituvchi va o'quvchi ekranlarida — gorizontal
//     siljish yo'q, matnlar kesilmagan, ≥ 12 px, tugmalar ≥ 48 px; skrinshotlar.
// O'rin o'zgarishi va g'oliblarni e'lon qilishning batafsil tekshiruvi (tartib, vaqt, sizib chiqmaslik) — e2e/podium.e2e.js.
// Skrinshotlar: e2e/screenshots/ (yoki OUT muhit o'zgaruvchisi). Brauzer konsolidagi har qanday xato testni yiqitadi.
// DESIGN_ONLY=1 — faqat dizayn bo'limlari (24–25: barcha kengliklar, g'oliblar, uzun mavzu) — maketni tez qayta tekshirish uchun.
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.OUT || path.join(__dirname, 'screenshots');
const PORT = Number(process.env.PORT || 8765);
const BASE = `http://127.0.0.1:${PORT}`;
const DESIGN_PORT = PORT + 1;
const DESIGN = `http://127.0.0.1:${DESIGN_PORT}`;
const TIME = 7;                 // savol vaqti (soniya) — maxsus qiymat sifatida kiritiladi
const INTRO = 5;                // spetsifikatsiya: mavzu nomi 5 s
const READ = 5;                 // spetsifikatsiya: savolni o'qish 5 s
const WIDTHS = [360, 375, 768, 1280];
const DESIGN_ONLY = process.env.DESIGN_ONLY === '1';
const AVATARS = [...fs.readFileSync(path.join(ROOT, 'static/js/octagon/common.js'), 'utf8')
  .match(/export const AVATARS = \[([\s\S]*?)\];/)[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let checks = 0;
function ok(cond, msg) {
  if (!cond) throw new Error(`FAIL: ${msg}`);
  checks += 1;
  console.log(`  ✓ ${msg}`);
}

const QUESTIONS = [
  ['Oʻzbekistonning poytaxti qaysi shahar?', ['Toshkent', 'Samarqand', 'Buxoro', 'Xiva'], 0],
  ['2 + 2 × 2 nechaga teng?', ['8', '6', '4', '10'], 1],
  ['HTML nima?', ['Dasturlash tili', 'Maʼlumotlar bazasi', 'Belgilash (markup) tili', 'Operatsion tizim'], 2],
  ['Yer Quyosh atrofida aylanadimi?', ['Yoʻq', 'Ha'], 1],
  ['Qaysi biri tub son?', ['9', '15', '21', '13', '27'], 3],
  ['Python qaysi yili yaratilgan?', ['2005', '1975', '2015', '1991'], 3],
];
const CORRECT = Object.fromEntries(QUESTIONS.map(([q, opts, c]) => [q, opts[c]]));
const ALL_TEXTS = QUESTIONS.flatMap(([q, opts]) => [q, ...opts.filter((o) => o.length > 3)]);
const TOPIC_FILE = QUESTIONS.map(([q, opts, c]) => [q, ...opts.map((o, i) => (i === c ? `#${o}` : o))].join('\n====\n')).join('\n++++\n');
const TOPIC = 'Octagon E2E';
const LONG_TOPIC = 'Informatika va axborot texnologiyalari: algoritmlar, dasturlash asoslari, maʼlumotlar tuzilmalari va tarmoqlar';

// ------------------------------------------------------------------ server
const servers = [];
async function startServer(port, env = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'octagon-e2e-'));
  const proc = spawn('python3', ['run.py', '--port', String(port), '--host', '127.0.0.1', '--db', path.join(dir, 'e2e.db')], {
    cwd: ROOT,
    env: { ...process.env, TD_SUPERADMIN_PASSWORD: 'owner123', TD_OCTAGON_INTRO: String(INTRO), TD_OCTAGON_READ: String(READ), ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  proc.stdout.on('data', (d) => { log += d; });
  proc.stderr.on('data', (d) => { log += d; });
  const base = `http://127.0.0.1:${port}`;
  const server = { proc, base, log: () => log };
  servers.push(server);
  for (let i = 0; i < 100; i++) {
    try {
      const r = await fetch(`${base}/healthz`);
      if (r.ok) return server;
    } catch {
      /* hali ishga tushmagan */
    }
    await sleep(100);
  }
  throw new Error(`server ishga tushmadi:\n${log}`);
}

async function apiAs(cookie, method, url, body, base = BASE) {
  const r = await fetch(base + url, {
    method,
    headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: r.status, data: await r.json().catch(() => null), cookie: (r.headers.get('set-cookie') || '').split(';')[0] };
}

async function seed(base = BASE) {
  const owner = (await apiAs('', 'POST', '/api/auth/login', { login: 'admin', password: 'owner123' }, base)).cookie;
  for (const u of [{ login: 'oqituvchi', isTeacher: true }, { login: 'zam_admin', isAdmin: true }, { login: 'talaba' }]) {
    const r = await apiAs(owner, 'POST', '/api/admin/users', { password: '1234', ...u }, base);
    if (r.status !== 201) throw new Error(`user ${u.login}: ${r.status}`);
  }
  const t = await apiAs(owner, 'POST', '/api/admin/topics', { name: TOPIC, content: TOPIC_FILE, shuffle: false }, base);
  if (t.status !== 201) throw new Error(`topic: ${t.status}`);
  return owner;
}

// ------------------------------------------------------------- brauzer
const errors = [];
function watch(page, tag) {
  page.on('console', (m) => {
    if (m.type() === 'error' && !/status of 40[134]/.test(m.text())) errors.push(`[${tag}] ${m.text()}`);
  });
  page.on('pageerror', (e) => errors.push(`[${tag}] pageerror ${e.message}`));
}

async function loginPage(browser, login, viewport = { width: 1280, height: 800 }, base = BASE) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  watch(page, login);
  await page.goto(`${base}/#/login`);
  const st = await page.evaluate(async (l) => (await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login: l, password: l === 'admin' ? 'owner123' : '1234' }),
  })).status, login);
  if (st !== 200) throw new Error(`${login}: login ${st}`);
  return page;
}

async function studentPage(browser, width, tag, contextOptions = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 700 ? 760 : 1024 }, isMobile: width < 700, hasTouch: true, ...contextOptions });
  const page = await ctx.newPage();
  watch(page, tag);
  const frames = [];
  page.on('websocket', (ws) => ws.on('framereceived', (f) => frames.push(String(f.payload))));
  page.frames = frames;
  page.loaded = [];
  page.on('response', async (r) => {
    const body = await r.body().catch(() => Buffer.alloc(0));
    const h = r.headers();
    page.loaded.push({ url: new URL(r.url()).pathname, bytes: body.length, cache: h['cache-control'] || '', enc: h['content-encoding'] || '', status: r.status() });
  });
  return page;
}

/** Ism va avatar tanlab qo'shilish (avatar — AVATARS dagi indeks). */
async function joinAs(page, nick, av) {
  await page.waitForSelector('input[autocomplete=nickname]');
  await page.fill('input[autocomplete=nickname]', nick);
  if (av != null) await page.click(`.pl-avatars .pl-av >> nth=${av}`);
  await page.click('.pl-join button[type=submit]');
}

/** Kirish animatsiyalari (masshtab) tugashini kutadi — o'lchamlar animatsiya o'rtasida o'lchanmasin. */
async function settle(page) {
  await page.evaluate(() => Promise.all(document.getAnimations()
    .filter((a) => a.effect && a.effect.getTiming().iterations !== Infinity)
    .map((a) => a.finished.catch(() => null))));
}

async function noOverflow(page, label) {
  await settle(page);
  const extra = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ok(extra <= 0, `${label}: gorizontal siljish yoʻq (${extra}px)`);
}

/** Yangi ekranlardagi bosiladigan elementlar kamida 48×48 px (telefon uchun). */
async function tapTargets(page, scope, label) {
  await settle(page);
  const small = await page.evaluate((sel) => {
    const out = [];
    for (const root of document.querySelectorAll(sel)) {
      const els = root.querySelectorAll('button, a[href], select, summary, label.check, input:not([type=checkbox]):not([type=radio])');
      for (const el of els) {
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        if (!r.width || !r.height || st.visibility === 'hidden' || el.closest('[hidden]')) continue;
        if (r.height < 47.5 || r.width < 47.5) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join('.')} ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
    }
    return out;
  }, scope);
  ok(small.length === 0, `${label}: bosiladigan elementlar ≥ 48px${small.length ? ` — kichik: ${small.join(', ')}` : ''}`);
}

/** Asosiy matnlar kesilmagan: mazmun o'z qutisiga sig'adi va ekran kengligidan chiqmaydi. */
async function notClipped(page, selectors, label) {
  await settle(page);
  const bad = await page.evaluate((sel) => {
    const out = [];
    for (const el of document.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height || el.closest('[hidden]')) continue;
      const cut = el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
      const outside = r.left < -0.5 || r.right > window.innerWidth + 0.5;
      if (cut || outside) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join('.')} «${el.textContent.trim().slice(0, 24)}»`);
    }
    return out;
  }, selectors);
  ok(bad.length === 0, `${label}: matnlar kesilmagan${bad.length ? ` — ${bad.join(', ')}` : ''}`);
}

/** Podium: ko'rinadigan har bir medal o'z ustuni ichida (ustundan pastga yoki yon tomonga chiqmaydi). */
async function medalsInside(page, label) {
  await settle(page);
  const bad = await page.evaluate(() => [...document.querySelectorAll('.oct-col')].flatMap((col) => {
    const medal = col.querySelector('.oct-col-bar .oct-medal');
    const st = medal && getComputedStyle(medal);
    if (!medal || st.visibility === 'hidden' || st.display === 'none') return [];
    const m = medal.getBoundingClientRect();
    const b = col.querySelector('.oct-col-bar').getBoundingClientRect();
    return m.bottom > b.bottom + 0.5 || m.left < b.left - 0.5 || m.right > b.right + 0.5 ? [`${col.dataset.place}-oʻrin`] : [];
  }));
  ok(bad.length === 0, `${label}: medallar ustun ichida${bad.length ? ` — chiqib ketgan: ${bad.join(', ')}` : ''}`);
}

/** Ismdagi so'zlar o'rtasidan bo'linmagan (har bir so'z bitta qatorda) — masalan «Madinabon / u» emas. */
async function wordsWhole(page, selectors, label) {
  await settle(page);
  const split = await page.evaluate((sel) => {
    const out = [];
    for (const el of document.querySelectorAll(sel)) {
      const node = el.firstChild;
      if (!node || node.nodeType !== Node.TEXT_NODE || !el.getBoundingClientRect().width) continue;
      let at = 0;
      for (const word of node.textContent.split(' ')) {
        const r = document.createRange();
        r.setStart(node, at);
        r.setEnd(node, at + word.length);
        const tops = new Set([...r.getClientRects()].map((x) => Math.round(x.top)));
        if (tops.size > 1) out.push(word);
        at += word.length + 1;
      }
    }
    return out;
  }, selectors);
  ok(split.length === 0, `${label}: soʻzlar oʻrtasidan boʻlinmagan${split.length ? ` — ${split.join(', ')}` : ''}`);
}

/** O'qiladigan matn: ko'rinadigan matnlar kamida 12 px. */
async function readableText(page, scope, label) {
  await settle(page);
  const small = await page.evaluate((sel) => {
    const out = [];
    for (const root of document.querySelectorAll(sel)) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const el = n.parentElement;
        if (!n.textContent.trim() || !el || el.closest('[hidden]')) continue;
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const size = parseFloat(getComputedStyle(el).fontSize);
        if (size < 12) out.push(`«${n.textContent.trim().slice(0, 20)}» ${size}px`);
      }
    }
    return out;
  }, scope);
  ok(small.length === 0, `${label}: matnlar ≥ 12px${small.length ? ` — kichik: ${small.join(', ')}` : ''}`);
}

/** Boshqaruv elementi ekranda, aylantirmasdan ko'rinadi va hech narsa ustini yopmagan. */
async function visibleControl(page, sel, label) {
  const okay = await page.evaluate((s) => {
    const c = document.querySelector(s);
    if (!c) return false;
    const b = c.getBoundingClientRect();
    const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    return b.bottom <= innerHeight && !!hit && (hit === c || c.contains(hit));
  }, sel);
  ok(okay, `${label}: ${sel} aylantirmasdan koʻrinadi`);
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false });
}

async function studentPin(page) {
  return (await page.textContent('.pl-pin b')).replace(/\s/g, '');
}

async function hostPin(page) {
  return (await page.textContent('.oct-pin b')).replace(/\s/g, '');
}

async function tileTexts(host) {
  return host.$$eval('.oct-tile-text', (els) => els.map((e) => e.textContent));
}

async function apiGame(page, pin) {
  return page.evaluate(async (p) => (await (await fetch(`/api/octagon/games/${p}`)).json()).game, pin);
}

async function myAvatar(page) {
  return page.textContent('.pl-me .pl-avatar');
}

let twoChecked = false;
/** 2 variantli (ha/yo'q) savol qaysi raundga tushmasin — maketi tekshiriladi. */
async function checkTwoOptions(tiles, teacher, students) {
  if (tiles.length !== 2 || twoChecked) return;
  twoChecked = true;
  for (const [p, w] of students) {
    await studentPhase(p, 'question_active');
    ok((await p.$$('.pl-answer')).length === 2, `ha/yoʻq savol ${w}px: 2 ta katta tugma`);
    await noOverflow(p, `ha/yoʻq savol ${w}px`);
    await shot(p, `student-question-2opts-${w}`);
  }
  await shot(teacher, 'question-2opts-1280');
}

async function answer(student, index) {
  await student.click(`.pl-answer >> nth=${index}`);
  await student.waitForSelector('.pl-phase-question_active .pl-shape, .pl-phase-question_result', { timeout: 5000 });
}

async function hostPhase(host, phase, timeout = 15000) {
  await host.waitForSelector(`.oct-host.phase-${phase}`, { timeout });
}

async function studentPhase(student, phase, timeout = 15000) {
  await student.waitForSelector(`#play.pl-phase-${phase}`, { timeout });
}

async function score(student) {
  return Number((await student.textContent('.pl-score')).replace(/\D/g, ''));
}

async function createGame(page, body) {
  return page.evaluate(async (b) => {
    const { topics } = await (await fetch('/api/octagon/topics')).json();
    const id = topics.find((x) => x.name === b.topic).id;
    const r = await fetch('/api/octagon/games', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topicId: id, ...b.settings }) });
    return (await r.json()).game;
  }, body);
}

// ------------------------------------------------------------------ test
(async () => {
  await startServer(PORT);
  const browser = await chromium.launch();
  try {
    await seed();

    if (!DESIGN_ONLY) { // DESIGN_ONLY=1 — faqat dizayn bo'limi (24–25): tez qayta tekshirish uchun
      console.log('0) bosh administrator oʻqituvchi rolini beradi va oladi');
      const owner = await loginPage(browser, 'admin');
      await owner.goto(`${BASE}/?app#/admin/users`);
      await owner.waitForSelector('.adm-filters');
      await owner.click('button:has-text("Foydalanuvchi qoʻshish")');
      await owner.waitForSelector('.modal-overlay.show input');
      await owner.fill('.modal input[type=text]:not(.mono)', 'yangi_ustoz');
      await owner.click('.modal label.adm-role:has-text("Oʻqituvchi")');
      await owner.click('.modal-foot .btn.primary');
      await owner.waitForSelector('.cred-box');
      await owner.click('.modal-foot .btn.primary');
      await owner.waitForSelector('.modal-overlay', { state: 'detached' });
      await owner.click('.adm-filter:has-text("Oʻqituvchilar")');
      await owner.waitForFunction(() => document.querySelectorAll('.adm-users tbody tr').length === 2);
      const teachers = await owner.$$eval('.adm-users tbody tr .adm-row-title span.ellipsis', (els) => els.map((e) => e.textContent).sort());
      ok(JSON.stringify(teachers) === JSON.stringify(['oqituvchi', 'yangi_ustoz']), `«Oʻqituvchilar» filtri: ${teachers.join(', ')} (yaratishda rol tanlandi)`);
      await owner.click('.adm-filter:has-text("Hammasi")');
      const student = await loginPage(browser, 'talaba');
      await student.goto(`${BASE}/?app#/duel`);
      await student.waitForSelector('.app-header');
      ok(!(await student.$('a[data-nav="games"]')), 'talaba: «Oʻyinlar» yoʻq');
      const row = owner.locator('.adm-users tbody tr', { hasText: 'talaba' });
      await row.locator('button[title="Oʻqituvchi qilish"]').click();
      await owner.click('.modal-foot .btn.primary');
      await student.waitForSelector('a[data-nav="games"]', { timeout: 5000 });
      ok(true, 'rol berildi — talaba oynasida «Oʻyinlar» sahifani yangilamasdan paydo boʻldi');
      await student.goto(`${BASE}/?app#/games`);
      await student.waitForSelector('.game-card.oct');
      await row.locator('button[title="Oʻqituvchi huquqini olish"]').click();
      await owner.click('.modal-foot .btn.primary');
      await student.waitForFunction(() => location.hash === '#/duel', null, { timeout: 5000 });
      ok(!(await student.$('a[data-nav="games"]')), 'rol olindi — «Oʻyinlar» yashirindi va talaba #/duel ga qaytarildi');
      await student.context().close();
      await owner.context().close();

      console.log('1) rollar va «Oʻyinlar» paneli');
      const user = await loginPage(browser, 'talaba');
      await user.goto(`${BASE}/?app#/duel`);
      await user.waitForSelector('.app-header');
      ok(!(await user.$('a[data-nav="games"]')), 'oddiy foydalanuvchi menyusida «Oʻyinlar» yoʻq');
      ok(!!(await user.$('a[data-nav="duel"]')) && !!(await user.$('a[data-nav="practice"]')), 'Duel va Oʻrganish joyida');
      for (const route of ['/games', '/games/octagon', '/games/octagon/123456', '/games/balloon', '/balloon']) {
        await user.goto(`${BASE}/?app#${route}`);
        await user.waitForFunction(() => location.hash === '#/duel', null, { timeout: 5000 });
      }
      ok(true, 'toʻgʻridan-toʻgʻri havolalar (#/games…, #/balloon) — #/duel ga qaytariladi');
      const denied = await user.evaluate(async () => Promise.all(['/api/octagon/games', '/api/octagon/topics', '/api/balloon/games'].map(async (u) => (await fetch(u)).status)));
      ok(denied.every((s) => s === 403), `API — 403 (${denied.join(', ')})`);
      // qurilmadagi «rol» ma'lumoti hech narsa bermaydi: server faqat sessiyaga qaraydi
      await user.evaluate(() => {
        localStorage.setItem('role', 'teacher');
        localStorage.setItem('td-user', JSON.stringify({ isTeacher: true, isAdmin: true }));
      });
      await user.reload();
      await user.waitForSelector('.app-header');
      ok(!(await user.$('a[data-nav="games"]')) && (await user.evaluate(async () => (await fetch('/api/octagon/games')).status)) === 403,
        'localStorage dagi soxta rol eʼtiborsiz: menyu va API oʻzgarmadi');
      for (const login of ['zam_admin', 'oqituvchi']) {
        const p = await loginPage(browser, login);
        await p.goto(`${BASE}/?app#/duel`);
        await p.waitForSelector('a[data-nav="games"]');
        ok(true, `${login} menyusida «Oʻyinlar» bor`);
        await p.context().close();
      }

      const teacher = await loginPage(browser, 'oqituvchi');
      for (const w of WIDTHS) {
        await teacher.setViewportSize({ width: w, height: 800 });
        await teacher.goto(`${BASE}/?app#/games`);
        await teacher.waitForSelector('.game-card.oct');
        await sleep(150);
        await noOverflow(teacher, `Oʻyinlar paneli ${w}px`);
        if (w === 360) await tapTargets(teacher, '.games', 'Oʻyinlar paneli 360px');
        await shot(teacher, `games-${w}`);
      }
      await teacher.waitForFunction(() => [...document.querySelectorAll('link[rel=modulepreload]')].some((l) => /views\/octagon\.js$/.test(l.href)), null, { timeout: 5000 });
      ok(true, '«Oʻyinlar» panelida Octagon ekrani moduli boʻsh vaqtda oldindan yuklandi (modulepreload)');
      await teacher.setViewportSize({ width: 1280, height: 800 });

      console.log('2) Balloon Pop yangi joyida');
      await teacher.goto(`${BASE}/?app#/balloon`);
      await teacher.waitForFunction(() => location.hash === '#/games/balloon');
      await teacher.waitForSelector('#bp-topic option[value]:not([value=""])', { state: 'attached' });
      await teacher.click('button:has-text("Oʻyinni boshlash")');
      await teacher.waitForSelector('.bp-game');
      ok(/#\/games\/balloon\/\d+$/.test(teacher.url()), 'eski #/balloon havolasi yoʻnaltirildi, Balloon Pop oʻyini ochildi');
      await sleep(600);
      await shot(teacher, 'balloon-game-1280');

      console.log('3) Octagon sozlamalari va lobbi');
      for (const w of WIDTHS) {
        await teacher.setViewportSize({ width: w, height: 800 });
        await teacher.goto(`${BASE}/?app#/games/octagon`);
        await teacher.waitForSelector('.oct-setup select:not([disabled])');
        await sleep(150);
        await noOverflow(teacher, `sozlash ${w}px`);
        if (w === 360) await tapTargets(teacher, '.oct-lobby-page', 'sozlash 360px');
        await shot(teacher, `setup-${w}`);
      }
      await teacher.setViewportSize({ width: 1280, height: 800 });
      await teacher.selectOption('.oct-setup select', { label: `${TOPIC} (6)` });
      await teacher.click('.oct-chip:has-text("Hammasi")');
      await teacher.fill('.oct-custom-time', '200');
      await teacher.click('button:has-text("Lobbini ochish")');
      ok(/5–120/.test(await teacher.textContent('.oct-setup .field-error')), 'notoʻgʻri vaqt (200 s) rad etildi');
      await teacher.fill('.oct-custom-time', String(TIME));
      await teacher.click('button:has-text("Lobbini ochish")');
      await teacher.waitForSelector('.oct-lobby .oct-qr svg path');
      const pin = await hostPin(teacher);
      ok(/^\d{6}$/.test(pin), `lobbida PIN: ${pin}`);
      const joinBase = await teacher.textContent('.oct-url b');
      ok(joinBase.endsWith('/play'), `qoʻshilish manzili koʻrsatildi: ${joinBase}`);
      const hostState = await apiGame(teacher, pin);
      ok(hostState.timeLimit === TIME && hostState.joinUrl.endsWith(`/play/${pin}`), `sozlangan vaqt ${TIME} s, QR havola: ${hostState.joinUrl}`);
      await shot(teacher, 'lobby-1280-empty');

      console.log('4) oʻquvchilar qoʻshiladi: QR havola va PIN orqali, ism + avatar');
      const ali = await studentPage(browser, 360, 'Ali');
      await ali.goto(`${BASE}/play/${pin}`); // QR kod shu manzilga olib boradi: ism maydoni darhol, PIN fonda tekshiriladi
      await ali.waitForSelector('input[autocomplete=nickname]');
      ok(await studentPin(ali) === pin, 'QR havola: PIN oldindan toʻldirilgan va koʻrinadi');
      ok((await ali.$$('.pl-avatars .pl-av')).length === AVATARS.length && (await ali.$$('.pl-avatars .pl-av[aria-checked=true]')).length === 1,
        `avatarlar: ${AVATARS.length} ta, biri oldindan (tasodifiy) tanlangan`);
      await noOverflow(ali, 'ism va avatar 360px');
      await tapTargets(ali, '#play', 'ism va avatar 360px');
      await shot(ali, 'student-nick-360');
      await joinAs(ali, 'Ali', 4);
      await studentPhase(ali, 'lobby');
      ok(await ali.textContent('.pl-me-big .pl-avatar') === AVATARS[4] && await myAvatar(ali) === AVATARS[4], `lobbida oʻz avatari ${AVATARS[4]} (katta va tepada)`);

      const vali = await studentPage(browser, 375, 'Vali');
      await vali.goto(`${BASE}/play`);
      await vali.waitForSelector('.pl-pin-input');
      await noOverflow(vali, 'PIN kiritish 375px');
      await tapTargets(vali, '#play', 'PIN kiritish 375px');
      await shot(vali, 'student-pin-375');
      await vali.fill('.pl-pin-input', '012345');
      await vali.click('button[type=submit]');
      await vali.waitForSelector('.pl-error:not([hidden])');
      ok(/6 xonali/.test(await vali.textContent('.pl-error')), 'notoʻgʻri formatdagi PIN serverga yuborilmaydi');
      await vali.fill('.pl-pin-input', pin === '999999' ? '999998' : '999999');
      await vali.click('button[type=submit]');
      await vali.waitForFunction(() => /topilmadi/.test(document.querySelector('.pl-error')?.textContent || ''));
      ok(true, 'mavjud boʻlmagan PIN — tushunarli xato');
      await vali.fill('.pl-pin-input', pin);
      await vali.click('button[type=submit]');
      await joinAs(vali, '  Vali  ', 17);
      await studentPhase(vali, 'lobby');
      ok((await vali.textContent('.pl-nick')) === 'Vali', 'ism tozalandi (boʻshliqlar olib tashlandi)');

      const olim = await studentPage(browser, 768, 'Olim');
      await olim.goto(`${BASE}/play/${pin}`);
      await joinAs(olim, 'Olim', 26);
      await studentPhase(olim, 'lobby');

      const dup = await studentPage(browser, 375, 'dup');
      await dup.goto(`${BASE}/play/${pin}`);
      await joinAs(dup, 'ali', 9);
      await dup.waitForSelector('.pl-error:not([hidden])');
      ok(/band/.test(await dup.textContent('.pl-error')), 'band ism (ali ~ Ali) rad etildi');
      await sleep(300);
      const kept = await dup.evaluate(() => ({
        value: document.querySelector('input[autocomplete=nickname]').value,
        focused: !!document.activeElement && document.activeElement.matches('input[autocomplete=nickname]'),
        av: [...document.querySelectorAll('.pl-av')].findIndex((b) => b.getAttribute('aria-checked') === 'true'),
      }));
      ok(kept.value === 'ali' && kept.focused && kept.av === 9, 'rad etilgandan keyin yozilgan ism va tanlangan avatar saqlandi, maydon fokusda (V2-F8)');
      await dup.context().close();

      await teacher.waitForFunction(() => document.querySelectorAll('.oct-player').length === 3);
      const lobbyAvatars = async () => teacher.$$eval('.oct-player', (els) => els.map((e) => `${e.querySelector('.oct-player-nick').textContent}:${e.querySelector('.oct-avatar').textContent}`).sort());
      ok(JSON.stringify(await lobbyAvatars()) === JSON.stringify([`Ali:${AVATARS[4]}`, `Olim:${AVATARS[26]}`, `Vali:${AVATARS[17]}`]),
        `oʻqituvchi lobbisida 3 oʻquvchi avatarlari bilan: ${(await lobbyAvatars()).join(', ')}`);
      await olim.click('.pl-wait .pl-btn.ghost'); // «Avatarni almashtirish»
      await olim.click('.pl-avatars .pl-av >> nth=29');
      await olim.waitForFunction((e) => document.querySelector('.pl-me-big .pl-avatar')?.textContent === e, AVATARS[29]);
      await teacher.waitForFunction((e) => [...document.querySelectorAll('.oct-player')].some((p) => p.querySelector('.oct-player-nick').textContent === 'Olim'
        && p.querySelector('.oct-avatar').textContent === e), AVATARS[29], { timeout: 5000 });
      ok(true, `lobbida avatar almashtirildi (${AVATARS[26]} → ${AVATARS[29]}) — oʻqituvchi ekranida ham`);
      for (const w of WIDTHS) {
        await teacher.setViewportSize({ width: w, height: w < 700 ? 760 : 800 });
        await sleep(200);
        await noOverflow(teacher, `lobbi ${w}px`);
        if (w === 360) await tapTargets(teacher, '.oct-host', 'lobbi 360px');
        await shot(teacher, `lobby-${w}`);
      }
      await teacher.setViewportSize({ width: 1280, height: 800 });
      for (const [p, w] of [[ali, 360], [vali, 375], [olim, 768]]) {
        await noOverflow(p, `oʻquvchi lobbi ${w}px`);
        await shot(p, `student-lobby-${w}`);
      }

      console.log('5) «Boshlash» bosilmaguncha oʻyin boshlanmaydi');
      await sleep(3000);
      ok(await ali.$('#play.pl-phase-lobby') && await teacher.$('.oct-host.phase-lobby'), '3 soniyadan keyin ham lobbi');
      // mavzu va o'qish paytida qo'shiladiganlar sahifani oldindan ochib qo'yadi (ism maydoni darhol chiqadi)
      const lateIntro = await studentPage(browser, 375, 'Kirish');
      await lateIntro.goto(`${BASE}/play/${pin}`);
      await lateIntro.waitForSelector('input[autocomplete=nickname]');
      const lateRead = await studentPage(browser, 360, 'Oqish');
      const injected = [];
      let lateReadServer = null;
      await lateRead.routeWebSocket(/\/ws\/octagon$/, (ws) => {
        const srv = ws.connectToServer();
        lateReadServer = srv;
        srv.onMessage((m) => {
          injected.push(String(m));
          ws.send(m);
        });
      });
      await lateRead.goto(`${BASE}/play/${pin}`);
      await lateRead.waitForSelector('input[autocomplete=nickname]');

      console.log(`6) «Boshlash»: mavzu nomi hamma ekranda ${INTRO} s`);
      const startedAt = Date.now();
      await teacher.click('.oct-start');
      await Promise.all([hostPhase(teacher, 'topic_intro'), ...[ali, vali, olim].map((p) => studentPhase(p, 'topic_intro'))]);
      ok((await teacher.textContent('.oct-intro-topic')) === TOPIC, `oʻqituvchi: mavzu nomi «${TOPIC}» toʻliq ekranda`);
      for (const [p, nick] of [[ali, 'Ali'], [vali, 'Vali'], [olim, 'Olim']]) {
        ok((await p.textContent('.pl-intro-topic')) === TOPIC && (await p.$$('.pl-answer')).length === 0, `${nick}: mavzu nomi, bosiladigan javob tugmasi yoʻq`);
      }
      const introState = await apiGame(teacher, pin);
      ok(introState.phase === 'topic_intro' && introState.phaseEnd - introState.phaseStart === INTRO * 1000, `server: mavzu bosqichi ${INTRO} s (mutlaq vaqtlar)`);
      const counts0 = await Promise.all([teacher.textContent('.oct-intro [data-countdown]'), ...[ali, vali, olim].map((p) => p.textContent('.pl-intro [data-countdown]'))]);
      ok(counts0.every((c) => Number(c) >= 1 && Number(c) <= INTRO), `sanoq hamma ekranda: ${counts0.join(', ')}`);
      await shot(teacher, 'intro-1280');
      await shot(ali, 'student-intro-360');
      await joinAs(lateIntro, 'Kirish', 11);
      await studentPhase(lateIntro, 'topic_intro');
      ok((await lateIntro.textContent('.pl-intro-topic')) === TOPIC && await myAvatar(lateIntro) === AVATARS[11], 'mavzu paytida qoʻshilgan oʻquvchi mavzu ekraniga tushdi (avatari bilan)');
      await vali.reload();
      await studentPhase(vali, 'topic_intro');
      ok((await vali.textContent('.pl-nick')) === 'Vali' && await myAvatar(vali) === AVATARS[17], 'mavzu paytida sahifani yangilagan Vali: oʻsha ism va avatar');

      console.log(`7) 1-savolni oʻqish: ${READ} s, matn faqat oʻqituvchida, tugmalar yopiq`);
      await Promise.all([hostPhase(teacher, 'question_read', 9000), ...[ali, vali, olim, lateIntro].map((p) => studentPhase(p, 'question_read', 9000))]);
      const readAt = Date.now();
      const introMs = readAt - startedAt;
      ok(introMs >= (INTRO - 0.6) * 1000 && introMs <= (INTRO + 1.5) * 1000, `mavzu ${(introMs / 1000).toFixed(1)} s koʻrsatildi (≈ ${INTRO} s)`);
      const q1 = (await teacher.textContent('.oct-ready .oct-qtext')).trim();
      ok(QUESTIONS.some(([q]) => q === q1), `oʻqituvchi ekranida savol matni: «${q1}»`);
      for (const [p, nick] of [[ali, 'Ali'], [vali, 'Vali'], [olim, 'Olim'], [lateIntro, 'Kirish']]) {
        const st = await p.evaluate(() => ({ reading: !!document.querySelector('.pl-reading'), all: document.querySelectorAll('.pl-answer').length,
          enabled: document.querySelectorAll('.pl-answer:not([disabled])').length, text: document.body.textContent }));
        ok(st.reading && st.all >= 2 && st.enabled === 0 && !ALL_TEXTS.some((t) => st.text.includes(t)), `${nick}: shakllar koʻrinadi, bosilmaydi, savol matni yoʻq`);
      }
      await ali.click('.pl-answer >> nth=0', { force: true, timeout: 1000 }).catch(() => {});
      await joinAs(lateRead, 'Oqish', 20);
      await studentPhase(lateRead, 'question_read');
      ok(true, 'oʻqish paytida qoʻshilgan oʻquvchi oʻqish ekraniga tushdi');
      lateReadServer.send(JSON.stringify({ t: 'a', d: { q: 0, o: 0 } })); // o'zgartirilgan mijoz: javob muddatidan oldin
      await lateRead.waitForFunction(() => true);
      for (let i = 0; i < 30 && !injected.some((m) => /"c":"early"/.test(m)); i++) await sleep(50);
      ok(injected.some((m) => /"c":"early"/.test(m)), 'oʻqish paytida yuborilgan javob serverda rad etildi («early»)');
      await shot(teacher, 'read-1280');
      await shot(ali, 'student-read-360');
      await Promise.all([hostPhase(teacher, 'question_active', 9000), ...[ali, vali, olim, lateIntro, lateRead].map((p) => studentPhase(p, 'question_active', 9000))]);
      const q1start = Date.now();
      const readMs = q1start - readAt;
      ok(readMs >= (READ - 0.8) * 1000 && readMs <= (READ + 1.5) * 1000, `oʻqish ${(readMs / 1000).toFixed(1)} s (≈ ${READ} s), soʻng javob taymeri`);
      ok(!(await ali.$('.pl-locked')), 'oʻqish paytidagi bosish javob boʻlib qolmadi');

      console.log('8) 1-savolga javoblar: toʻgʻri va notoʻgʻri; javob paytida qayta ulanish');
      const tiles1 = await tileTexts(teacher);
      const c1 = tiles1.indexOf(CORRECT[q1]);
      ok(c1 >= 0 && tiles1.length >= 2 && tiles1.length <= 4, `oʻqituvchi ekranida savol va ${tiles1.length} ta variant`);
      await checkTwoOptions(tiles1, teacher, [[ali, 360], [vali, 375], [olim, 768]]);
      for (const [p, w] of [[ali, 360], [vali, 375], [olim, 768]]) {
        ok((await p.$$('.pl-answer:not([disabled])')).length === tiles1.length, `${w}px: ${tiles1.length} ta shakl tugmasi ochiq`);
        const text = await p.textContent('body');
        ok(!ALL_TEXTS.some((t) => text.includes(t)), `${w}px: oʻquvchi ekranida savol/javob matni yoʻq`);
        const small = await p.$$eval('.pl-answer', (els) => els.filter((e) => e.getBoundingClientRect().height < 48 || e.getBoundingClientRect().width < 48).length);
        ok(small === 0, `${w}px: javob tugmalari ≥ 48px`);
        await noOverflow(p, `savol ${w}px`);
        await shot(p, `student-question-${w}`);
      }
      ok(await studentPin(ali) === pin && await hostPin(teacher) === pin, 'savol paytida PIN ikkala ekranda');
      await shot(teacher, 'question-1280');
      await lateIntro.reload();
      await studentPhase(lateIntro, 'question_active');
      ok((await lateIntro.textContent('.pl-nick')) === 'Kirish' && await myAvatar(lateIntro) === AVATARS[11], 'javob paytida sahifani yangilagan oʻquvchi: oʻsha savol, ism va avatar');
      await answer(ali, c1);                                   // to'g'ri, tez
      await answer(vali, (c1 + 1) % tiles1.length);            // noto'g'ri
      await answer(lateIntro, c1);
      await answer(lateRead, c1);
      await sleep(1500);
      await answer(olim, c1);                                  // to'g'ri, sekinroq
      await hostPhase(teacher, 'question_result');
      ok(Date.now() - q1start < TIME * 1000, 'hamma javob berdi — savol vaqt tugashini kutmasdan yopildi');
      await studentPhase(ali, 'question_result');
      ok(await ali.$('#play.pl-res-good') && await vali.$('#play.pl-res-bad') && await olim.$('#play.pl-res-good'), 'natijalar: Ali ✓, Vali ✗, Olim ✓');
      const s1 = { ali: await score(ali), vali: await score(vali), olim: await score(olim) };
      ok(s1.ali > s1.olim && s1.olim >= 500 && s1.ali <= 1000 && s1.vali === 0, `ballar: Ali ${s1.ali} > Olim ${s1.olim} ≥ 500, Vali 0`);
      ok(await myAvatar(ali) === AVATARS[4] && await myAvatar(olim) === AVATARS[29], 'natija ekranida oʻz avatari');
      const counts = await teacher.$$eval('.oct-tile-count b', (els) => els.map((e) => Number(e.textContent)));
      ok(counts[c1] === 4 && counts.reduce((a, b) => a + b, 0) === 5, `javoblar taqsimoti: ${counts.join('/')}`);
      for (const w of WIDTHS) {
        await teacher.setViewportSize({ width: w, height: w < 700 ? 760 : 800 });
        await sleep(150);
        await noOverflow(teacher, `natija ${w}px`);
        if (w === 360) await tapTargets(teacher, '.oct-host', 'natija 360px');
        await shot(teacher, `reveal-${w}`);
      }
      await teacher.setViewportSize({ width: 1280, height: 800 });
      for (const [p, w] of [[ali, 360], [vali, 375]]) {
        await noOverflow(p, `oʻquvchi natijasi ${w}px`);
        await shot(p, `student-reveal-${w}`);
      }

      console.log('9) reyting (avatarlar bilan)');
      await teacher.click('.oct-actions .btn.primary');
      await hostPhase(teacher, 'leaderboard');
      const apiBoard = (await apiGame(teacher, pin)).leaderboard.map((r) => `${r.nick} ${r.score} ${AVATARS[r.av]}`);
      const shown = await teacher.$$eval('.oct-rank li', (els) => els.map((li) => `${li.querySelector('.oct-rank-nick').textContent} ${Number(li.querySelector('.oct-rank-score').textContent.replace(/\D/g, ''))} ${li.querySelector('.oct-rank-av').textContent}`));
      ok(JSON.stringify(shown) === JSON.stringify(apiBoard) && shown[0].startsWith('Ali ') && shown.at(-1).startsWith('Vali '), `reyting: ${shown.join(', ')}`);
      for (const w of WIDTHS) {
        await teacher.setViewportSize({ width: w, height: w < 700 ? 760 : 800 });
        await sleep(450);
        await noOverflow(teacher, `reyting ${w}px`);
        if (w === 360) await tapTargets(teacher, '.oct-host', 'reyting 360px');
        await shot(teacher, `leaderboard-${w}`);
      }
      await teacher.setViewportSize({ width: 1280, height: 800 });

      console.log('10) 2-savol: oʻqish paytida qayta ulanish, javob paytida kech qoʻshilish, sozlangan vaqt');
      await teacher.click('.oct-actions .btn.primary');
      await hostPhase(teacher, 'question_read');
      await olim.reload();
      await studentPhase(olim, 'question_read');
      ok((await olim.textContent('.pl-nick')) === 'Olim' && await myAvatar(olim) === AVATARS[29] && (await score(olim)) === s1.olim,
        'oʻqish paytida sahifani yangilagan Olim: oʻsha ism, avatar va ball');
      await hostPhase(teacher, 'question_active', 9000);
      const q2start = Date.now();
      ok(Number((await teacher.textContent('.oct-question [data-countdown]')).trim()) >= TIME - 1, 'taymer sozlangan vaqtdan boshlandi');
      const late = await studentPage(browser, 375, 'Kechikkan');
      await late.goto(`${BASE}/play/${pin}`);
      await joinAs(late, 'Kechikkan', 0);
      await studentPhase(late, 'question_active');
      ok((await score(late)) === 0 && /Savol 2/.test(await late.textContent('.pl-qlabel')), 'javob paytida kech qoʻshilgan oʻquvchi joriy savolga tushdi, 0 ball');
      const q2 = (await teacher.textContent('.oct-qtext')).trim();
      const tiles2 = await tileTexts(teacher);
      const c2 = tiles2.indexOf(CORRECT[q2]);
      await checkTwoOptions(tiles2, teacher, [[ali, 360], [vali, 375], [olim, 768]]);
      await answer(ali, c2);
      await answer(vali, c2);
      await answer(late, c2);
      // Olim, Kirish va Oqish javob bermaydi -> savol vaqt tugaganda yopiladi
      await hostPhase(teacher, 'question_result', (TIME + 4) * 1000);
      const q2ms = Date.now() - q2start;
      ok(q2ms > (TIME - 1) * 1000 && q2ms < (TIME + 2) * 1000, `savol sozlangan vaqtda yopildi (${(q2ms / 1000).toFixed(1)} s ≈ ${TIME} s)`);
      await studentPhase(olim, 'question_result');
      ok(await olim.$('#play.pl-res-none'), 'javob bermagan — «Javob berilmadi»');

      console.log('11) oʻquvchi sahifani yangiladi — oʻsha oʻyinchi, dublikatsiz');
      const valiScore = await score(vali);
      await vali.reload();
      await studentPhase(vali, 'question_result');
      ok((await vali.textContent('.pl-nick')) === 'Vali' && (await score(vali)) === valiScore, `Vali qaytdi: oʻsha ism va ball (${valiScore})`);
      ok(await studentPin(vali) === pin, 'yangilangandan keyin ham PIN koʻrinadi');
      let st = await apiGame(teacher, pin);
      ok(st.playerCount === 6 && st.connectedCount === 6, `oʻyinchilar soni oʻzgarmadi: ${st.playerCount} (onlayn ${st.connectedCount})`);

      console.log('12) oʻqituvchi sahifani yangiladi — oʻyin yoʻqolmadi');
      await teacher.reload();
      await hostPhase(teacher, 'question_result');
      ok(await hostPin(teacher) === pin && /Savol 2/.test(await teacher.textContent('.oct-qnum')), 'oʻqituvchi oʻsha oʻyinga, oʻsha bosqichga qaytdi');
      await teacher.click('.oct-actions .btn.primary');
      await hostPhase(teacher, 'leaderboard');
      ok((await teacher.$$('.oct-rank li')).length === 5, 'reytingda eng yaxshi 5 talik');

      console.log('13) oʻsha token ikkinchi oynada — yangi oyna egallaydi');
      const ali2 = await ali.context().newPage();
      watch(ali2, 'Ali-2');
      await ali2.goto(`${BASE}/play/${pin}`);
      await ali2.waitForSelector('.pl-nick');
      ok((await ali2.textContent('.pl-nick')) === 'Ali' && await myAvatar(ali2) === AVATARS[4], 'ikkinchi oynada oʻsha oʻyinchi (Ali, oʻsha avatar)');
      await ali.waitForSelector('text=Oʻyin boshqa oynada ochildi');
      ok(true, 'eski oyna: «Oʻyin boshqa oynada ochildi»');
      st = await apiGame(teacher, pin);
      ok(st.playerCount === 6, 'ikkinchi oyna yangi oʻyinchi yaratmadi');
      await shot(ali, 'student-replaced-360');
      await ali.close();

      console.log('14) qolgan savollar, gʻoliblar va yakuniy natijalar');
      const players = [ali2, vali, olim, late, lateIntro, lateRead];
      for (let q = 3; q <= 6; q++) {
        await teacher.click('.oct-actions .btn.primary');
        await hostPhase(teacher, 'question_read');
        await hostPhase(teacher, 'question_active', 9000);
        ok(await hostPin(teacher) === pin && await studentPin(olim) === pin, `${q}-savol: PIN ikkala ekranda`);
        const text = (await teacher.textContent('.oct-qtext')).trim();
        const tiles = await tileTexts(teacher);
        const c = tiles.indexOf(CORRECT[text]);
        ok(c >= 0, `${q}-savol: ${tiles.length} ta variant, toʻgʻri javob ekranda`);
        for (const p of players) await studentPhase(p, 'question_active');
        await checkTwoOptions(tiles, teacher, [[ali2, 360], [vali, 375], [olim, 768]]);
        for (const [i, p] of players.entries()) await answer(p, i === 1 ? (c + 1) % tiles.length : c);
        await hostPhase(teacher, 'question_result');
        if (q < 6) {
          await teacher.click('.oct-actions .btn.primary');
          await hostPhase(teacher, 'leaderboard');
        }
      }
      ok(/Gʻoliblar/.test(await teacher.textContent('.oct-actions .btn.primary')), 'oxirgi savol natijasidan keyin — «Gʻoliblar» (reyting koʻrsatilmaydi)');
      await teacher.click('.oct-actions .btn.primary');
      await hostPhase(teacher, 'podium_intro');
      for (const p of players) await studentPhase(p, 'podium_intro');
      await teacher.click('[data-skip]');                     // «Natijalarga oʻtish»
      await hostPhase(teacher, 'final_results');
      for (const p of players) await studentPhase(p, 'final_results');
      await sleep(1200);
      const ranking = (await apiGame(teacher, pin)).ranking;
      ok(ranking.length === 6 && ranking.every((r, i) => i === 0 || ranking[i - 1].score >= r.score), `yakuniy reyting: ${ranking.map((r) => `${r.nick} ${r.score}`).join(', ')}`);
      const podium = await teacher.evaluate(() => {
        const nicks = [...document.querySelectorAll('.oct-step-nick')].map((e) => e.textContent);
        const avs = [...document.querySelectorAll('.oct-step-av')].map((e) => e.textContent);
        return nicks.map((n, i) => `${n}:${avs[i]}`).sort();
      });
      ok(JSON.stringify(podium) === JSON.stringify(ranking.slice(0, 3).map((r) => `${r.nick}:${AVATARS[r.av]}`).sort()), `podium (avatarlar bilan): ${podium.join(', ')}`);
      const top3 = await vali.$$eval('.pl-top3 li', (els) => els.map((li) => `${li.querySelector('.pl-top3-nick').textContent}:${li.querySelector('.pl-avatar').textContent}`));
      ok(JSON.stringify(top3) === JSON.stringify(ranking.slice(0, 3).map((r) => `${r.nick}:${AVATARS[r.av]}`)), `oʻquvchi natijalarida eng yaxshi 3 talik avatarlari bilan: ${top3.join(', ')}`);
      for (const [p, nick] of [[ali2, 'Ali'], [vali, 'Vali'], [olim, 'Olim'], [late, 'Kechikkan'], [lateIntro, 'Kirish'], [lateRead, 'Oqish']]) {
        const r = ranking.find((x) => x.nick === nick);
        const place = await p.textContent('.pl-place');
        ok((await score(p)) === r.score && place === `${AVATARS[r.av]}${r.rank}-oʻrin`, `${nick}: telefonda ${place} (avatar bilan), ${r.score} ball`);
      }
      for (const w of WIDTHS) {
        await teacher.setViewportSize({ width: w, height: w < 700 ? 760 : 800 });
        await sleep(200);
        await noOverflow(teacher, `yakuniy natijalar ${w}px`);
        if (w === 360) await tapTargets(teacher, '.oct-host', 'yakuniy natijalar 360px');
        await shot(teacher, `final-${w}`);
      }
      await tapTargets(ali2, '#play', 'oʻquvchi yakuniy natijalari 360px');
      for (const [p, w] of [[ali2, 360], [vali, 375], [olim, 768]]) {
        await noOverflow(p, `oʻquvchi yakuniy natijalari ${w}px`);
        await shot(p, `student-final-${w}`);
      }

      console.log('15) oʻquvchilarga kelgan haqiqiy xabarlar: savol/javob matni, emoji va javob oldindan yoʻq');
      for (const [p, nick] of [[vali, 'Vali'], [olim, 'Olim'], [late, 'Kechikkan'], [lateIntro, 'Kirish'], [lateRead, 'Oqish']]) {
        const blob = p.frames.join('\n');
        ok(p.frames.length > 10 && !ALL_TEXTS.some((t) => blob.includes(t)), `${nick}: ${p.frames.length} ta xabar — savol/javob matni yoʻq`);
        ok(!AVATARS.some((a) => blob.includes(a)), `${nick}: avatarlar faqat raqam (indeks) bilan keladi`);
        const early = p.frames.map((f) => JSON.parse(f)).filter((m) => m.t === 's' && m.d.p <= 3 && m.d.res);
        ok(early.length === 0, `${nick}: toʻgʻri javob savol yopilguncha yuborilmagan`);
        const maxLen = Math.max(...p.frames.map((f) => f.length));
        ok(maxLen < 300, `${nick}: eng katta xabar ${maxLen} bayt`);
      }

      console.log('16) oʻquvchi sahifasi yengil va keshlanadi (haqiqiy trafik)');
      const files = [...new Set(vali.loaded.map((f) => f.url))];
      ok(!files.some((u) => /\/js\/(app|lib|api|live)\.js$|\/js\/views\/|\/css\/app\.css$/.test(u)), `faqat oʻquvchi fayllari: ${files.join(', ')}`);
      const once = new Map(vali.loaded.filter((f) => f.status === 200 && !/^\/play\/\d/.test(f.url)).map((f) => [f.url, f.bytes]));
      const total = [...once.values()].reduce((a, b) => a + b, 0);
      ok(total < 100 * 1024, `oʻquvchi sahifasi: ${once.size} ta fayl, jami ${(total / 1024).toFixed(1)} KB (siqilmagan; tarmoqda gzip)`);
      const assets = vali.loaded.filter((f) => /^\/assets\/[0-9a-f]{12}\/(js|css)\//.test(f.url) && f.status === 200);
      ok(assets.length >= 3 && assets.every((f) => /immutable/.test(f.cache) && f.enc === 'gzip'), `JS/CSS: mazmun xeshli manzil, «immutable» kesh, gzip (${assets.length} ta fayl)`);
      const page = vali.loaded.find((f) => f.url === `/play/${pin}`);
      ok(page && page.cache === 'no-cache', 'HTML qobiq: no-cache (yangi versiya darhol)');

      console.log('17) yopilgan oʻyin');
      await teacher.evaluate(async (p) => fetch(`/api/octagon/games/${p}`, { method: 'DELETE' }), pin);
      await vali.waitForSelector('text=Oʻyin yopildi');
      ok(true, 'oʻyin yopilganda oʻquvchi xabar oldi');

      console.log('18) tarmoq uzilishi: qayta ulanish (oraligʻi oshib boradi) va navbatdagi javob');
      const t2 = await loginPage(browser, 'oqituvchi');
      const g2 = await createGame(t2, { topic: TOPIC, settings: { timeLimit: 30, questionCount: 2 } });
      await t2.goto(`${BASE}/?app#/games/octagon/${g2.pin}`);
      await t2.waitForSelector('.oct-lobby');
      const netCtx = await browser.newContext({ viewport: { width: 375, height: 760 }, isMobile: true, hasTouch: true });
      let online = true;
      const routes = new Set();
      const tries = [];
      await netCtx.routeWebSocket(/\/ws\/octagon$/, (ws) => {
        tries.push(Date.now());
        if (!online) {
          ws.close({ code: 4500, reason: 'offline' });
          return;
        }
        routes.add({ ws, server: ws.connectToServer() });
      });
      const drop = () => {
        online = false;
        for (const r of routes) {
          r.ws.close({ code: 4500, reason: 'net' });
          r.server.close();
        }
        routes.clear();
      };
      const net = await netCtx.newPage();
      watch(net, 'Uzilgan');
      await net.goto(`${BASE}/play/${g2.pin}`);
      await joinAs(net, 'Uzilgan', 7);
      await studentPhase(net, 'lobby');
      const other2 = await studentPage(browser, 375, 'Boshqa');
      await other2.goto(`${BASE}/play/${g2.pin}`);
      await joinAs(other2, 'Boshqa', 8);
      await studentPhase(other2, 'lobby');
      drop();
      const dropAt = Date.now();
      await net.waitForSelector('.pl-conn:not([hidden])', { timeout: 10000 });
      ok(true, 'aloqa uzildi — «qayta ulanmoqda» banneri');
      await t2.click('.oct-start');
      await sleep(6000);
      const offTries = tries.filter((x) => x >= dropAt);
      const gaps = offTries.slice(1).map((x, i) => x - offTries[i]);
      ok(offTries.length >= 3 && gaps.every((g, i) => i === 0 || g >= gaps[i - 1] * 0.8 || g >= 4500) && Math.max(...gaps) <= 5600,
        `qayta ulanish urinishlari oraligʻi oshib boradi: ${gaps.map((g) => (g / 1000).toFixed(1)).join(', ')} s`);
      online = true;
      await studentPhase(net, 'question_active', 20000);
      await net.waitForSelector('.pl-conn[hidden]', { state: 'attached', timeout: 15000 });
      ok((await net.textContent('.pl-nick')) === 'Uzilgan' && await studentPin(net) === g2.pin && await myAvatar(net) === AVATARS[7],
        'aloqa tiklandi: oʻsha oʻyinchi va avatar, joriy savol, PIN koʻrinadi');
      drop();
      await net.waitForSelector('.pl-conn:not([hidden])', { timeout: 10000 });
      await net.click('.pl-answer >> nth=0');
      await net.waitForSelector('text=javob ulanish tiklanishi bilan yuboriladi');
      ok(true, 'aloqasiz bosilgan javob navbatga qoʻyildi');
      await sleep(1000);
      online = true;
      await net.waitForSelector('.pl-conn[hidden]', { state: 'attached', timeout: 15000 });
      await other2.click('.pl-answer >> nth=1');
      await hostPhase(t2, 'question_result', 35000);
      const st2 = await apiGame(t2, g2.pin);
      ok(st2.answered === 2 && st2.playerCount === 2, `navbatdagi javob yetib bordi: ${st2.answered}/2 javob, ${st2.playerCount} oʻyinchi`);

      console.log('19) XSS: mavzu nomi, savol, variantlar va ismlardagi HTML faqat matn sifatida; «Oʻtkazib yuborish» tugmalari');
      const XSS = '<img src=x onerror="window.__xss=1">';
      const xssContent = [`Savol ${XSS} <script>window.__xss=2</script>?`, `#Javob ${XSS}`,
        '<b onmouseover="window.__xss=3">Qalin</b>', '"><svg onload=window.__xss=4>', 'Oddiy javob'].join('\n====\n');
      const ownerCookie = (await apiAs('', 'POST', '/api/auth/login', { login: 'admin', password: 'owner123' })).cookie;
      const xssTopic = `XSS ${XSS} sinov`;
      const xt = await apiAs(ownerCookie, 'POST', '/api/admin/topics', { name: xssTopic, content: xssContent, shuffle: false });
      ok(xt.status === 201, 'HTML li mavzu yaratildi');
      const xg = await createGame(t2, { topic: xssTopic, settings: { timeLimit: 30, questionCount: 1, shuffleAnswers: false } });
      await t2.goto(`${BASE}/?app#/games/octagon/${xg.pin}`);
      await t2.waitForSelector('.oct-lobby');
      const xs = await studentPage(browser, 375, 'xss');
      await xs.goto(`${BASE}/play/${xg.pin}`);
      await joinAs(xs, '<img src=x>');
      await xs.waitForSelector('.pl-error:not([hidden])');
      const nickErr = await xs.textContent('.pl-error');
      ok(/harf yoki raqam/.test(nickErr), `faqat HTML tegidan iborat ism rad etildi: «${nickErr}»`);
      await joinAs(xs, 'Ali"><svg onload=f>');
      await studentPhase(xs, 'lobby');
      ok((await xs.textContent('.pl-nick')) === 'Ali', 'ismdan HTML tozalandi: «Ali»');
      // brauzerdagi 20 belgilik cheklovni chetlab, uzun HTML ism va soxta avatar satri to'g'ridan-to'g'ri WebSocket orqali
      const raw = await xs.evaluate((p) => Promise.all([
        { nick: '<img src=x onerror="window.__xss=5">Bek', av: 1 },
        { nick: 'Emoji', av: '🐶' },
        { nick: 'Katta', av: 999 },
      ].map((d) => new Promise((resolve) => {
        const sock = new WebSocket(`ws://${location.host}/ws/octagon`);
        sock.onopen = () => sock.send(JSON.stringify({ t: 'join', d: { v: 3, pin: p, ...d } }));
        sock.onmessage = (ev) => {
          const m = JSON.parse(ev.data);
          if (m.t !== 'w' && m.t !== 'e') return;
          sock.close(); // Bek aloqasiz qoladi — savol Ali javob berishi bilan yopiladi
          resolve(m.t === 'w' ? m.d.nick : `xato:${m.d.c}`);
        };
      }))), xg.pin);
      ok(raw[0] === 'Bek', `WebSocket orqali yuborilgan HTML ism serverda tozalandi: «${raw[0]}»`);
      ok(raw[1] === 'xato:avatar' && raw[2] === 'xato:avatar', 'ruxsat etilmagan avatar (emoji satri, katta indeks) rad etildi');
      await t2.waitForFunction(() => document.querySelectorAll('.oct-player-nick').length === 2);
      const nicks = await t2.$$eval('.oct-player-nick', (els) => els.map((e) => e.textContent).sort());
      ok(JSON.stringify(nicks) === '["Ali","Bek"]', `oʻqituvchi lobbisida ismlar matn sifatida: ${nicks.join(', ')}`);
      await t2.goto(`${BASE}/?app#/games/octagon`);
      await t2.waitForSelector('.games-active .adm-row-title');
      const activeText = await t2.textContent('.games-active');
      ok(activeText.includes(xssTopic), 'mavzu nomidagi HTML matn sifatida koʻrsatildi (davom etayotgan oʻyinlar)');
      ok(!/topic_intro|question_|leaderboard/.test(activeText) && /lobbi|natija/.test(activeText), 'davom etayotgan oʻyinlarda bosqich nomi oʻzbekcha (V2-F11)');
      await t2.goto(`${BASE}/?app#/games/octagon/${xg.pin}`);
      await t2.waitForSelector('.oct-start:not([disabled])');
      await t2.click('.oct-start');
      await hostPhase(t2, 'topic_intro');
      await studentPhase(xs, 'topic_intro');
      ok((await t2.textContent('.oct-intro-topic')) === xssTopic && (await xs.textContent('.pl-intro-topic')) === xssTopic, 'mavzu ekranida HTML li nom matn sifatida (ikkala ekranda)');
      await t2.click('.oct-intro .btn.ghost');                 // «O'tkazib yuborish»
      await hostPhase(t2, 'question_read', 3000);
      ok(true, '«Oʻtkazib yuborish» — mavzu ekranidan darhol oʻqishga');
      await t2.click('.oct-ready .btn.ghost');                 // «Javoblarni hozir ochish»
      await hostPhase(t2, 'question_active', 3000);
      ok(true, '«Javoblarni hozir ochish» — oʻqishdan darhol javoblarga');
      const qText = await t2.textContent('.oct-qtext');
      const tiles = await tileTexts(t2);
      ok(qText.includes(XSS) && qText.includes('<script>'), `savol matni oʻzgarishsiz koʻrsatildi: ${qText.slice(0, 40)}…`);
      ok(tiles.includes('<b onmouseover="window.__xss=3">Qalin</b>') && tiles.includes('"><svg onload=window.__xss=4>'), 'variantlardagi HTML matn sifatida');
      await t2.hover('.oct-tile >> nth=1');
      const inj = await t2.evaluate(() => ({
        flag: window.__xss,
        nodes: document.querySelectorAll('.oct-stage img, .oct-stage script, .oct-stage svg[onload], .oct-stage b[onmouseover], .games-active img').length,
      }));
      ok(inj.flag === undefined && inj.nodes === 0, 'oʻqituvchi ekranida hech qanday skript ishlamadi, HTML element yaratilmadi');
      await xs.click('.pl-answer >> nth=0');
      await hostPhase(t2, 'question_result');
      await t2.click('.oct-actions .btn.primary');             // yagona (oxirgi) savol -> g'oliblar
      await hostPhase(t2, 'podium_intro');
      await t2.click('[data-next]');                           // «Keyingi oʻrin»
      await hostPhase(t2, 'reveal_2nd');                      // 2 o'yinchi: 3-o'rin yo'q
      await studentPhase(xs, 'reveal_2nd');
      ok(await t2.evaluate(() => window.__xss === undefined && !document.querySelector('.oct-stage img, .oct-stage script')), 'gʻoliblar ekranida HTML li ism matn sifatida');
      await t2.click('[data-skip]');
      await hostPhase(t2, 'final_results');
      await studentPhase(xs, 'final_results');
      ok(await xs.evaluate(() => window.__xss === undefined && !document.querySelector('#play img, #play script')), 'oʻquvchi sahifasida ham skript ishlamadi');
      ok(await t2.evaluate(() => window.__xss === undefined), 'yakuniy natijalarda ham skript ishlamadi');

      console.log('20) eskirgan (12 soatdan eski) saqlangan oʻyinchi maʼlumoti ishlatilmaydi va oʻchiriladi');
      const stale = await studentPage(browser, 375, 'stale');
      await stale.goto(`${BASE}/play`);
      await stale.evaluate(([p, me]) => localStorage.setItem(`oct:${p}`, JSON.stringify(me)),
        [g2.pin, { v: 2, id: 'eski', tok: 'y'.repeat(32), nick: 'Eski', av: 1, at: Date.now() - 13 * 3600 * 1000 }]);
      await stale.goto(`${BASE}/play/${g2.pin}`);
      await stale.waitForSelector('input[autocomplete=nickname]');
      ok(await stale.evaluate((p) => localStorage.getItem(`oct:${p}`) === null, g2.pin), 'eskirgan ID/token eʼtiborsiz qoldirildi va oʻchirildi (ism soʻraladi)');

      console.log('21) oʻqituvchi yangi qoʻshilishlarni yopadi va qayta ochadi');
      await t2.goto(`${BASE}/?app#/games/octagon/${g2.pin}`);
      await t2.waitForSelector('.oct-lock:not([hidden])');
      await t2.click('.oct-lock');
      await t2.waitForSelector('.oct-lock.on[aria-pressed=true]');
      await joinAs(stale, 'Kechikkan');
      await stale.waitForFunction(() => /toʻxtatgan/.test(document.querySelector('.pl-error')?.textContent || ''));
      ok(true, 'qoʻshilish yopiq: yangi oʻquvchiga tushunarli xabar');
      await t2.click('.oct-lock');
      await t2.waitForSelector('.oct-lock:not(.on)');
      await stale.click('.pl-join button[type=submit]');
      await studentPhase(stale, 'question_result');
      ok((await stale.textContent('.pl-nick')) === 'Kechikkan', 'qoʻshilish qayta ochildi — oʻquvchi kirdi (yozilgan ism saqlangan edi)');

      console.log('22) qurilmadagi maʼlumotni oʻzgartirish natijani oʻzgartirmaydi (tamper)');
      const tg = await createGame(t2, { topic: TOPIC, settings: { timeLimit: 30, questionCount: 1, shuffleQuestions: false, shuffleAnswers: false } });
      await t2.goto(`${BASE}/?app#/games/octagon/${tg.pin}`);
      await t2.waitForSelector('.oct-lobby');
      const tA = await studentPage(browser, 375, 'TamperA');
      await tA.goto(`${BASE}/play/${tg.pin}`);
      await joinAs(tA, 'Anvar', 2);
      await studentPhase(tA, 'lobby');
      const tB = await studentPage(browser, 375, 'TamperB');
      await tB.goto(`${BASE}/play/${tg.pin}`);
      await joinAs(tB, 'Botir', 3);
      await studentPhase(tB, 'lobby');
      const recA = await tA.evaluate((p) => JSON.parse(localStorage.getItem(`oct:${p}`)), tg.pin);
      const recB = await tB.evaluate((p) => JSON.parse(localStorage.getItem(`oct:${p}`)), tg.pin);
      ok(recA && recA.v === 2 && recA.tok && recA.id && !('sc' in recA), 'saqlangan yozuv: versiya, ID, token, ism, avatar (ball yoʻq)');
      await tA.evaluate(([p, r]) => localStorage.setItem(`oct:${p}`, JSON.stringify({ ...r, nick: 'Admin', av: 29, sc: 99999, role: 'teacher', isTeacher: true })), [tg.pin, recA]);
      await tA.reload();
      await studentPhase(tA, 'lobby');
      ok((await tA.textContent('.pl-nick')) === 'Anvar' && await myAvatar(tA) === AVATARS[2], 'oʻzgartirilgan ism/avatar/ball/rol eʼtiborsiz: server qiymatlari (Anvar, avatar, 0 ball)');
      await tA.evaluate(([p, r, b]) => localStorage.setItem(`oct:${p}`, JSON.stringify({ ...r, id: b.id })), [tg.pin, recA, recB]);
      await tA.reload();
      await tA.waitForSelector('input[autocomplete=nickname]', { timeout: 10000 });
      ok(!(await tB.$('#play.pl-view-closed')) && (await tB.textContent('.pl-nick')) === 'Botir', 'boshqa oʻyinchining ID si oʻz tokeni bilan — rad etildi, Botir joyida qoldi');
      await joinAs(tA, 'Anvar2', 2);
      await studentPhase(tA, 'lobby');
      const tC = await studentPage(browser, 375, 'Soat', { timezoneId: 'Pacific/Kiritimati' });
      await tC.addInitScript(() => {                           // telefon soati bir soat oldinda
        const real = Date.now.bind(Date);
        Date.now = () => real() + 3600 * 1000;
      });
      await tC.goto(`${BASE}/play/${tg.pin}`);
      await joinAs(tC, 'Soat', 5);
      await studentPhase(tC, 'lobby');
      await t2.waitForFunction(() => document.querySelectorAll('.oct-player').length === 3);
      await t2.click('.oct-start');
      await studentPhase(tC, 'topic_intro');
      await sleep(600);
      const cd = Number(await tC.textContent('.pl-intro [data-countdown]'));
      ok(cd >= 1 && cd <= INTRO, `soati 1 soat oldinda boʻlgan telefonda ham sanoq toʻgʻri: ${cd} (server vaqti boʻyicha)`);
      await t2.click('.oct-intro .btn.ghost');
      await hostPhase(t2, 'question_read');
      await t2.click('.oct-ready .btn.ghost');
      await hostPhase(t2, 'question_active');
      const tq = (await t2.textContent('.oct-qtext')).trim();
      const tc = (await tileTexts(t2)).indexOf(CORRECT[tq]);
      for (const p of [tA, tB, tC]) await studentPhase(p, 'question_active');
      await answer(tC, tc);
      await answer(tA, tc);
      await answer(tB, (tc + 1) % 4);
      await studentPhase(tC, 'question_result');
      ok(await tC.$('#play.pl-res-good') && (await score(tC)) >= 500, `soxta soatli telefon javobi qabul qilindi va server vaqti boʻyicha baholandi (${await score(tC)} ball)`);

      console.log('23) bosib turilgan Probel kirish va oʻqish vaqtini oʻtkazib yubormaydi (V2-F9)');
      const kg = await createGame(t2, { topic: TOPIC, settings: { timeLimit: 30, questionCount: 1 } });
      await t2.goto(`${BASE}/?app#/games/octagon/${kg.pin}`);
      await t2.waitForSelector('.oct-lobby');
      const ks = await studentPage(browser, 375, 'Probel');
      await ks.goto(`${BASE}/play/${kg.pin}`);
      await joinAs(ks, 'Probel', 6);
      await studentPhase(ks, 'lobby');
      await t2.waitForFunction(() => document.querySelectorAll('.oct-player').length === 1);
      await t2.locator('body').click({ position: { x: 5, y: 400 } });
      await t2.keyboard.down(' ');
      await hostPhase(t2, 'topic_intro');
      for (let i = 0; i < 15; i++) {                          // tugma qo'yib yuborilmadi — OS avtomatik takrorlashi
        await t2.keyboard.down(' ');
        await sleep(40);
      }
      await t2.keyboard.up(' ');
      await sleep(300);
      ok(await t2.$('.oct-host.phase-topic_intro') && await ks.$('#play.pl-phase-topic_intro'), 'bitta bosish — bitta amal: oʻyin boshlandi, mavzu ekrani oʻtkazib yuborilmadi');

    }
    console.log('24) dizayn: barcha bosqichlar 360 / 375 / 768 / 1280 px, oʻqituvchi va oʻquvchi (alohida server, uzun bosqichlar)');
    await startServer(DESIGN_PORT, { // eng ko'pi (sozlamalar tekshiruvi): ochilish qadamlari ham «Keyingi» bilan o'tkaziladi
      TD_OCTAGON_INTRO: '60', TD_OCTAGON_READ: '60', TD_OCTAGON_PODIUM_INTRO: '60', TD_OCTAGON_REVEAL_STEP: '60', TD_OCTAGON_REVEAL_WINNER: '60',
    });
    const designOwner = await seed(DESIGN);
    const lt = await apiAs(designOwner, 'POST', '/api/admin/topics', { name: LONG_TOPIC, content: TOPIC_FILE, shuffle: false }, DESIGN);
    ok(lt.status === 201, `uzun nomli mavzu (${LONG_TOPIC.length} belgi)`);
    const dt = await loginPage(browser, 'oqituvchi', { width: 1280, height: 800 }, DESIGN);
    const dg = await createGame(dt, { topic: TOPIC, settings: { timeLimit: 120, questionCount: 3, shuffleQuestions: false, shuffleAnswers: false } });
    const tPages = [];
    const sPages = [];
    const studentNames = ['Madinabonu Rahimova', 'Abdulaziz', 'Gulnora', 'Shohjahon Karimov'];
    for (const [i, w] of WIDTHS.entries()) {
      const tp = i === 3 ? dt : await loginPage(browser, 'oqituvchi', { width: w, height: w < 700 ? 760 : 800 }, DESIGN);
      await tp.goto(`${DESIGN}/?app#/games/octagon/${dg.pin}`);
      await tp.waitForSelector('.oct-lobby');
      tPages.push([tp, w]);
      const sp = await studentPage(browser, w, `Dizayn-${w}`);
      await sp.goto(`${DESIGN}/play/${dg.pin}`);
      await joinAs(sp, studentNames[i], [4, 12, 22, 27][i]);
      await studentPhase(sp, 'lobby');
      sPages.push([sp, w]);
    }
    ok(await dt.getAttribute('.oct-sound', 'aria-pressed') === 'false', 'ovoz standart holatda oʻchiq (tugma bilan yoqiladi)');
    const allWidths = async (label, hostSel, studentSel) => {
      await sleep(400);
      for (const [p, w] of tPages) {
        await noOverflow(p, `${label} oʻqituvchi ${w}px`);
        await notClipped(p, hostSel, `${label} oʻqituvchi ${w}px`);
        await readableText(p, '.oct-host', `${label} oʻqituvchi ${w}px`);
        if (w <= 375) await tapTargets(p, '.oct-host', `${label} oʻqituvchi ${w}px`);
        ok(await hostPin(p) === dg.pin, `${label} oʻqituvchi ${w}px: PIN koʻrinadi`);
        await shot(p, `v2-teacher-${label}-${w}`);
      }
      for (const [p, w] of sPages) {
        await noOverflow(p, `${label} oʻquvchi ${w}px`);
        await notClipped(p, studentSel, `${label} oʻquvchi ${w}px`);
        await readableText(p, '#play', `${label} oʻquvchi ${w}px`);
        if (w <= 375) await tapTargets(p, '#play', `${label} oʻquvchi ${w}px`);
        ok(await studentPin(p) === dg.pin, `${label} oʻquvchi ${w}px: PIN koʻrinadi`);
        await shot(p, `v2-student-${label}-${w}`);
      }
    };
    const [dt4] = tPages[3];
    const phaseAll = async (phase) => {
      await Promise.all([...tPages.map(([p]) => hostPhase(p, phase)), ...sPages.map(([p]) => studentPhase(p, phase))]);
    };
    await allWidths('lobby', '.oct-hero-pin, .oct-url b, .oct-pin b, .oct-start', '.pl-pin b, .pl-big-nick');
    await dt4.click('.oct-start');
    await phaseAll('topic_intro');
    await allWidths('intro', '.oct-intro-topic, .oct-pin b', '.pl-intro-topic, .pl-pin b');
    for (const [p, w] of tPages) await visibleControl(p, '.oct-intro .btn.ghost', `mavzu oʻqituvchi ${w}px`);
    await dt4.click('.oct-intro .btn.ghost');
    await phaseAll('question_read');
    await allWidths('read', '.oct-ready .oct-qtext, .oct-pin b', '.pl-read-note h1, .pl-qlabel, .pl-pin b');
    for (const [p, w] of tPages) await visibleControl(p, '.oct-ready .btn.ghost', `oʻqish oʻqituvchi ${w}px`);
    await dt4.click('.oct-ready .btn.ghost');
    await phaseAll('question_active');
    const labels = await sPages[0][0].$$eval('.pl-answer', (els) => els.map((e) => [e.getAttribute('aria-label'), e.className, !!e.querySelector('svg path')]));
    ok(JSON.stringify(labels.map((l) => l[0])) === JSON.stringify(['Javob: Qizil sakkizburchak', 'Javob: Koʻk tomchi', 'Javob: Sariq yulduz', 'Javob: Yashil plyus']),
      `shakllar: ${labels.map((l) => l[0].replace('Javob: ', '')).join(', ')}`);
    ok(labels.every(([, cls, svg], i) => cls.includes(`oc-c${i}`) && svg), 'har bir tugmada rang va shakl (inline SVG) bor');
    const tileLabels = await dt4.$$eval('.oct-tile-shape', (els) => els.map((e) => e.getAttribute('aria-label')));
    ok(tileLabels.join() === 'Qizil sakkizburchak,Koʻk tomchi,Sariq yulduz,Yashil plyus', 'proyektordagi variantlarda ham oʻsha rang va shakl');
    await allWidths('active', '.oct-qtext, .oct-tile-text, .oct-pin b', '.pl-pin b, .pl-qlabel');
    // 1-savol: hamma xato, qat'iy navbat bilan (o'rinlar vaqt bo'yicha aniq: Madinabonu, Abdulaziz, Gulnora, Shohjahon)
    for (const [p] of sPages.slice(0, 3)) {
      await p.click('.pl-answer >> nth=2');
      await p.waitForSelector('.pl-lock-tag.on');
    }
    ok(/qabul qilindi/.test(await sPages[0][0].textContent('.pl-locked h1')), 'javob qulflandi — aniq tasdiq koʻrsatildi');
    await allWidths('locked', '.oct-qtext, .oct-pin b', '.pl-pin b');
    await sPages[3][0].click('.pl-answer >> nth=2');
    await phaseAll('question_result');
    await allWidths('result', '.oct-tile-text, .oct-tile-count, .oct-pin b', '.pl-result h1, .pl-rank, .pl-pin b');
    await dt4.click('.oct-actions .btn.primary');
    await phaseAll('leaderboard');
    await allWidths('leaderboard', '.oct-rank-score, .oct-rank-nick, .oct-board-title', '.pl-result h1, .pl-rank, .pl-pin b');
    ok(await dt4.$$eval('.oct-board-list .oct-move', (els) => els.every((e) => e.classList.contains('none') && !e.textContent)), '1-savol reytingida strelkalar yoʻq');
    // 2-savol: faqat Shohjahon (oxirgi o'rinda edi) to'g'ri javob beradi — 4 -> 1 (▲ 3), qolganlar bitta pastga (▼ 1)
    await dt4.click('.oct-actions .btn.primary');
    await phaseAll('question_read');
    await dt4.click('.oct-ready .btn.ghost');
    await phaseAll('question_active');
    await sPages[3][0].click('.pl-answer >> nth=1');
    await sPages[3][0].waitForSelector('.pl-lock-tag.on');
    await dt4.click('button:has-text("Savolni yakunlash")');
    await phaseAll('question_result');
    await allWidths('result-move', '.oct-tile-text, .oct-pin b', '.pl-result h1, .pl-rank, .pl-move, .pl-pin b');
    const up = await sPages[3][0].textContent('.pl-move');
    const down = await sPages[0][0].textContent('.pl-move');
    ok(/▲ 3/.test(up) && /1-oʻrin/.test(up) && /3 oʻringa koʻtarildingiz/.test(up), `oʻquvchi telefonida koʻtarilish: «${up}»`);
    ok(/▼ 1/.test(down) && /2-oʻrin/.test(down) && /1 oʻringa tushdingiz/.test(down), `oʻquvchi telefonida tushish: «${down}»`);
    ok(/Shohjahon Karimov sizdan [\d ]+ ball oldinda/.test(await sPages[0][0].textContent('.pl-behind')), 'yuqoridagi oʻquvchigacha farq koʻrsatildi');
    await dt4.click('.oct-actions .btn.primary');
    await phaseAll('leaderboard');
    for (const [p, w] of tPages) await wordsWhole(p, '.oct-board-list .oct-rank-nick', `reyting oʻqituvchi ${w}px`);
    await allWidths('leaderboard-arrows', '.oct-rank-score, .oct-rank-nick, .oct-board-title, .oct-move, .oct-jump-nick', '.pl-result h1, .pl-rank, .pl-move, .pl-pin b');
    const marks = await dt4.$$eval('.oct-board-list li', (els) => els.map((li) => `${li.querySelector('.oct-rank-nick').textContent}:${li.querySelector('.oct-move').textContent}`));
    ok(JSON.stringify(marks) === JSON.stringify(['Shohjahon Karimov:▲3', 'Madinabonu Rahimova:▼1', 'Abdulaziz:▼1', 'Gulnora:▼1']), `reytingda strelka va son: ${marks.join(', ')}`);
    const jump = await dt4.textContent('[data-jump]');
    ok(/Eng katta sakrash/.test(jump) && /Shohjahon Karimov/.test(jump) && /▲3/.test(jump), `«Eng katta sakrash» qatori: «${jump}»`);
    // 3-savol (oxirgi): reytingsiz — g'oliblar birma-bir
    await dt4.click('.oct-actions .btn.primary');
    await phaseAll('question_read');
    await dt4.click('.oct-ready .btn.ghost');
    await phaseAll('question_active');
    await dt4.click('button:has-text("Savolni yakunlash")');
    await phaseAll('question_result');
    ok(await sPages[0][0].$('.pl-move') === null, 'oxirgi savol natijasida oʻrin koʻrsatilmaydi (gʻoliblar hali sir)');
    await dt4.click('.oct-actions .btn.primary');
    await phaseAll('podium_intro');
    await allWidths('podium-intro', '.oct-finale-title, .oct-pin b, [data-next], [data-skip]', '.pl-suspense h1, .pl-pin b');
    for (const [p, w] of tPages) await medalsInside(p, `podium-intro oʻqituvchi ${w}px`);
    for (const [step, place] of [['reveal_3rd', 3], ['reveal_2nd', 2], ['reveal_1st', 1]]) {
      await dt4.click('[data-next]');
      await phaseAll(step);
      await sleep(1900);   // ustun ko'tarilishi va ism chiqishi tugasin
      for (const [p, w] of tPages) await wordsWhole(p, '.oct-col.shown .oct-step-nick', `${step} oʻqituvchi ${w}px`);
      await allWidths(step, '.oct-finale-title, .oct-col.shown .oct-step-score, .oct-col.shown .oct-step-nick, .oct-pin b, [data-next], [data-skip]', '.pl-pin b, .pl-final h1, .pl-wait h1');
      for (const [p, w] of tPages) await medalsInside(p, `${step} oʻqituvchi ${w}px`);
      ok(await dt4.$$eval('.oct-col.shown', (els) => els.length) === 4 - place, `${step}: oʻqituvchi ekranida ${4 - place} ta oʻrin ochiq`);
    }
    await dt4.click('[data-next]');
    await phaseAll('final_results');
    await sleep(600);
    for (const [p, w] of tPages) await wordsWhole(p, '.oct-step-nick, .oct-final-list .oct-rank-nick', `final oʻqituvchi ${w}px`);
    await allWidths('final', '.oct-board-title, .oct-step-score, .oct-step-nick, .oct-final-list .oct-rank-nick, .oct-final-actions .btn', '.pl-place, .pl-points, .pl-top3-nick, .pl-final .pl-btn');
    for (const [p, w] of tPages) await medalsInside(p, `final oʻqituvchi ${w}px`);

    console.log(`25) uzun mavzu nomi (${LONG_TOPIC.length} belgi): sanoq va «Oʻtkazib yuborish» hamma kenglikda koʻrinadi (V2-F10)`);
    const lg = await createGame(dt4, { topic: LONG_TOPIC, settings: { timeLimit: 30, questionCount: 1 } });
    const longPages = [];
    for (const [p, w] of tPages) {
      await p.goto(`${DESIGN}/?app#/games/octagon/${lg.pin}`);
      await p.waitForSelector('.oct-lobby');
      longPages.push([p, w]);
    }
    const lStudents = [];
    for (const w of WIDTHS) {
      const sp = await studentPage(browser, w, `Uzun-${w}`);
      await sp.goto(`${DESIGN}/play/${lg.pin}`);
      await joinAs(sp, `Oquvchi ${w}`, 1);
      await studentPhase(sp, 'lobby');
      lStudents.push([sp, w]);
    }
    await dt4.click('.oct-start');
    for (const [p, w] of longPages) {
      await hostPhase(p, 'topic_intro');
      await sleep(300);
      await noOverflow(p, `uzun mavzu oʻqituvchi ${w}px`);
      await notClipped(p, '.oct-intro-topic', `uzun mavzu oʻqituvchi ${w}px`);
      await visibleControl(p, '.oct-intro [data-countdown]', `uzun mavzu oʻqituvchi ${w}px`);
      await visibleControl(p, '.oct-intro .btn.ghost', `uzun mavzu oʻqituvchi ${w}px`);
      await shot(p, `v2-teacher-long-topic-${w}`);
    }
    for (const [p, w] of lStudents) {
      await studentPhase(p, 'topic_intro');
      await noOverflow(p, `uzun mavzu oʻquvchi ${w}px`);
      await notClipped(p, '.pl-intro-topic', `uzun mavzu oʻquvchi ${w}px`);
      await visibleControl(p, '.pl-intro .pl-count', `uzun mavzu oʻquvchi ${w}px`);
      await shot(p, `v2-student-long-topic-${w}`);
    }

    const rmCtx = await browser.newContext({ viewport: { width: 375, height: 760 }, reducedMotion: 'reduce' });
    const rm = await rmCtx.newPage();
    await rm.goto(`${BASE}/play`);
    await rm.waitForSelector('.pl-card');
    ok(await rm.$eval('.pl-card', (e) => getComputedStyle(e).animationName === 'none'), '«kamroq harakat» sozlamasida animatsiyalar oʻchadi');
    await rmCtx.close();

    if (!DESIGN_ONLY) ok(twoChecked, 'ha/yoʻq (2 variantli) savol maketi tekshirildi');
    for (const s of servers) {
      const tracebacks = (s.log().match(/Traceback/g) || []).length;
      ok(tracebacks === 0, `${s.base}: server jurnalida xato yoʻq`);
    }
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
