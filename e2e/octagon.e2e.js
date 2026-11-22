// Octagon va «O'yinlar» paneli — brauzerda to'liq tekshiruv (Playwright).
//
// Ishga tushirish (loyiha ildizidan):  node e2e/octagon.e2e.js
// Talab: Node.js va Playwright (npm i -D playwright && npx playwright install chromium). Ilovaning o'ziga kerak emas.
// Skript o'zi vaqtinchalik baza bilan server ishga tushiradi, akkauntlar va mavzu yaratadi, so'ng:
//   * rollar: o'qituvchi/admin «O'yinlar»ni ko'radi, oddiy foydalanuvchi ko'rmaydi va to'g'ridan-to'g'ri havoladan qaytariladi;
//   * o'qituvchi mavzu va savol vaqtini tanlaydi -> lobbida PIN va QR -> 3 o'quvchi turli ismlar bilan qo'shiladi;
//   * «Boshlash» bosilmaguncha o'yin boshlanmaydi; to'g'ri/noto'g'ri javoblar bilan to'liq o'yin; sozlangan vaqt ishlatiladi;
//   * reyting to'g'ri; kech qo'shilgan o'quvchi; sahifa yangilanganda o'sha o'yinchi (dublikatsiz); ikkinchi oyna egallaydi;
//   * band ism rad etiladi; PIN hamma ekranda doim ko'rinadi; o'qituvchi sahifani yangilasa o'yin yo'qolmaydi;
//   * o'quvchiga kelgan WebSocket xabarlarida savol/javob matni yo'q;
//   * 360, 375, 768 va 1280 px kengliklarda gorizontal siljish yo'q, tugmalar bosish uchun yetarli kattalikda;
//   * Balloon Pop yangi joyida ishlaydi (eski havola yo'naltiriladi).
// Skrinshotlar: e2e/screenshots/ (yoki OUT muhit o'zgaruvchisi).
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.OUT || path.join(__dirname, 'screenshots');
const PORT = Number(process.env.PORT || 8765);
const BASE = `http://127.0.0.1:${PORT}`;
const TIME = 7; // savol vaqti (soniya) — maxsus qiymat sifatida kiritiladi
const WIDTHS = [360, 375, 768, 1280];
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

// ------------------------------------------------------------------ server
async function startServer() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'octagon-e2e-'));
  const proc = spawn('python3', ['run.py', '--port', String(PORT), '--host', '127.0.0.1', '--db', path.join(dir, 'e2e.db')], {
    cwd: ROOT,
    env: { ...process.env, TD_SUPERADMIN_PASSWORD: 'owner123', TD_OCTAGON_READY: '1.5' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  proc.stdout.on('data', (d) => { log += d; });
  proc.stderr.on('data', (d) => { log += d; });
  for (let i = 0; i < 100; i++) {
    try {
      const r = await fetch(`${BASE}/api/auth/me`);
      if (r.ok) return { proc, log: () => log };
    } catch {
      /* hali ishga tushmagan */
    }
    await sleep(100);
  }
  proc.kill();
  throw new Error(`server ishga tushmadi:\n${log}`);
}

async function apiAs(cookie, method, url, body) {
  const r = await fetch(BASE + url, {
    method,
    headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: r.status, data: await r.json().catch(() => null), cookie: (r.headers.get('set-cookie') || '').split(';')[0] };
}

async function seed() {
  const owner = (await apiAs('', 'POST', '/api/auth/login', { login: 'admin', password: 'owner123' })).cookie;
  for (const u of [{ login: 'oqituvchi', isTeacher: true }, { login: 'zam_admin', isAdmin: true }, { login: 'talaba' }]) {
    const r = await apiAs(owner, 'POST', '/api/admin/users', { password: '1234', ...u });
    if (r.status !== 201) throw new Error(`user ${u.login}: ${r.status}`);
  }
  const t = await apiAs(owner, 'POST', '/api/admin/topics', { name: 'Octagon E2E', content: TOPIC_FILE, shuffle: false });
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

async function loginPage(browser, login, viewport = { width: 1280, height: 800 }) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  watch(page, login);
  await page.goto(`${BASE}/#/login`);
  const st = await page.evaluate(async (l) => (await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login: l, password: l === 'admin' ? 'owner123' : '1234' }),
  })).status, login);
  if (st !== 200) throw new Error(`${login}: login ${st}`);
  return page;
}

