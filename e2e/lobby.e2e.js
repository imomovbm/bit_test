// Duel bosh sahifasi (lobbi + mavzular katalogi) va boshqaruvdagi mavzular faolligi — brauzerda to'liq tekshiruv (Playwright).
//
// Ishga tushirish (loyiha ildizidan):  node e2e/lobby.e2e.js
// Talab: Node.js va Playwright (npm i -D playwright && npx playwright install chromium). Ilovaning o'ziga kerak emas.
// Skript o'zi vaqtinchalik baza bilan server ishga tushiradi (TD_DUEL_QUESTIONS=3, TD_RANKING_REFRESH=1 — sinov tezroq
// o'tishi uchun), akkauntlar va mavzular yaratadi, so'ng:
//   * A mavzuni tanlab raqib kutadi -> B buni sahifani yangilamasdan (jonli) ko'radi va bir bosishda qo'shiladi;
//   * ikkalasi duelni oxirigacha o'ynaydi -> mavzuning oxirgi o'yini va soni yangilanadi -> «Bugun» ro'yxatida yuqoriga chiqadi;
//   * ikki o'yinchi bitta seekka bir vaqtda qo'shiladi -> aynan bittasi duelga kiradi, ikkinchisi «allaqachon» xabarini oladi;
//   * kutishni bekor qilish boshqalarda jonli ko'rinadi; lobbi xabarlarida foydalanuvchi identifikatorlari yo'q;
//   * qidiruv va «Yana yuklash» (sahifalash), boshqaruvdagi mavzular ro'yxati (saralash, ommaviy yopish), yopilgan mavzu
//     bosh sahifadan yo'qoladi va o'sha mavzuda kutayotgan o'yinchiga xabar boradi;
//   * 360, 375, 768 va 1280 px kengliklarda: gorizontal siljish yo'q, bosiladigan elementlar ≥ 48px (telefonda), matnlar kesilmagan.
// Skrinshotlar: e2e/screenshots/ (yoki OUT muhit o'zgaruvchisi).
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.OUT || path.join(__dirname, 'screenshots');
const PORT = Number(process.env.PORT || 8767);
const BASE = `http://127.0.0.1:${PORT}`;
const WIDTHS = [360, 375, 768, 1280];
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let checks = 0;
function ok(cond, msg) {
  if (!cond) throw new Error(`FAIL: ${msg}`);
  checks += 1;
  console.log(`  ✓ ${msg}`);
}

const QUESTIONS = Array.from({ length: 6 }, (_, i) => [`Sinov savoli ${i + 1}?`, ['Birinchi', 'Ikkinchi', 'Uchinchi', 'Toʻrtinchi'], i % 4]);
const TOPIC_FILE = QUESTIONS.map(([q, opts, c]) => [q, ...opts.map((o, i) => (i === c ? `#${o}` : o))].join('\n====\n')).join('\n++++\n');
const TARGET = 'Zoologiya E2E'; // alifbo bo'yicha oxirgi va hali o'ynalmagan — «Bugun» ro'yxatining oxirida turadi
const TOPICS = ['Algebra E2E', 'Biologiya E2E', 'Geometriya E2E', 'Tarix E2E', 'Fizika E2E', TARGET];
const EXTRA = 40; // sahifalash va qidiruvni tekshirish uchun qo'shimcha mavzular
const XSS = '<img src=x onerror="window.__xss=1"> XSS sinov'; // HTML nomli mavzu — faqat matn bo'lib ko'rinishi kerak
const TOTAL = TOPICS.length + EXTRA + 1;

