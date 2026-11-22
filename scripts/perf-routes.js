// Sahifalar hajmi va yuklanish tezligi (Playwright): har bir marshrut uchun yuklangan JS/CSS/HTML (xom va gzip),
// sekin mobil tarmoq + sekin protsessorda birinchi va takroriy ochilish vaqti, kesh sarlavhalari.
//
// Ishga tushirish (loyiha ildizidan):  node scripts/perf-routes.js [--json natija.json] [--port 8771]
// Skript o'zi vaqtinchalik baza bilan server ishga tushiradi (o'qituvchi, mavzu va bitta Octagon o'yini yaratiladi).
//
// Tarmoq: "Slow 4G" (Lighthouse): 150 ms RTT, 1.6 Mbit/s yuklab olish, 750 kbit/s yuborish; protsessor — 4x sekin
// (o'rta darajali telefon). "Foydalanishga tayyor" — sahifaning asosiy kiritish maydoni/tugmasi ko'ringan payt.
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const opt = (name, def) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : def;
};
const PORT = Number(opt('--port', 8771));
const BASE = `http://127.0.0.1:${PORT}`;
const JSON_OUT = opt('--json', null);
const RUNS = Number(opt('--runs', 3));
const SLOW_4G = { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 };
const CPU_SLOWDOWN = 4;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function startServer() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'perf-routes-'));
  const proc = spawn('python3', ['run.py', '--port', String(PORT), '--host', '127.0.0.1', '--db', path.join(dir, 'perf.db')], {
    cwd: ROOT, env: { ...process.env, TD_SUPERADMIN_PASSWORD: 'owner123' }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  proc.stdout.on('data', (d) => { log += d; });
  proc.stderr.on('data', (d) => { log += d; });
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${BASE}/api/auth/me`)).ok) return { proc, log: () => log };
    } catch { /* hali ishga tushmagan */ }
    await sleep(100);
  }
  proc.kill();
  throw new Error(`server ishga tushmadi:\n${log}`);
}

async function apiAs(cookie, method, url, body) {
  const r = await fetch(BASE + url, { method, headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, data: await r.json().catch(() => null), cookie: (r.headers.get('set-cookie') || '').split(';')[0] };
}

async function seed() {
  const owner = (await apiAs('', 'POST', '/api/auth/login', { login: 'admin', password: 'owner123' })).cookie;
  const content = Array.from({ length: 6 }, (_, i) => [`Savol ${i + 1}?`, '#Toʻgʻri', 'Notoʻgʻri', 'Yana', 'Boshqa'].join('\n====\n')).join('\n++++\n');
  const t = await apiAs(owner, 'POST', '/api/admin/topics', { name: 'Perf mavzu', content, shuffle: false });
  const g = await apiAs(owner, 'POST', '/api/octagon/games', { topicId: t.data.topic.id, timeLimit: 20, questionCount: 5 });
  return { owner, pin: g.data.game.pin };
}

const ROUTES = (pin) => [
  { name: 'student-join (/play)', url: `/play`, ready: '.pl-pin-input', login: false },
  { name: 'student-join with PIN (/play/PIN)', url: `/play/${pin}`, ready: '.pl-view-nick input, .pl-nick-input, input[autocomplete="nickname"]', login: false },
  { name: 'login (/)', url: '/#/login', ready: 'form input[type=password]', login: false },
  { name: 'teacher game (/#/games/octagon/PIN)', url: `/?app#/games/octagon/${pin}`, ready: '.oct-hero-pin', login: true },
];

function kind(url, type) {
  if (type) {
    if (type.includes('javascript')) return 'js';
    if (type.includes('css')) return 'css';
    if (type.includes('html')) return 'html';
    if (type.includes('json')) return 'json';
    if (type.includes('image') || type.includes('svg')) return 'img';
  }
  return path.extname(new URL(url).pathname).slice(1) || 'other';
}

async function measure(browser, route, cookie) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 800 }, isMobile: true, hasTouch: true });
  if (route.login) {
    const [name, value] = cookie.split('=');
    await ctx.addCookies([{ name, value, domain: '127.0.0.1', path: '/', httpOnly: true }]);
  }
  // Joylashuv siljishi (CLS): sahifa yuklanayotganda elementlar sakrab ketmasligi kerak
  await ctx.addInitScript(() => {
    window.__cls = 0;
    try {
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cls += e.value;
      }).observe({ type: 'layout-shift', buffered: true });
    } catch { /* eski brauzer */ }
  });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', SLOW_4G);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU_SLOWDOWN });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const results = [];
  for (const visit of ['cold', 'repeat']) {
    const resources = [];
    const onResponse = async (r) => {
      const req = r.request();
      if (req.resourceType() === 'websocket') return;
      let body = Buffer.alloc(0);
      try {
        body = await r.body();
      } catch { /* 304/redirect */ }
      const h = r.headers();
      resources.push({
        url: new URL(r.url()).pathname, status: r.status(), kind: kind(r.url(), h['content-type']),
        raw: body.length, gz: body.length ? zlib.gzipSync(body, { level: 9 }).length : 0,
        encoding: h['content-encoding'] || '', cache: h['cache-control'] || '', etag: !!h.etag, fromCache: r.fromServiceWorker() ? 'sw' : '',
      });
    };
    await page.goto('about:blank'); // takroriy ochilish ham to'liq yuklanish bo'lsin (faqat # o'zgarishi emas)
    page.on('response', onResponse);
    const t0 = Date.now();
    await page.goto(BASE + route.url, { waitUntil: 'commit' });
    await page.waitForSelector(route.ready, { state: 'visible', timeout: 60000 });
    const usable = await page.evaluate(() => performance.now());
    await page.waitForLoadState('load');
    await sleep(300);
    const nav = await page.evaluate(() => {
      const n = performance.getEntriesByType('navigation')[0];
      const paint = performance.getEntriesByType('paint').find((p) => p.name === 'first-contentful-paint');
      const res = performance.getEntriesByType('resource').map((r) => ({ name: new URL(r.name).pathname, transfer: r.transferSize, encoded: r.encodedBodySize, decoded: r.decodedBodySize }));
      return { ttfb: n.responseStart, dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd, fcp: paint ? paint.startTime : null, res, docTransfer: n.transferSize, cls: window.__cls || 0 };
    });
    page.off('response', onResponse);
    const transferred = nav.docTransfer + nav.res.reduce((a, r) => a + (r.transfer || 0), 0);
    // tarmoqqa chiqqan so'rovlar (disk/xotira keshidan olinganlari — transferSize 0 — hisoblanmaydi; 304 hisoblanadi)
    const networkRequests = (nav.docTransfer > 0 ? 1 : 0) + nav.res.filter((r) => r.transfer > 0).length;
    results.push({ visit, usableMs: Math.round(usable), fcpMs: nav.fcp && Math.round(nav.fcp), dclMs: Math.round(nav.dcl), loadMs: Math.round(nav.load), wallMs: Date.now() - t0, transferredBytes: transferred, networkRequests, cls: Math.round(nav.cls * 1000) / 1000, resources });
  }
  await ctx.close();
  return { results, errors };
}