async function studentPage(browser, width, tag) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 700 ? 760 : 1024 }, isMobile: width < 700, hasTouch: true });
  const page = await ctx.newPage();
  watch(page, tag);
  const frames = [];
  page.on('websocket', (ws) => ws.on('framereceived', (f) => frames.push(String(f.payload))));
  page.frames = frames;
  page.loaded = [];
  page.on('response', async (r) => {
    const body = await r.body().catch(() => Buffer.alloc(0));
    page.loaded.push({ url: new URL(r.url()).pathname, bytes: body.length });
  });
  return page;
}

async function noOverflow(page, label) {
  const extra = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ok(extra <= 0, `${label}: gorizontal siljish yoʻq (${extra}px)`);
}

/** Yangi ekranlardagi bosiladigan elementlar kamida 48×48 px (telefon uchun). */
async function tapTargets(page, scope, label) {
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

let twoChecked = false;
/** 2 variantli (ha/yo'q) savol qaysi raundga tushmasin — maketi tekshiriladi. */
async function checkTwoOptions(tiles, teacher, students) {
  if (tiles.length !== 2 || twoChecked) return;
  twoChecked = true;
  for (const [p, w] of students) {
    await studentPhase(p, 'question');
    ok((await p.$$('.pl-answer')).length === 2, `ha/yoʻq savol ${w}px: 2 ta katta tugma`);
    await noOverflow(p, `ha/yoʻq savol ${w}px`);
    await shot(p, `student-question-2opts-${w}`);
  }
  await shot(teacher, 'question-2opts-1280');
}

async function answer(student, index) {
  await student.click(`.pl-answer >> nth=${index}`);
  await student.waitForSelector('.pl-phase-question .pl-shape, .pl-phase-reveal', { timeout: 5000 });
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

// ------------------------------------------------------------------ test
(async () => {
  const server = await startServer();
  const browser = await chromium.launch();
  try {
    await seed();

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
    await teacher.selectOption('.oct-setup select', { label: 'Octagon E2E (6)' });
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
    let qrUrl = null;
    try {
      const jsQR = require('jsqr'); // ixtiyoriy: o'rnatilgan bo'lsa, QR kod o'qib ko'riladi
      const png = await teacher.locator('.oct-qr').screenshot();
      const { PNG } = require('pngjs');
      const img = PNG.sync.read(png);
      qrUrl = jsQR(new Uint8ClampedArray(img.data), img.width, img.height)?.data;
    } catch {
      qrUrl = null;
    }
    if (qrUrl) ok(qrUrl.endsWith(`/play/${pin}`), `QR kod oʻqildi: ${qrUrl}`);
    const hostState = await teacher.evaluate(async (p) => (await (await fetch(`/api/octagon/games/${p}`)).json()).game, pin);
    ok(hostState.timeLimit === TIME && hostState.joinUrl.endsWith(`/play/${pin}`), `sozlangan vaqt ${TIME} s, QR havola: ${hostState.joinUrl}`);
    await shot(teacher, 'lobby-1280-empty');

    console.log('4) oʻquvchilar qoʻshiladi (QR havola va PIN orqali)');
    const ali = await studentPage(browser, 360, 'Ali');
    await ali.goto(`${BASE}/play/${pin}`); // QR kod shu manzilga olib boradi
    await ali.waitForSelector('input[autocomplete=nickname]');
    ok(await studentPin(ali) === pin, 'QR havola: PIN oldindan toʻldirilgan va koʻrinadi');
    await noOverflow(ali, 'ism kiritish 360px');
    await tapTargets(ali, '#play', 'ism kiritish 360px');
    await shot(ali, 'student-nick-360');
    await ali.fill('input[autocomplete=nickname]', 'Ali');
    await ali.click('button[type=submit]');
    await studentPhase(ali, 'lobby');

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
    await vali.waitForSelector('input[autocomplete=nickname]');
    await vali.fill('input[autocomplete=nickname]', '  Vali  ');
    await vali.click('button[type=submit]');
    await studentPhase(vali, 'lobby');
    ok((await vali.textContent('.pl-nick')) === 'Vali', 'ism tozalandi (boʻshliqlar olib tashlandi)');

    const olim = await studentPage(browser, 768, 'Olim');
    await olim.goto(`${BASE}/play/${pin}`);
    await olim.fill('input[autocomplete=nickname]', 'Olim');
    await olim.click('button[type=submit]');
    await studentPhase(olim, 'lobby');

    const dup = await studentPage(browser, 375, 'dup');
    await dup.goto(`${BASE}/play/${pin}`);
    await dup.fill('input[autocomplete=nickname]', 'ali');
    await dup.click('button[type=submit]');
    await dup.waitForSelector('.pl-error:not([hidden])');
    ok(/band/.test(await dup.textContent('.pl-error')), 'band ism (ali ~ Ali) rad etildi');
    await dup.context().close();

    await teacher.waitForFunction(() => document.querySelectorAll('.oct-player').length === 3);
    ok(true, 'oʻqituvchi ekranida 3 oʻquvchi');
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

    console.log('6) 1-savol: toʻgʻri va notoʻgʻri javoblar');
    await teacher.click('.oct-start');
    await hostPhase(teacher, 'ready');
    await studentPhase(ali, 'ready');
    await hostPhase(teacher, 'question');
    const q1start = Date.now();
    await studentPhase(ali, 'question');
    const q1 = (await teacher.textContent('.oct-qtext')).trim();
    const tiles1 = await tileTexts(teacher);
    const c1 = tiles1.indexOf(CORRECT[q1]);
    ok(c1 >= 0 && tiles1.length >= 2 && tiles1.length <= 4, `oʻqituvchi ekranida savol va ${tiles1.length} ta variant`);
    await checkTwoOptions(tiles1, teacher, [[ali, 360], [vali, 375], [olim, 768]]);
    for (const [p, w] of [[ali, 360], [vali, 375], [olim, 768]]) {
      ok((await p.$$('.pl-answer')).length === tiles1.length, `${w}px: ${tiles1.length} ta shakl tugmasi`);
      const text = await p.textContent('body');
      ok(!ALL_TEXTS.some((t) => text.includes(t)), `${w}px: oʻquvchi ekranida savol/javob matni yoʻq`);
      const small = await p.$$eval('.pl-answer', (els) => els.filter((e) => e.getBoundingClientRect().height < 48 || e.getBoundingClientRect().width < 48).length);
      ok(small === 0, `${w}px: javob tugmalari ≥ 48px`);
      await noOverflow(p, `savol ${w}px`);
      await shot(p, `student-question-${w}`);
    }
    ok(await studentPin(ali) === pin && await hostPin(teacher) === pin, 'savol paytida PIN ikkala ekranda');
    await shot(teacher, 'question-1280');
    await answer(ali, c1);                                   // to'g'ri, tez
    await answer(vali, (c1 + 1) % tiles1.length);            // noto'g'ri
    await sleep(1500);
    await answer(olim, c1);                                  // to'g'ri, sekinroq
    await hostPhase(teacher, 'reveal');
    ok(Date.now() - q1start < TIME * 1000, 'hamma javob berdi — savol vaqt tugashini kutmasdan yopildi');
    await studentPhase(ali, 'reveal');
    ok(await ali.$('#play.pl-res-good') && await vali.$('#play.pl-res-bad') && await olim.$('#play.pl-res-good'), 'natijalar: Ali ✓, Vali ✗, Olim ✓');
    const s1 = { ali: await score(ali), vali: await score(vali), olim: await score(olim) };
    ok(s1.ali > s1.olim && s1.olim >= 500 && s1.ali <= 1000 && s1.vali === 0, `ballar: Ali ${s1.ali} > Olim ${s1.olim} ≥ 500, Vali 0`);
    const counts = await teacher.$$eval('.oct-tile-count b', (els) => els.map((e) => Number(e.textContent)));
    ok(counts[c1] === 2 && counts.reduce((a, b) => a + b, 0) === 3, `javoblar taqsimoti: ${counts.join('/')}`);
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

    console.log('7) reyting');
    await teacher.click('.oct-actions .btn.primary');
    await hostPhase(teacher, 'leaderboard');
    const board = await teacher.$$eval('.oct-rank li', (els) => els.map((li) => [li.querySelector('.oct-rank-nick').textContent, Number(li.querySelector('.oct-rank-score').textContent.replace(/\D/g, ''))]));
    ok(JSON.stringify(board) === JSON.stringify([['Ali', s1.ali], ['Olim', s1.olim], ['Vali', 0]]), `reyting toʻgʻri: ${board.map((r) => r.join(' ')).join(', ')}`);
    for (const w of WIDTHS) {
      await teacher.setViewportSize({ width: w, height: w < 700 ? 760 : 800 });
      await sleep(450);
      await noOverflow(teacher, `reyting ${w}px`);
      if (w === 360) await tapTargets(teacher, '.oct-host', 'reyting 360px');
      await shot(teacher, `leaderboard-${w}`);
    }
    await teacher.setViewportSize({ width: 1280, height: 800 });

    console.log('8) 2-savol: kech qoʻshilgan oʻquvchi, sozlangan vaqt');
    await teacher.click('.oct-actions .btn.primary');
    await hostPhase(teacher, 'question');
    const q2start = Date.now();
    ok((await teacher.textContent('[data-countdown]')).trim() >= String(TIME - 1), 'taymer sozlangan vaqtdan boshlandi');
    const late = await studentPage(browser, 375, 'Kechikkan');
    await late.goto(`${BASE}/play/${pin}`);
    await late.fill('input[autocomplete=nickname]', 'Kechikkan');
    await late.click('button[type=submit]');
    await studentPhase(late, 'question');
    ok((await score(late)) === 0 && /Savol 2/.test(await late.textContent('.pl-qlabel')), 'kech qoʻshilgan oʻquvchi joriy savolga tushdi, 0 ball');
    const q2 = (await teacher.textContent('.oct-qtext')).trim();
    const tiles2 = await tileTexts(teacher);
    const c2 = tiles2.indexOf(CORRECT[q2]);
    await checkTwoOptions(tiles2, teacher, [[ali, 360], [vali, 375], [olim, 768]]);
    await answer(ali, c2);
    await answer(vali, c2);
    await answer(late, c2);
    // Olim javob bermaydi -> savol vaqt tugaganda yopiladi
    await hostPhase(teacher, 'reveal', (TIME + 4) * 1000);
    const q2ms = Date.now() - q2start;
    ok(q2ms > (TIME - 1) * 1000 && q2ms < (TIME + 2) * 1000, `savol sozlangan vaqtda yopildi (${(q2ms / 1000).toFixed(1)} s ≈ ${TIME} s)`);
    await studentPhase(olim, 'reveal');
    ok(await olim.$('#play.pl-res-none'), 'javob bermagan — «Javob berilmadi»');

    console.log('9) oʻquvchi sahifani yangiladi — oʻsha oʻyinchi, dublikatsiz');
    const valiScore = await score(vali);
    await vali.reload();
    await studentPhase(vali, 'reveal');
    ok((await vali.textContent('.pl-nick')) === 'Vali' && (await score(vali)) === valiScore, `Vali qaytdi: oʻsha ism va ball (${valiScore})`);
    ok(await studentPin(vali) === pin, 'yangilangandan keyin ham PIN koʻrinadi');
    let st = await teacher.evaluate(async (p) => (await (await fetch(`/api/octagon/games/${p}`)).json()).game, pin);
    ok(st.playerCount === 4 && st.connectedCount === 4, `oʻyinchilar soni oʻzgarmadi: ${st.playerCount} (onlayn ${st.connectedCount})`);

    console.log('10) oʻqituvchi sahifani yangiladi — oʻyin yoʻqolmadi');
    await teacher.reload();
    await hostPhase(teacher, 'reveal');
    ok(await hostPin(teacher) === pin && /Savol 2/.test(await teacher.textContent('.oct-qnum')), 'oʻqituvchi oʻsha oʻyinga, oʻsha bosqichga qaytdi');
    await teacher.click('.oct-actions .btn.primary');
    await hostPhase(teacher, 'leaderboard');
    ok((await teacher.$$('.oct-rank li')).length === 4, 'reytingda kech qoʻshilgan oʻquvchi ham bor');

    console.log('11) oʻsha token ikkinchi oynada — yangi oyna egallaydi');
    const ali2 = await ali.context().newPage();
    watch(ali2, 'Ali-2');
    await ali2.goto(`${BASE}/play/${pin}`);
    await ali2.waitForSelector('.pl-nick');
    ok((await ali2.textContent('.pl-nick')) === 'Ali', 'ikkinchi oynada oʻsha oʻyinchi (Ali)');
    await ali.waitForSelector('text=Oʻyin boshqa oynada ochildi');
    ok(true, 'eski oyna: «Oʻyin boshqa oynada ochildi»');
    st = await teacher.evaluate(async (p) => (await (await fetch(`/api/octagon/games/${p}`)).json()).game, pin);
    ok(st.playerCount === 4, 'ikkinchi oyna yangi oʻyinchi yaratmadi');
    await shot(ali, 'student-replaced-360');
    await ali.close();

    console.log('12) qolgan savollar va podium');
    const players = [ali2, vali, olim, late];
    for (let q = 3; q <= 6; q++) {
      await teacher.click('.oct-actions .btn.primary');
      await hostPhase(teacher, 'question');
      ok(await hostPin(teacher) === pin && await studentPin(olim) === pin, `${q}-savol: PIN ikkala ekranda`);
      const text = (await teacher.textContent('.oct-qtext')).trim();
      const tiles = await tileTexts(teacher);
      const c = tiles.indexOf(CORRECT[text]);
      ok(c >= 0, `${q}-savol: ${tiles.length} ta variant, toʻgʻri javob ekranda`);
      for (const p of players) await studentPhase(p, 'question');
      await checkTwoOptions(tiles, teacher, [[ali2, 360], [vali, 375], [olim, 768]]);
      for (const [i, p] of players.entries()) await answer(p, i === 1 ? (c + 1) % tiles.length : c);
      await hostPhase(teacher, 'reveal');
      await teacher.click('.oct-actions .btn.primary');
      await hostPhase(teacher, 'leaderboard');
    }
    ok(/Yakuniy/.test(await teacher.textContent('.oct-actions .btn.primary')), 'oxirgi savoldan keyin — «Yakuniy natijalar»');
    await teacher.click('.oct-actions .btn.primary');
    await hostPhase(teacher, 'podium');
    for (const p of players) await studentPhase(p, 'podium');
    await sleep(1200);
    const ranking = await teacher.evaluate(async (p) => (await (await fetch(`/api/octagon/games/${p}`)).json()).game.ranking, pin);
    ok(ranking.length === 4 && ranking.every((r, i) => i === 0 || ranking[i - 1].score >= r.score), `yakuniy reyting: ${ranking.map((r) => `${r.nick} ${r.score}`).join(', ')}`);
    const podiumNames = await teacher.$$eval('.oct-step-nick', (els) => els.map((e) => e.textContent));
    ok(podiumNames.length === 3 && podiumNames.includes(ranking[0].nick), `podium: ${podiumNames.join(', ')}`);
    for (const [p, nick] of [[ali2, 'Ali'], [vali, 'Vali'], [olim, 'Olim'], [late, 'Kechikkan']]) {
      const r = ranking.find((x) => x.nick === nick);
      ok((await score(p)) === r.score && (await p.textContent('.pl-place')).startsWith(`${r.rank}-`), `${nick}: telefonda ${r.rank}-oʻrin, ${r.score} ball`);
    }
    for (const w of WIDTHS) {
      await teacher.setViewportSize({ width: w, height: w < 700 ? 760 : 800 });
      await sleep(200);
      await noOverflow(teacher, `podium ${w}px`);
      if (w === 360) await tapTargets(teacher, '.oct-host', 'podium 360px');
      await shot(teacher, `podium-${w}`);
    }
    await tapTargets(ali2, '#play', 'oʻquvchi podium 360px');
    for (const [p, w] of [[ali2, 360], [vali, 375], [olim, 768]]) {
      await noOverflow(p, `oʻquvchi podium ${w}px`);
      await shot(p, `student-podium-${w}`);
    }

    console.log('13) oʻquvchilarga kelgan xabarlarda savol/javob matni yoʻq');
    for (const [p, nick] of [[vali, 'Vali'], [olim, 'Olim'], [late, 'Kechikkan']]) {
      const blob = p.frames.join('\n');
      ok(p.frames.length > 10 && !ALL_TEXTS.some((t) => blob.includes(t)), `${nick}: ${p.frames.length} ta xabar — matn yoʻq`);
      const early = p.frames.map((f) => JSON.parse(f)).filter((m) => m.t === 's' && ['lobby', 'ready', 'question'].includes(m.d.p) && m.d.res);
      ok(early.length === 0, `${nick}: toʻgʻri javob savol tugaguncha yuborilmagan`);
      const maxLen = Math.max(...p.frames.map((f) => f.length));
      ok(maxLen < 300, `${nick}: eng katta xabar ${maxLen} bayt`);
    }

    console.log('14) oʻquvchi sahifasi yengil: asosiy ilova yuklanmaydi');
    const files = [...new Set(vali.loaded.map((f) => f.url))];
    ok(!files.some((u) => /\/js\/(app|lib|api|live)\.js$|\/js\/views\/|\/css\/app\.css$/.test(u)), `faqat oʻquvchi fayllari: ${files.join(', ')}`);
    const total = vali.loaded.reduce((a, f) => a + f.bytes, 0);
    ok(total < 80 * 1024, `oʻquvchi sahifasi jami ${(total / 1024).toFixed(1)} KB`);

    console.log('15) yopilgan oʻyin');
    await teacher.evaluate(async (p) => fetch(`/api/octagon/games/${p}`, { method: 'DELETE' }), pin);
    await vali.waitForSelector('text=Oʻyin yopildi');
    ok(true, 'oʻyin yopilganda oʻquvchi xabar oldi');

    console.log('16) tarmoq uzilishi: qayta ulanish (oraligʻi oshib boradi) va navbatdagi javob');
    const owner2 = await loginPage(browser, 'oqituvchi');
    const t2 = owner2;
    const g2 = await t2.evaluate(async () => {
      const { topics } = await (await fetch('/api/octagon/topics')).json();
      const id = topics.find((x) => x.name === 'Octagon E2E').id;
      return (await (await fetch('/api/octagon/games', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topicId: id, timeLimit: 30, questionCount: 2 }) })).json()).game;
    });
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
    await net.fill('input[autocomplete=nickname]', 'Uzilgan');
    await net.click('button[type=submit]');
    await studentPhase(net, 'lobby');
    const other2 = await studentPage(browser, 375, 'Boshqa');
    await other2.goto(`${BASE}/play/${g2.pin}`);
    await other2.fill('input[autocomplete=nickname]', 'Boshqa');
    await other2.click('button[type=submit]');
    await studentPhase(other2, 'lobby');
    drop();
    const dropAt = Date.now();
    await net.waitForSelector('.pl-conn:not([hidden])', { timeout: 10000 });
    ok(true, 'aloqa uzildi — «qayta ulanmoqda» banneri');
    await t2.click('.oct-start');
    await hostPhase(t2, 'question');
    await sleep(6000);
    const offTries = tries.filter((x) => x >= dropAt);
    const gaps = offTries.slice(1).map((x, i) => x - offTries[i]);
    ok(offTries.length >= 3 && gaps.every((g, i) => i === 0 || g >= gaps[i - 1] * 0.8 || g >= 4500) && Math.max(...gaps) <= 5600,
      `qayta ulanish urinishlari oraligʻi oshib boradi: ${gaps.map((g) => (g / 1000).toFixed(1)).join(', ')} s`);
    online = true;
    await studentPhase(net, 'question');
    await net.waitForSelector('.pl-conn[hidden]', { state: 'attached', timeout: 15000 });
    ok((await net.textContent('.pl-nick')) === 'Uzilgan' && await studentPin(net) === g2.pin, 'aloqa tiklandi: oʻsha oʻyinchi, joriy savol, PIN koʻrinadi');
    drop();
    await net.waitForSelector('.pl-conn:not([hidden])', { timeout: 10000 });
    await net.click('.pl-answer >> nth=0');
    await net.waitForSelector('text=javob ulanish tiklanishi bilan yuboriladi');
    ok(true, 'aloqasiz bosilgan javob navbatga qoʻyildi');
    await sleep(1000);
    online = true;
    await net.waitForSelector('.pl-conn[hidden]', { state: 'attached', timeout: 15000 });
    await other2.click('.pl-answer >> nth=1');
    await hostPhase(t2, 'reveal', 35000);
    const st2 = await t2.evaluate(async (p) => (await (await fetch(`/api/octagon/games/${p}`)).json()).game, g2.pin);
    ok(st2.answered === 2 && st2.playerCount === 2, `navbatdagi javob yetib bordi: ${st2.answered}/2 javob, ${st2.playerCount} oʻyinchi`);

    console.log('17) XSS: mavzu nomi, savol, variantlar va ismlardagi HTML faqat matn sifatida koʻrsatiladi');
    const XSS = '<img src=x onerror="window.__xss=1">';
    const xssContent = [`Savol ${XSS} <script>window.__xss=2</script>?`, `#Javob ${XSS}`,
      '<b onmouseover="window.__xss=3">Qalin</b>', '"><svg onload=window.__xss=4>', 'Oddiy javob'].join('\n====\n');
    const ownerCookie = (await apiAs('', 'POST', '/api/auth/login', { login: 'admin', password: 'owner123' })).cookie;
    const xt = await apiAs(ownerCookie, 'POST', '/api/admin/topics', { name: `XSS ${XSS} sinov`, content: xssContent, shuffle: false });
    ok(xt.status === 201, 'HTML li mavzu yaratildi');
    const xg = await t2.evaluate(async (id) => (await (await fetch('/api/octagon/games', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topicId: id, timeLimit: 30, questionCount: 1, shuffleAnswers: false }),
    })).json()).game, xt.data.topic.id);
    await t2.goto(`${BASE}/?app#/games/octagon/${xg.pin}`);
    await t2.waitForSelector('.oct-lobby');
    const xs = await studentPage(browser, 375, 'xss');
    await xs.goto(`${BASE}/play/${xg.pin}`);
    await xs.fill('input[autocomplete=nickname]', '<img src=x>'); // maydon 20 belgigacha
    await xs.click('button[type=submit]');
    await xs.waitForSelector('.pl-error:not([hidden])');
    const nickErr = await xs.textContent('.pl-error');
    ok(/harf yoki raqam/.test(nickErr), `faqat HTML tegidan iborat ism rad etildi: «${nickErr}»`);
    await xs.fill('input[autocomplete=nickname]', 'Ali"><svg onload=f>');
    await xs.click('button[type=submit]');
    await studentPhase(xs, 'lobby');
    ok((await xs.textContent('.pl-nick')) === 'Ali', 'ismdan HTML tozalandi: «Ali»');
    // brauzerdagi 20 belgilik cheklovni chetlab, uzun HTML ism to'g'ridan-to'g'ri WebSocket orqali
    const rawNick = await xs.evaluate((p) => new Promise((resolve) => {
      const sock = new WebSocket(`ws://${location.host}/ws/octagon`);
      sock.onopen = () => sock.send(JSON.stringify({ t: 'join', d: { pin: p, nick: '<img src=x onerror="window.__xss=5">Bek' } }));
      sock.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        if (m.t !== 'w' && m.t !== 'e') return;
        sock.close(); // Bek aloqasiz qoladi — savol Ali javob berishi bilan yopiladi
        resolve(m.t === 'w' ? m.d.nick : `xato: ${m.d.m}`);
      };
    }), xg.pin);
    ok(rawNick === 'Bek', `WebSocket orqali yuborilgan HTML ism serverda tozalandi: «${rawNick}»`);
    await t2.waitForFunction(() => document.querySelectorAll('.oct-player-nick').length === 2);
    const nicks = await t2.$$eval('.oct-player-nick', (els) => els.map((e) => e.textContent).sort());
    ok(JSON.stringify(nicks) === '["Ali","Bek"]', `oʻqituvchi lobbisida ismlar matn sifatida: ${nicks.join(', ')}`);
    await t2.goto(`${BASE}/?app#/games/octagon`);
    await t2.waitForSelector('.games-active .adm-row-title');
    ok((await t2.textContent('.games-active')).includes(`XSS ${XSS} sinov`), 'mavzu nomidagi HTML matn sifatida koʻrsatildi (davom etayotgan oʻyinlar)');
    await t2.goto(`${BASE}/?app#/games/octagon/${xg.pin}`);
    await t2.waitForSelector('.oct-start:not([disabled])');
    await t2.click('.oct-start');
    await hostPhase(t2, 'question');
    const qText = await t2.textContent('.oct-qtext');
    const tiles = await tileTexts(t2);
    ok(qText.includes(XSS) && qText.includes('<script>'), `savol matni oʻzgarishsiz koʻrsatildi: ${qText.slice(0, 40)}…`);
    ok(tiles.includes('<b onmouseover="window.__xss=3">Qalin</b>') && tiles.includes('"><svg onload=window.__xss=4>'), 'variantlardagi HTML matn sifatida');
    await t2.hover('.oct-tile >> nth=1');
    const injected = await t2.evaluate(() => ({
      flag: window.__xss,
      nodes: document.querySelectorAll('.oct-stage img, .oct-stage script, .oct-stage svg[onload], .oct-stage b[onmouseover], .games-active img').length,
    }));
    ok(injected.flag === undefined && injected.nodes === 0, 'oʻqituvchi ekranida hech qanday skript ishlamadi, HTML element yaratilmadi');
    await xs.click('.pl-answer >> nth=0');
    await hostPhase(t2, 'reveal');
    await t2.click('.oct-actions .btn.primary');
    await hostPhase(t2, 'leaderboard');
    await t2.click('.oct-actions .btn.primary');
    await hostPhase(t2, 'podium');
    await studentPhase(xs, 'podium');
    ok(await xs.evaluate(() => window.__xss === undefined && !document.querySelector('#play img, #play script')), 'oʻquvchi sahifasida ham skript ishlamadi');
    ok(await t2.evaluate(() => window.__xss === undefined), 'podiumda ham skript ishlamadi');

    console.log('18) eskirgan (12 soatdan eski) saqlangan oʻyinchi maʼlumoti ishlatilmaydi va oʻchiriladi');
    const stale = await studentPage(browser, 375, 'stale');
    await stale.goto(`${BASE}/play`);
    await stale.evaluate(([p, me]) => localStorage.setItem(`oct:${p}`, JSON.stringify(me)),
      [g2.pin, { id: 'eski', tok: 'y'.repeat(32), nick: 'Eski', at: Date.now() - 13 * 3600 * 1000 }]);
    await stale.goto(`${BASE}/play/${g2.pin}`);
    await stale.waitForSelector('input[autocomplete=nickname]');
    ok(await stale.evaluate((p) => localStorage.getItem(`oct:${p}`) === null, g2.pin), 'eskirgan ID/token eʼtiborsiz qoldirildi va oʻchirildi (ism soʻraladi)');

    console.log('19) oʻqituvchi yangi qoʻshilishlarni yopadi va qayta ochadi');
    await t2.goto(`${BASE}/?app#/games/octagon/${g2.pin}`);
    await t2.waitForSelector('.oct-lock:not([hidden])');
    await t2.click('.oct-lock');
    await t2.waitForSelector('.oct-lock.on[aria-pressed=true]');
    await stale.fill('input[autocomplete=nickname]', 'Kechikkan');
    await stale.click('button[type=submit]');
    await stale.waitForFunction(() => /toʻxtatgan/.test(document.querySelector('.pl-error')?.textContent || ''));
    ok(true, 'qoʻshilish yopiq: yangi oʻquvchiga tushunarli xabar');
    await t2.click('.oct-lock');
    await t2.waitForSelector('.oct-lock:not(.on)');
    await stale.fill('input[autocomplete=nickname]', 'Kechikkan');
    await stale.click('button[type=submit]');
    await studentPhase(stale, 'reveal');
    ok((await stale.textContent('.pl-nick')) === 'Kechikkan', 'qoʻshilish qayta ochildi — oʻquvchi kirdi');

    ok(twoChecked, 'ha/yoʻq (2 variantli) savol maketi tekshirildi');
    console.log(`\nbrauzer xatolari: ${errors.length ? `\n${errors.join('\n')}` : 'yoʻq'}`);
    if (errors.length) throw new Error('brauzer konsolida xatolar bor');
    console.log(`\nHAMMASI OʻTDI: ${checks} ta tekshiruv. Skrinshotlar: ${OUT}`);
  } finally {
    await browser.close();
    server.proc.kill();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