// ------------------------------------------------------------------ server
async function startServer() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lobby-e2e-'));
  const proc = spawn('python3', ['run.py', '--port', String(PORT), '--host', '127.0.0.1', '--db', path.join(dir, 'e2e.db')], {
    cwd: ROOT,
    env: { ...process.env, TD_SUPERADMIN_PASSWORD: 'owner123', TD_DUEL_QUESTIONS: '3', TD_RANKING_REFRESH: '1' },
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

const ids = {};
async function seed() {
  const owner = (await apiAs('', 'POST', '/api/auth/login', { login: 'admin', password: 'owner123' })).cookie;
  for (const login of ['alisher', 'bobur', 'charos', 'dilnoza', 'eldor']) {
    const r = await apiAs(owner, 'POST', '/api/admin/users', { login, password: '1234' });
    if (r.status !== 201) throw new Error(`user ${login}: ${r.status}`);
  }
  for (const name of [...TOPICS, ...Array.from({ length: EXTRA }, (_, i) => `Qoʻshimcha ${String(i + 1).padStart(2, '0')}`), XSS]) {
    const t = await apiAs(owner, 'POST', '/api/admin/topics', { name, content: TOPIC_FILE, shuffle: false });
    if (t.status !== 201) throw new Error(`topic ${name}: ${t.status}`);
    ids[name] = t.data.topic.id;
  }
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

async function loginPage(browser, login, width = 1280, hash = '/duel') {
  const mobile = width < 700;
  const ctx = await browser.newContext({ viewport: { width, height: mobile ? 760 : 900 }, isMobile: mobile, hasTouch: mobile });
  const page = await ctx.newPage();
  watch(page, `${login}@${width}`);
  page.frames = [];
  page.on('websocket', (ws) => ws.on('framereceived', (f) => page.frames.push(String(f.payload))));
  await page.goto(`${BASE}/#/login`);
  const st = await page.evaluate(async (l) => (await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login: l, password: l === 'admin' ? 'owner123' : '1234' }),
  })).status, login);
  if (st !== 200) throw new Error(`${login}: login ${st}`);
  await page.goto(`${BASE}/?app#${hash}`);
  return page;
}

/** Kirish animatsiyalari tugashini kutadi — o'lchamlar animatsiya o'rtasida o'lchanmasin. */
async function settle(page) {
  await page.evaluate(() => Promise.all(document.getAnimations()
    .filter((a) => a.effect && a.effect.getTiming().iterations !== Infinity)
    .map((a) => a.finished.catch(() => null))));
}

async function noOverflow(page, label) {
  await settle(page);
  const { extra, wide } = await page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.width && r.right > window.innerWidth + 0.5 && getComputedStyle(el).position !== 'fixed') {
        out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join('.')} right=${Math.round(r.right)}`);
      }
    }
    return { extra: document.documentElement.scrollWidth - window.innerWidth, wide: out.slice(0, 6) };
  });
  ok(extra <= 0, `${label}: gorizontal siljish yoʻq (${extra}px)${extra > 0 ? ` — ${wide.join(', ')}` : ''}`);
}

/** Bosiladigan elementlar kamida 48×48 px (telefon uchun). */
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
      const cut = el.scrollWidth > el.clientWidth + 1;
      const outside = r.left < -0.5 || r.right > window.innerWidth + 0.5;
      if (cut || outside) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join('.')} «${el.textContent.trim().slice(0, 24)}»`);
    }
    return out;
  }, selectors);
  ok(bad.length === 0, `${label}: matnlar kesilmagan${bad.length ? ` — ${bad.join(', ')}` : ''}`);
}

async function shot(page, name, fullPage = false) {
  await settle(page);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage });
}

async function topicNames(page) {
  return page.$$eval('.browse .topic-card:not(.skeleton) .topic-name', (els) => els.map((e) => e.textContent));
}

async function openTab(page, label) {
  await page.click(`.period-tab:has-text("${label}")`);
  await page.waitForSelector('.browse .topic-card:not(.skeleton)');
  await page.waitForFunction(() => !document.querySelector('.topic-grid[aria-busy]'));
}

/** Duelni oxirigacha o'ynaydi (har savolda birinchi variant) va natija ekranini kutadi. */
async function playDuel(page) {
  for (let i = 0; i < 200; i++) {
    if (await page.$('.screen.result')) return;
    const btn = await page.$('.option:not([disabled])');
    if (btn) await btn.click().catch(() => {});
    await sleep(150);
  }
  throw new Error('duel tugamadi');
}