function summarize(route, runs) {
  const cold = runs.map((r) => r.results[0]);
  const repeat = runs.map((r) => r.results[1]);
  const med = (xs) => xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)];
  const res = cold[0].resources.filter((r) => ['js', 'css', 'html'].includes(r.kind));
  const sum = (k, f) => res.filter((r) => r.kind === k).reduce((a, r) => a + r[f], 0);
  return {
    route: route.name,
    js: { files: res.filter((r) => r.kind === 'js').length, raw: sum('js', 'raw'), gzip: sum('js', 'gz') },
    css: { raw: sum('css', 'raw'), gzip: sum('css', 'gz') },
    html: { raw: sum('html', 'raw'), gzip: sum('html', 'gz') },
    coldUsableMs: med(cold.map((r) => r.usableMs)),
    coldFcpMs: med(cold.map((r) => r.fcpMs || 0)),
    repeatUsableMs: med(repeat.map((r) => r.usableMs)),
    coldTransferred: med(cold.map((r) => r.transferredBytes)),
    repeatTransferred: med(repeat.map((r) => r.transferredBytes)),
    repeatRequests: repeat[0].resources.length,
    repeatNetworkRequests: med(repeat.map((r) => r.networkRequests)),
    coldCls: Math.max(...cold.map((r) => r.cls)),
    contentEncoding: [...new Set(res.map((r) => r.encoding || '-'))].join(','),
    cacheHeaders: Object.fromEntries(cold[0].resources.filter((r) => ['js', 'css', 'html'].includes(r.kind)).map((r) => [r.url, r.cache || '(none)'])),
    files: res.map((r) => `${r.url} ${r.raw}B gz${r.gz}B`),
  };
}