// ------------------------------------------------------------------ test
(async () => {
  const server = await startServer();
  const browser = await chromium.launch();
  try {
    const owner = await seed();

    console.log('1) bosh sahifa: katalog, davrlar, qidiruv, sahifalash');
    const bob = await loginPage(browser, 'bobur', 375);
    await bob.waitForSelector('.lobby .seek-card .seek-empty');
    ok(true, 'B lobbini ochdi: hozircha hech kim kutmayapti (boʻsh holat)');
    await bob.waitForSelector('.browse .topic-card:not(.skeleton)');
    const firstPage = await topicNames(bob);
    ok(firstPage.length === 24, `katalog sahifalab yuklanadi: birinchi sahifada 24 ta (jami ${TOPICS.length + EXTRA})`);
    ok((await bob.textContent('.browse-summary')).includes(`${TOTAL} ta mavzu`), 'jami mavzular soni koʻrsatiladi');
    await bob.click('.browse-more-btn');
    await bob.waitForFunction((n) => document.querySelectorAll('.browse .topic-card:not(.skeleton)').length === n, TOTAL);
    ok(true, `«Yana yuklash» qolgan mavzularni olib keladi (${TOTAL} ta)`);
    await openTab(bob, 'Bugun');
    await bob.click('.browse-more-btn'); // o'ynalmagan mavzu ro'yxat oxirida — ikkinchi sahifada
    await bob.waitForFunction((n) => document.querySelectorAll('.browse .topic-card:not(.skeleton)').length === n, TOTAL);
    let today = await topicNames(bob);
    const before = today.indexOf(TARGET);
    ok(before > 0, `«Bugun»: «${TARGET}» hali oʻynalmagan — roʻyxatda ${before + 1}-oʻrinda`);
    await bob.fill('.browse-search input', 'zoolog');
    await bob.waitForFunction((n) => {
      const names = [...document.querySelectorAll('.browse .topic-card:not(.skeleton) .topic-name')].map((e) => e.textContent);
      return names.length === 1 && names[0] === n;
    }, TARGET);
    ok(true, 'qidiruv (kechiktirilgan) serverdan faqat mos mavzuni qaytaradi');
    await bob.fill('.browse-search input', 'xss sinov');
    await bob.waitForFunction(() => {
      const cards = document.querySelectorAll('.browse .topic-card:not(.skeleton)');
      return cards.length === 1 && cards[0].textContent.includes('XSS sinov');
    });
    const xssCard = await bob.$eval('.browse .topic-card:not(.skeleton)', (el) => ({
      text: el.querySelector('.topic-name').textContent, imgs: el.querySelectorAll('img').length, fired: window.__xss === 1,
    }));
    ok(xssCard.text === XSS && xssCard.imgs === 0 && !xssCard.fired, 'XSS: mavzu nomidagi HTML faqat matn sifatida chiqadi (element yaratilmaydi)');
    await bob.fill('.browse-search input', 'yoʻq-bunday-mavzu');
    await bob.waitForSelector('.browse .empty');
    ok((await bob.textContent('.browse .empty')).includes('Hech narsa topilmadi'), 'topilmasa — tushunarli boʻsh holat');
    await bob.fill('.browse-search input', '');
    await bob.waitForFunction(() => document.querySelectorAll('.browse .topic-card:not(.skeleton)').length === 24);

    console.log('2) A raqib kutadi -> B buni jonli koʻradi va bir bosishda qoʻshiladi');
    const ali = await loginPage(browser, 'alisher', 1280);
    await ali.waitForSelector('.browse .topic-card:not(.skeleton)');
    await ali.fill('.browse-search input', 'zoolog');
    await ali.waitForFunction((n) => {
      const c = [...document.querySelectorAll('.browse .topic-card:not(.skeleton) .topic-name')];
      return c.length === 1 && c[0].textContent === n;
    }, TARGET);
    await ali.click('.browse .topic-card:not(.skeleton)');
    await ali.waitForSelector('.screen.waiting');
    ok((await ali.textContent('.waiting .topic-pill')).includes(TARGET), 'A kutish ekranida: mavzu nomi va taklif havolasi');
    await bob.waitForFunction(() => [...document.querySelectorAll('.seek-card .seek-row .seek-login')].some((e) => e.textContent.includes('alisher')), null, { timeout: 4000 });
    ok(true, 'B sahifani yangilamasdan Aʼning taklifini koʻrdi (jonli yangilanish ≤ 1 s)');
    const row = await bob.$('.seek-card .seek-row:has(.seek-login:has-text("alisher"))');
    ok((await row.textContent()).includes(TARGET), 'qatorda: taxallus, mavzu va kutish vaqti');
    await bob.waitForSelector('.lobby .live-topic:has-text("Zoologiya")');
    ok(/1 kutmoqda/.test(await bob.textContent('.lobby .live-topic')), '«Hozir faol mavzular»: 1 kutmoqda');
    // lobbi xabarlarida faqat taxallus — foydalanuvchi identifikatorlari yo'q
    const lobbyFrames = bob.frames.map((f) => JSON.parse(f)).filter((m) => m.t === 'lobby' || m.t === 'lobby:diff');
    const seekViews = lobbyFrames.flatMap((m) => (m.t === 'lobby' ? m.d.seeks : m.d.add || []));
    ok(seekViews.length > 0 && seekViews.every((s) => Object.keys(s).sort().join(',') === 'id,login,mine,since,topicId,topicName'),
      'lobbi xabarlarida faqat seek, taxallus, mavzu va vaqt (foydalanuvchi id va IP yoʻq)');
    for (const w of WIDTHS) {
      await bob.setViewportSize({ width: w, height: w < 700 ? 760 : 900 });
      await sleep(250);
      await noOverflow(bob, `bosh sahifa (lobbi) ${w}px`);
      await notClipped(bob, '.seek-login, .seek-topic, .topic-name, .period-tab, .quick-any, .lt-name', `bosh sahifa ${w}px`);
      if (w < 700) await tapTargets(bob, '.lobby', `bosh sahifa ${w}px`);
      await bob.evaluate(() => window.scrollTo(0, 0));
      await sleep(150);
      await shot(bob, `main-${w}`);
      // katalog bo'limi: yopishqoq sarlavha ostida qolmasligi uchun undan pastroqqa aylantiriladi
      await bob.evaluate(() => window.scrollTo(0, document.querySelector('.browse').getBoundingClientRect().top + window.scrollY - 76));
      await sleep(150);
      await shot(bob, `main-catalog-${w}`);
      await bob.evaluate(() => window.scrollTo(0, 0));
    }
    await bob.setViewportSize({ width: 375, height: 760 });
    await bob.click('.seek-card .seek-row:has(.seek-login:has-text("alisher")) .seek-btn');
    await Promise.all([bob.waitForSelector('.vs-screen'), ali.waitForSelector('.vs-screen')]);
    ok(true, 'B bir bosishda qoʻshildi: ikkalasida duel sanogʻi boshlandi');

    console.log('3) duel oxirigacha -> faollik yangilanadi -> mavzu «Bugun»da yuqoriga chiqadi');
    await Promise.all([playDuel(ali), playDuel(bob)]);
    ok(true, 'duel tugadi: ikkalasida natija ekrani');
    let browse = null;
    for (let i = 0; i < 30; i++) { // reyting keshi TD_RANKING_REFRESH (1 s) dan keyin yangilanadi
      browse = (await apiAs(owner, 'GET', '/api/topics/browse?period=today&limit=60')).data;
      if (browse.items[0].name === TARGET) break;
      await sleep(200);
    }
    const top = browse.items[0];
    ok(top.name === TARGET && top.today === 1 && top.totalDuels === 1, `API: «${TARGET}» «Bugun» roʻyxatida 1-oʻrinda (bugun 1 ta duel)`);
    ok(top.lastPlayedAt && Date.now() - top.lastPlayedAt < 120000, 'oxirgi oʻyin vaqti (last_played_at) yangilandi');
    await bob.click('.result-actions .btn.ghost');
    await bob.waitForSelector('.lobby .browse .topic-card:not(.skeleton)');
    await openTab(bob, 'Bugun');
    today = await topicNames(bob);
    ok(today[0] === TARGET, `UI «Bugun»: «${TARGET}» ${before + 1}-oʻrindan 1-oʻringa chiqdi`);
    ok((await bob.textContent('.browse .topic-card:not(.skeleton) .topic-hint')).includes('Bugun 1 ta duel'), 'kartochkada izoh: «Bugun 1 ta duel · oxirgi oʻyin: hozirgina»');
    const adm = (await apiAs(owner, 'GET', '/api/admin/topic-activity?sort=lastPlayed&dir=desc&per=5')).data;
    ok(adm.items[0].name === TARGET && adm.items[0].totalDuels === 1 && adm.items[0].duels30 === 1, 'boshqaruv roʻyxatida: oxirgi oʻyin, jami 1, 30 kunda 1');
    await ali.click('.result-actions .btn.ghost');

    console.log('4) ikki oʻyinchi bitta seekka bir vaqtda qoʻshiladi -> aynan bittasi yutadi');
    const charos = await loginPage(browser, 'charos', 1280);
    const dilnoza = await loginPage(browser, 'dilnoza', 360);
    const eldor = await loginPage(browser, 'eldor', 768);
    for (const p of [charos, dilnoza]) await p.waitForSelector('.lobby .seek-card');
    await eldor.waitForSelector('.lobby .quick-any');
    await eldor.click('.lobby .quick-any'); // «istalgan mavzu» — hech kim kutmayapti, shuning uchun kutadi
    await eldor.waitForSelector('.screen.waiting');
    ok((await eldor.textContent('.waiting .topic-pill')).includes('Istalgan mavzu'), '«Istalgan mavzu» bilan kutish (qoida ekranda tushuntirilgan)');
    await shot(eldor, 'lobby-waiting-768');
    for (const p of [charos, dilnoza]) {
      await p.waitForSelector('.seek-card .seek-row:has(.seek-login:has-text("eldor")) .seek-btn');
    }
    await Promise.all([
      charos.click('.seek-card .seek-row:has(.seek-login:has-text("eldor")) .seek-btn'),
      dilnoza.click('.seek-card .seek-row:has(.seek-login:has-text("eldor")) .seek-btn'),
    ]);
    await eldor.waitForSelector('.vs-screen');
    await sleep(800);
    const inDuel = [];
    for (const [name, p] of [['charos', charos], ['dilnoza', dilnoza]]) if (await p.$('.vs-screen, .screen.play')) inDuel.push(name);
    ok(inDuel.length === 1, `bir vaqtda ikki bosish: aynan bittasi (${inDuel[0]}) duelga kirdi`);
    const loser = inDuel[0] === 'charos' ? dilnoza : charos;
    await loser.waitForSelector('.toast:has-text("allaqachon")');
    ok(true, 'ikkinchisiga «allaqachon boshqa raqib bilan juftlandi» xabari chiqdi');
    await loser.waitForFunction(() => ![...document.querySelectorAll('.seek-card .seek-row .seek-login')].some((e) => e.textContent.includes('eldor')));
    ok(true, 'yutqazgan oʻyinchining roʻyxati yangilandi (band seek olib tashlandi)');

    console.log('5) kutishni bekor qilish jonli koʻrinadi; telefon kutish ekrani');
    await loser.click('.browse .topic-card:not(.skeleton)');
    await loser.waitForSelector('.screen.waiting');
    await bob.waitForFunction((n) => [...document.querySelectorAll('.seek-card .seek-row .seek-login')].some((e) => e.textContent.includes(n)), inDuel[0] === 'charos' ? 'dilnoza' : 'charos');
    ok(true, 'yangi kutish B roʻyxatida jonli paydo boʻldi');
    for (const w of [360, 375]) {
      await loser.setViewportSize({ width: w, height: 760 });
      await sleep(200);
      await noOverflow(loser, `kutish ekrani ${w}px`);
      await tapTargets(loser, '.screen.waiting', `kutish ekrani ${w}px`);
      await shot(loser, `lobby-waiting-${w}`);
    }
    await loser.click('.screen.waiting button:has-text("Bekor qilish")');
    await loser.waitForSelector('.lobby .seek-card');
    await bob.waitForFunction((n) => ![...document.querySelectorAll('.seek-card .seek-row .seek-login')].some((e) => e.textContent.includes(n)), inDuel[0] === 'charos' ? 'dilnoza' : 'charos');
    ok(true, 'bekor qilingan kutish B roʻyxatidan jonli olib tashlandi');

    console.log('6) boshqaruv: mavzular faolligi, saralash, ommaviy yopish, jurnal');
    const admin = await loginPage(browser, 'admin', 1280, '/admin/topics');
    await admin.waitForSelector('.adm-activity-table tbody tr');
    await admin.click('th button.th-sort:has-text("Oxirgi")'); // sana ustuni — birinchi bosishda yangisi oldin
    await admin.waitForFunction(() => document.querySelector('th[aria-sort="descending"] .th-sort')?.textContent.includes('Oxirgi'));
    await admin.waitForFunction((n) => document.querySelector('.adm-activity-table tbody tr .adm-topic-link')?.textContent === n, TARGET);
    ok(true, 'saralash «Oxirgi oʻyin» (yangisi oldin): oʻynalgan mavzu birinchi');
    // «Tarix E2E» mavzusida kimdir kutib turibdi — yopilganda unga xabar boradi
    await bob.click('.browse-search input');
    await bob.fill('.browse-search input', 'Tarix E2E');
    await bob.waitForFunction(() => document.querySelectorAll('.browse .topic-card:not(.skeleton)').length === 1);
    await bob.click('.browse .topic-card:not(.skeleton)');
    await bob.waitForSelector('.screen.waiting');
    await admin.fill('.adm-search input', 'xss sinov');
    await admin.waitForFunction(() => {
      const rows = document.querySelectorAll('.adm-activity-table tbody tr');
      return rows.length === 1 && rows[0].textContent.includes('XSS sinov');
    });
    const xssRow = await admin.$eval('.adm-activity-table tbody tr', (el) => ({
      text: el.querySelector('.adm-topic-link').textContent, imgs: el.querySelectorAll('img').length, fired: window.__xss === 1,
    }));
    ok(xssRow.text === XSS && xssRow.imgs === 0 && !xssRow.fired, 'XSS: boshqaruv roʻyxatida ham faqat matn');
    await admin.fill('.adm-search input', 'E2E');
    await admin.waitForFunction(() => document.querySelectorAll('.adm-activity-table tbody tr').length === 6);
    for (const name of ['Tarix E2E', 'Fizika E2E']) await admin.click(`.adm-activity-table tbody tr:has(.adm-topic-link:text-is("${name}")) .bank-check input`);
    await admin.waitForSelector('.adm-selbar.has-sel');
    ok((await admin.textContent('.adm-selbar')).includes('2 ta mavzu tanlandi'), 'ikki mavzu tanlandi — ommaviy amallar paneli');
    await admin.click('.adm-selbar .btn.danger');
    await admin.waitForSelector('.modal-overlay.show');
    ok((await admin.textContent('.modal')).includes('2 ta mavzu yopiladi'), 'tasdiqlashda yopiladigan mavzular soni koʻrsatiladi');
    await admin.click('.modal-foot .btn.danger');
    await admin.waitForSelector('.toast:has-text("2 ta mavzu yopildi")');
    ok(true, 'ommaviy yopish bajarildi');
    await bob.waitForSelector('.toast:has-text("yopildi")', { timeout: 5000 });
    await bob.waitForSelector('.lobby .seek-card');
    ok(true, 'yopilgan mavzuda kutayotgan oʻyinchiga xabar bordi va u lobbiga qaytdi');
    const after = (await apiAs(owner, 'GET', '/api/topics/browse?period=all&limit=60')).data;
    ok(!after.items.some((t) => t.name === 'Tarix E2E' || t.name === 'Fizika E2E') && after.total === TOTAL - 2, 'yopilgan mavzular bosh sahifadan yoʻqoldi (tarix saqlanadi)');
    await admin.click('.adm-views button:has-text("Jurnal")');
    await admin.waitForSelector('.adm-log-table tbody tr');
    ok((await admin.$$('.adm-log-table tbody tr')).length === 2, 'jurnalda ikkala yopish yozilgan (kim, qachon, sabab)');
    await admin.click('.adm-views button:has-text("tavsiya")');
    await admin.waitForSelector('.adm-auto .adm-reg-text'); // sozlamalar yuklangach chiziladi
    ok((await admin.textContent('.adm-auto')).includes('Oʻchiq (standart)'), 'avtomatik yopish standart holatda oʻchiq');
    await admin.click('.adm-views button:has-text("Barcha")');
    await admin.waitForSelector('.adm-activity-table tbody tr');
    for (const w of WIDTHS) {
      await admin.setViewportSize({ width: w, height: w < 700 ? 760 : 900 });
      await sleep(250);
      await admin.evaluate(() => document.querySelector('.adm-views').scrollIntoView());
      await noOverflow(admin, `boshqaruv mavzular roʻyxati ${w}px`);
      await notClipped(admin, '.adm-topic-link, .adm-filter, .th-sort', `boshqaruv roʻyxati ${w}px`);
      if (w < 700) await tapTargets(admin, '.adm-topics-panel, .adm-views', `boshqaruv roʻyxati ${w}px`);
      await shot(admin, `admin-topics-${w}`);
    }

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