(async () => {
  const server = await startServer();
  const browser = await chromium.launch();
  try {
    const { owner, pin } = await seed();
    const out = [];
    const allErrors = [];
    for (const route of ROUTES(pin)) {
      const runs = [];
      for (let i = 0; i < RUNS; i++) {
        const m = await measure(browser, route, owner);
        allErrors.push(...m.errors);
        runs.push(m);
      }
      const s = summarize(route, runs);
      out.push(s);
      console.log(`\n${s.route}`);
      console.log(`  JS ${s.js.files} fayl: ${(s.js.raw / 1024).toFixed(1)} KB (gzip ${(s.js.gzip / 1024).toFixed(1)} KB) · CSS ${(s.css.raw / 1024).toFixed(1)} KB (gzip ${(s.css.gzip / 1024).toFixed(1)} KB) · HTML ${(s.html.raw / 1024).toFixed(1)} KB`);
      console.log(`  sovuq: foydalanishga tayyor ${s.coldUsableMs} ms (FCP ${s.coldFcpMs} ms), uzatilgan ${(s.coldTransferred / 1024).toFixed(1)} KB, kodlash: ${s.contentEncoding}`);
      console.log(`  takroriy: ${s.repeatUsableMs} ms, uzatilgan ${(s.repeatTransferred / 1024).toFixed(1)} KB, tarmoqqa ${s.repeatNetworkRequests} ta so'rov (jami ${s.repeatRequests}) · CLS ${s.coldCls}`);
    }
    // API va ochiq ma'lumotlar uchun kesh sarlavhalari
    const headersOf = async (url, cookie) => {
      const r = await fetch(BASE + url, { headers: cookie ? { Cookie: cookie } : {} });
      await r.arrayBuffer();
      return { url, status: r.status, cacheControl: r.headers.get('cache-control'), etag: r.headers.get('etag'), encoding: r.headers.get('content-encoding') };
    };
    const api = [
      await headersOf('/api/auth/me', owner),
      await headersOf('/api/topics', owner),
      await headersOf('/api/stats/leaderboard', owner),
      await headersOf('/api/octagon/topics', owner),
      await headersOf('/api/topics/browse?period=hot', owner),
      await headersOf(`/api/octagon/games/${pin}`, owner),
    ];
    console.log('\nAPI sarlavhalari:');
    for (const a of api) console.log(`  ${a.url}: ${a.status} cache-control=${a.cacheControl} etag=${a.etag ? 'bor' : 'yoʻq'} encoding=${a.encoding || '-'}`);
    if (allErrors.length) console.log('\nbrauzer xatolari:', allErrors);
    if (JSON_OUT) fs.writeFileSync(JSON_OUT, JSON.stringify({ network: 'Slow 4G 150ms/1.6Mbps', cpu: `${CPU_SLOWDOWN}x`, routes: out, api }, null, 1));
  } finally {
    await browser.close();
    server.proc.kill();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
