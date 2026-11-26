// Octagon ovozi (static/js/octagon/audio.js) — birlik sinovlari: trek tanlash, natija ovozi tanlash (chegaralar),
// bosqich -> ovoz rejasi, sozlamalar va dvigatelning o'zi (soxta AudioContext va soxta taymerlar bilan).
//   node --test 'tests/js/*.test.js'        (qo'shimcha kutubxonasiz: Node'ning o'z sinov vositasi)
import { test, describe, beforeEach, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import {
  AUDIO, TRACKS, createAudio, gameSeed, pickResultSound, planFor, stepLength, trackFor, trackOrder,
} from '../../static/js/octagon/audio.js';

const RULES = { bands: [[60, 'cheer'], [30, 'hmm'], [0, 'oops']], nobody: 'soft' }; // app/config.py standart qiymatlari

// ============================================================ trek tanlash
describe('trek tanlash', () => {
  test("ketma-ket ikki savolda bir xil trek yo'q (blok chegaralarida ham)", () => {
    for (let seed = 0; seed < 400; seed++) {
      const order = trackOrder(seed * 7919 + 13, 100);
      for (let i = 1; i < order.length; i++) assert.notEqual(order[i], order[i - 1], `seed ${seed}, ${i}-savol`);
    }
  });

  test('har 5 savolda 5 ta trek bittadan (aralashtirilgan tartib)', () => {
    for (let seed = 0; seed < 200; seed++) {
      const order = trackOrder(gameSeed(String(100000 + seed), 1700000000000 + seed), 50);
      for (let b = 0; b < 50; b += 5) assert.deepEqual([...order.slice(b, b + 5)].sort(), [0, 1, 2, 3, 4]);
    }
  });

  test("tartib o'yinga qarab har xil (aralashtiriladi)", () => {
    const firsts = new Set();
    const orders = new Set();
    for (let i = 0; i < 300; i++) {
      const order = trackOrder(gameSeed(String(200000 + i), 1700000000000), 5);
      firsts.add(order[0]);
      orders.add(order.join(''));
    }
    assert.equal(firsts.size, 5);          // har bir trek birinchi bo'lishi mumkin
    assert.ok(orders.size > 60, `${orders.size}`); // 120 ta mumkin bo'lgan tartibdan ko'pi uchraydi
  });

  test("savol raqami bo'yicha aniq: sahifa yangilansa ham o'sha trek", () => {
    const seed = gameSeed('482913', 1764150000123);
    const order = trackOrder(seed, 40);
    for (let i = 0; i < 40; i++) {
      assert.equal(trackFor(seed, i), order[i]);
      assert.equal(trackFor(seed, i), trackFor(gameSeed('482913', 1764150000123), i)); // qayta hisoblash — o'sha natija
    }
    assert.equal(trackFor(seed, -1), 0);
    assert.equal(trackFor(seed, 1.5), 0);
  });

  test("o'yin urug'i: PIN va yaratilgan vaqtdan, barqaror", () => {
    assert.equal(gameSeed('123456', 1), gameSeed('123456', 1));
    assert.notEqual(gameSeed('123456', 1), gameSeed('123457', 1));
    assert.notEqual(gameSeed('123456', 1), gameSeed('123456', 2));
    assert.ok(Number.isInteger(gameSeed('x', undefined)) && gameSeed('x', undefined) >= 0);
  });
});

// ============================================================ natija ovozi
describe('natija ovozi tanlash', () => {
  const pick = (pct, answered = 10, rules = RULES) => pickResultSound({ correctPct: pct, answered }, rules);

  test('chegaralar: 29/30/59/60 %', () => {
    assert.equal(pick(29), 'oops');
    assert.equal(pick(30), 'hmm');
    assert.equal(pick(59), 'hmm');
    assert.equal(pick(60), 'cheer');
  });

  test('chetlar: 0 % va 100 %', () => {
    assert.equal(pick(0), 'oops');
    assert.equal(pick(100), 'cheer');
  });

  test("hech kim javob bermadi: yumshoq ovoz yoki (sozlamada) jimlik", () => {
    assert.equal(pickResultSound({ correctPct: null, answered: 0 }, RULES), 'soft');
    assert.equal(pickResultSound({ correctPct: null, answered: 0 }, { ...RULES, nobody: 'silent' }), null);
    assert.equal(pickResultSound({ answered: 0 }, RULES), 'soft');
  });

  test("bitta o'yinchi: to'g'ri — quvnoq, noto'g'ri — «oops»", () => {
    assert.equal(pick(100, 1), 'cheer');
    assert.equal(pick(0, 1), 'oops');
  });

  test("chegaralar serverdagi sozlamadan keladi (kod ichida raqam yo'q)", () => {
    const custom = { bands: [[75, 'cheer'], [40, 'hmm'], [0, 'oops']], nobody: 'soft' };
    assert.equal(pick(74, 10, custom), 'hmm');
    assert.equal(pick(75, 10, custom), 'cheer');
    assert.equal(pick(39, 10, custom), 'oops');
    assert.equal(pick(40, 10, custom), 'hmm');
  });

  test("jadval yo'q yoki buzilgan — jim (xato bermaydi)", () => {
    assert.equal(pickResultSound({ correctPct: 80, answered: 3 }, undefined), null);
    assert.equal(pickResultSound({ correctPct: 80, answered: 3 }, {}), null);
    assert.equal(pickResultSound(null, RULES), null);
  });
});

// ============================================================ bosqich -> reja
describe('bosqich -> ovoz rejasi', () => {
  const base = { pin: '111222', createdAt: 1764150000000, index: 2, sounds: RULES };
  const NOW = 1764150100000;

  test("musiqa savol ko'ringanda boshlanadi va javob vaqti tugaguncha; trek ikkala bosqichda bir xil", () => {
    const read = planFor({ ...base, phase: 'question_read', phaseStart: NOW - 1000, phaseEnd: NOW + 4000 }, NOW, 'leaderboard:1');
    const active = planFor({ ...base, phase: 'question_active', phaseStart: NOW, phaseEnd: NOW + 20000 }, NOW, read.key);
    assert.equal(read.music.track, trackFor(gameSeed(base.pin, base.createdAt), 2));
    assert.equal(active.music.track, read.music.track);
    assert.equal(read.music.stopAt, null);                 // o'qish vaqtida to'xtash vaqti yo'q
    assert.equal(active.music.stopAt, NOW + 20000);       // javob vaqti tugashi
    assert.equal(active.music.tenseAt, NOW + 20000 - AUDIO.tenseMs);
    assert.equal(read.sfx, null);
    assert.equal(active.sfx, null);
  });

  test("musiqa boshqa bosqichlarda yo'q", () => {
    for (const phase of ['lobby', 'topic_intro', 'question_result', 'leaderboard', 'podium_intro', 'reveal_3rd', 'reveal_2nd', 'reveal_1st', 'final_results']) {
      assert.equal(planFor({ ...base, phase }, NOW, 'x').music, null, phase);
    }
  });

  test('natija ovozi serverdagi foizdan; reyting, baraban va fanfaralar', () => {
    const res = (pct, answered) => planFor({ ...base, phase: 'question_result', correctPct: pct, answered }, NOW, 'question_active:2').sfx;
    assert.equal(res(80, 5), 'cheer');
    assert.equal(res(40, 5), 'hmm');
    assert.equal(res(20, 5), 'oops');
    assert.equal(res(null, 0), 'soft');
    assert.equal(planFor({ ...base, phase: 'leaderboard' }, NOW, 'question_result:2').sfx, 'board');
    const step = (phase, prev) => planFor({ ...base, phase, phaseStart: NOW - 100, phaseEnd: NOW + 3000 }, NOW, prev);
    assert.equal(step('podium_intro', 'question_result:2').sfx, 'roll');
    assert.equal(step('podium_intro', 'question_result:2').until, NOW + 3000);
    assert.equal(step('reveal_3rd', 'podium_intro:2').sfx, 'fanfare3');
    assert.equal(step('reveal_2nd', 'reveal_3rd:2').sfx, 'fanfare2');
    assert.equal(step('reveal_1st', 'reveal_2nd:2').sfx, 'fanfare1');
    assert.equal(step('final_results', 'reveal_1st:2').sfx, null);
  });

  test("sahifa endi ochilgan (oldingi holat yo'q) yoki bosqich ancha oldin boshlangan — effekt chalinmaydi", () => {
    assert.equal(planFor({ ...base, phase: 'question_result', correctPct: 90, answered: 4 }, NOW, null).sfx, null);
    assert.equal(planFor({ ...base, phase: 'leaderboard' }, NOW, 'leaderboard:2').sfx, null); // o'sha bosqich — yangilanish
    const late = planFor({ ...base, phase: 'reveal_2nd', phaseStart: NOW - AUDIO.freshMs - 1, phaseEnd: NOW + 1000 }, NOW, 'reveal_3rd:2');
    assert.equal(late.sfx, null);
  });

  test("lobbi va yakuniy natijalarda ovoz kerak emas (live=false), o'yin davomida — kerak", () => {
    assert.equal(planFor({ ...base, phase: 'lobby', index: -1 }, NOW, null).live, false);
    assert.equal(planFor({ ...base, phase: 'final_results' }, NOW, null).live, false);
    assert.equal(planFor({ ...base, phase: 'topic_intro', index: -1 }, NOW, null).live, true);
    assert.equal(planFor({ ...base, phase: 'question_result' }, NOW, null).live, true);
  });
});

// ============================================================ sozlamalar
describe('sozlamalar', () => {
  test("5 ta har xil trek: temp, tonallik, cholg'u", () => {
    assert.equal(TRACKS.length, AUDIO.tracks);
    assert.equal(TRACKS.length, 5);
    assert.equal(new Set(TRACKS.map((t) => t.name)).size, 5);
    assert.equal(new Set(TRACKS.map((t) => t.bpm)).size, 5);
    assert.equal(new Set(TRACKS.map((t) => t.root % 12)).size, 5);
    assert.ok(new Set(TRACKS.map((t) => t.lead.wave)).size >= 4);
  });

  test("har bir trek quvnoq (tez, major/miksolidiy) va naqshlari to'g'ri uzunlikda", () => {
    for (const t of TRACKS) {
      assert.ok(t.bpm >= 96 && t.bpm <= 150, t.name);
      assert.deepEqual(t.scale.slice(0, 5), [0, 2, 4, 5, 7], t.name);        // katta terts — major tusli
      assert.equal(t.melody.length, 64, t.name);
      assert.match(t.melody, /^[0-9a-e.-]+$/, t.name);
      assert.notEqual(t.melody[0], '-', t.name);
      assert.equal(t.chords.length, 4, t.name);
      assert.equal(t.bass.line.length, 16, t.name);
      for (const k of ['kick', 'snare', 'hat']) assert.match(t.drums[k], /^[x.]{16}$/, `${t.name}.${k}`);
    }
  });

  test("4 takt bir xil uzunlikda: sving va oxirgi soniyalar tempi aylanishni buzmaydi", () => {
    for (const t of TRACKS) {
      const loop = (tense) => Array.from({ length: 64 }, (_, i) => stepLength(t, i, tense)).reduce((a, b) => a + b, 0);
      assert.ok(Math.abs(loop(false) - (64 * 60) / t.bpm / 4) < 1e-9, t.name);
      assert.ok(loop(true) < loop(false) && loop(true) > loop(false) * 0.9, t.name); // biroz tezroq (≈ 6 %)
    }
  });

  test("vaqtlar: so'nish ~300 ms, oxirgi 5 soniya", () => {
    assert.equal(AUDIO.fadeMs, 300);
    assert.equal(AUDIO.tenseMs, 5000);
    assert.ok(AUDIO.cutMs > 0 && AUDIO.cutMs < AUDIO.fadeMs);
    assert.ok(AUDIO.tenseTempo > 1 && AUDIO.tenseTempo <= 1.1);
  });
});

// ============================================================ dvigatel (soxta AudioContext)
class FakeParam {
  constructor(value) {
    this.value = value;
    this.events = [];
  }

  setValueAtTime(v, t) {
    this.events.push(['set', v, t]);
    this.value = v;
  }

  linearRampToValueAtTime(v, t) {
    this.events.push(['lin', v, t]);
  }

  exponentialRampToValueAtTime(v, t) {
    if (!(v > 0)) throw new RangeError('exponential ramp to 0');
    this.events.push(['exp', v, t]);
  }

  setTargetAtTime(v, t, c) {
    this.events.push(['target', v, t, c]);
    this.value = v;
  }

  cancelScheduledValues(t) {
    this.events.push(['cancel', t]);
  }
}

class FakeNode {
  constructor(ctx, kind) {
    this.ctx = ctx;
    this.kind = kind;
    this.outs = new Set();
    ctx.nodes.push(this);
  }

  connect(dest) {
    this.outs.add(dest);
    return dest;
  }

  disconnect() {
    this.outs.clear();
    this.disconnected = true;
  }
}

class FakeSource extends FakeNode {
  start(t = 0) {
    if (this.ctx.state === 'closed') throw new Error('closed');
    this.startAt = t;
    this.ctx.starts.push(this);
  }

  stop(t = 0) {
    this.stopAt = t;
  }
}

class FakeCtx {
  static instances = [];
  static startState = 'running';
  static blocked = false;

  constructor(opts) {
    FakeCtx.instances.push(this);
    this.opts = opts;
    this.state = FakeCtx.blocked ? 'suspended' : FakeCtx.startState;
    this.currentTime = 0;
    this.sampleRate = 8000;
    this.nodes = [];
    this.starts = [];
    this.calls = [];
    this.destination = new FakeNode(this, 'destination');
    this.onstatechange = null;
  }

  createGain() {
    const n = new FakeNode(this, 'gain');
    n.gain = new FakeParam(1);
    return n;
  }

  createOscillator() {
    const n = new FakeSource(this, 'osc');
    n.frequency = new FakeParam(440);
    n.detune = new FakeParam(0);
    return n;
  }

  createBufferSource() {
    return new FakeSource(this, 'noise');
  }

  createBiquadFilter() {
    const n = new FakeNode(this, 'filter');
    n.frequency = new FakeParam(350);
    n.Q = new FakeParam(1);
    return n;
  }

  createDynamicsCompressor() {
    const n = new FakeNode(this, 'compressor');
    for (const k of ['threshold', 'knee', 'ratio', 'attack', 'release']) n[k] = new FakeParam(0);
    return n;
  }

  createBuffer(channels, length) {
    const data = new Float32Array(length);
    return { getChannelData: () => data };
  }

  set(state) {
    if (this.state === state) return;
    this.state = state;
    if (this.onstatechange) this.onstatechange();
  }

  resume() {
    this.calls.push('resume');
    if (!FakeCtx.blocked) this.set('running');
    return Promise.resolve();
  }

  suspend() {
    this.calls.push('suspend');
    this.set('suspended');
    return Promise.resolve();
  }

  close() {
    this.calls.push('close');
    this.set('closed');
    return Promise.resolve();
  }
}

describe('dvigatel', () => {
  let clock; // server soati (ms)
  let doc;
  let win;
  let nav;
  let events;
  let statuses;

  beforeEach(() => {
    mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
    FakeCtx.instances = [];
    FakeCtx.blocked = false;
    FakeCtx.startState = 'running';
    clock = 1764150000000;
    doc = new EventTarget();
    doc.hidden = false;
    win = new EventTarget();
    nav = { userActivation: { hasBeenActive: false, isActive: false } };
    events = [];
    statuses = [];
    win.addEventListener('octagon-audio', (e) => events.push(e.detail));
  });

  afterEach(() => {
    mock.timers.reset();
  });

  const make = (extra = {}) => createAudio({
    volume: 60, muted: false, now: () => clock, AudioContext: FakeCtx, win, doc, nav, onStatus: (s) => statuses.push(s), ...extra,
  });
  const ctx = () => FakeCtx.instances[FakeCtx.instances.length - 1];
  const of = (type) => events.filter((e) => e.type === type);
  function wait(ms) { // server soati, audio soati va taymerlar birga yuradi
    const c = ctx();
    const stepMs = 50;
    for (let left = ms; left > 0; left -= stepMs) {
      const d = Math.min(stepMs, left);
      clock += d;
      if (c && c.state === 'running') c.currentTime += d / 1000;
      mock.timers.tick(d);
    }
  }
  const flush = () => new Promise((r) => setImmediate(r));
  function click() {
    nav.userActivation.hasBeenActive = true;
    nav.userActivation.isActive = true;
    doc.dispatchEvent(new Event('click'));
  }
  const G = { pin: '482913', createdAt: 1764149990000, total: 5, sounds: RULES };
  const read = (index) => ({ ...G, phase: 'question_read', index, phaseStart: clock, phaseEnd: clock + 5000 });
  const active = (index, ms = 20000) => ({ ...G, phase: 'question_active', index, phaseStart: clock, phaseEnd: clock + ms });
  const result = (index, correctPct, answered = 5) => ({ ...G, phase: 'question_result', index, correctPct, answered });

  test("bosilmaguncha AudioContext yaratilmaydi; «Ovozni yoqish» kerakligi bildiriladi", () => {
    const a = make();
    a.sync({ ...G, phase: 'lobby', index: -1 });
    assert.equal(FakeCtx.instances.length, 0);
    assert.equal(a.status().blocked, false);             // lobbida ovoz kerak emas — tugma yo'q
    a.unlock();                                           // bosish bo'lmagan chaqiruv (masalan, kod ichidan) — hech narsa
    assert.equal(FakeCtx.instances.length, 0);
    a.sync(read(0));
    assert.equal(FakeCtx.instances.length, 0);
    assert.equal(a.status().blocked, true);
    assert.deepEqual(statuses.at(-1), { blocked: true, running: false, muted: false });
    a.dispose();
  });

  test('birinchi bosishda ochiladi va o\'sha savolning treki chalinadi', async () => {
    const a = make();
    a.sync(read(1));
    click();
    await flush();
    assert.equal(FakeCtx.instances.length, 1);
    assert.deepEqual(ctx().opts, { latencyHint: 'playback' });
    const start = of('music-start');
    assert.equal(start.length, 1);
    assert.equal(start[0].track, trackFor(gameSeed(G.pin, G.createdAt), 1));
    assert.equal(a.status().blocked, false);
    wait(1000);
    assert.ok(ctx().starts.length > 5, 'notalar rejalashtirilmoqda');
    a.dispose();
  });

  test("«Boshlash» bosilgach (lobbida) kontekst tayyor, savolda musiqa o'zi boshlanadi", () => {
    const a = make();
    a.sync({ ...G, phase: 'lobby', index: -1 });
    nav.userActivation.hasBeenActive = true;
    a.unlock();                                           // «Boshlash» tugmasi
    assert.equal(FakeCtx.instances.length, 1);
    a.sync({ ...G, phase: 'topic_intro', index: -1, phaseStart: clock, phaseEnd: clock + 5000 });
    assert.equal(of('music-start').length, 0);            // mavzu kirishida musiqa yo'q
    wait(5000);
    a.sync(read(0));
    assert.equal(of('music-start').length, 1);
    a.dispose();
  });

  test("o'qishdan savolga o'tishda musiqa uzilmaydi; vaqt tugaganda 300 ms da so'nadi", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(read(0));
    wait(5000);
    a.sync(active(0, 8000));
    assert.equal(of('music-start').length, 1);            // qayta boshlanmadi
    const endAt = ctx().currentTime + 8;
    wait(9000);
    const stop = of('music-stop');
    assert.equal(stop.length, 1);
    assert.equal(stop[0].reason, 'timer');
    assert.ok(Math.abs(stop[0].at - endAt) < 0.06, `${stop[0].at} ~ ${endAt}`);
    assert.ok(Math.abs(stop[0].end - stop[0].at - 0.3) < 1e-9);
    const bus = ctx().nodes.find((n) => n.kind === 'gain' && n.gain.events.some((e) => e[0] === 'lin' && e[2] === stop[0].end));
    assert.ok(bus, "musiqa yo'lagida 300 ms chiziqli so'nish bor");
    assert.equal(bus.gain.events.at(-1)[1], 0.0001);
    const during = ctx().starts.filter((s) => s.startAt >= stop[0].at - 1e-9 && s.startAt < stop[0].end);
    const after = ctx().starts.filter((s) => s.startAt >= stop[0].end - 1e-9);
    assert.ok(during.length > 0, "so'nish davomida musiqa chalinib turadi (keskin uzilmaydi)");
    assert.equal(after.length, 0, "so'nish tugagach nota yo'q");
    assert.equal(of('music-stop').length, 1);
    assert.ok(of('tense').length === 1 && Math.abs(of('tense')[0].at - (endAt - 5)) < 0.2, 'oxirgi 5 soniya');
    a.dispose();
  });

  test("hamma javob berdi: musiqa darhol so'nadi, natija ovozi so'nish tugagach boshlanadi (ustma-ust emas)", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(read(0));
    wait(5000);
    a.sync(active(0, 20000));
    wait(3000);
    a.sync(result(0, 80, 5));
    const stop = of('music-stop').at(-1);
    assert.equal(stop.reason, 'phase');
    const sfx = of('sfx').at(-1);
    assert.equal(sfx.name, 'cheer');
    assert.ok(sfx.at >= stop.end - 1e-9, `${sfx.at} >= ${stop.end}`);
    a.dispose();
  });

  for (const [pct, answered, name] of [[100, 4, 'cheer'], [45, 9, 'hmm'], [10, 10, 'oops'], [null, 0, 'soft']]) {
    test(`natija ovozi: ${pct} % (${answered} ta javob) -> ${name}`, () => {
      nav.userActivation.hasBeenActive = true;
      const a = make();
      a.sync(active(0, 10000));
      wait(1000);
      a.sync(result(0, pct, answered));
      assert.deepEqual(of('sfx').map((e) => e.name), [name]);
      a.dispose();
    });
  }

  test("hech kim javob bermadi va sozlamada «silent» — jimlik", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(active(0));
    a.sync({ ...result(0, null, 0), sounds: { ...RULES, nobody: 'silent' } });
    assert.equal(of('sfx').length, 0);
    a.dispose();
  });

  test("sahifa yangilansa: o'sha savol — o'sha trek; natija/reyting ekranida effekt qayta chalinmaydi", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(active(3));
    const first = of('music-start')[0].track;
    a.dispose();
    events.length = 0;
    const b = make();                                     // yangi sahifa, o'sha o'yin
    b.sync(active(3));
    assert.equal(of('music-start')[0].track, first);
    b.dispose();
    events.length = 0;
    const c = make();
    c.sync(result(3, 90, 5));                             // natija ekranida ochildi
    assert.equal(of('sfx').length, 0);
    c.sync({ ...G, phase: 'leaderboard', index: 3 });     // keyingi bosqich — jonli o'tish
    assert.deepEqual(of('sfx').map((e) => e.name), ['board']);
    c.dispose();
  });

  test("tez ketma-ket ikki bosqich: oldingi effekt o'chadi, yangisi undan keyin (ustma-ust emas)", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(active(0));
    a.sync(result(0, 70, 5));
    wait(100);
    a.sync({ ...G, phase: 'leaderboard', index: 0 });
    const cut = of('sfx-cut');
    assert.deepEqual(cut.map((e) => e.name), ['cheer']);
    const board = of('sfx').find((e) => e.name === 'board');
    assert.ok(board.at >= cut[0].end - 1e-9, `${board.at} >= ${cut[0].end}`);
    wait(100);
    a.sync(read(1));                                       // darhol keyingi savol
    assert.deepEqual(of('sfx-cut').map((e) => e.name), ['cheer', 'board']);
    const music = of('music-start').at(-1);
    assert.ok(music.at >= of('sfx-cut').at(-1).end - 1e-9);
    a.dispose();
  });

  test("ovozni o'chirish: musiqa to'xtaydi, yangi nota yo'q; yoqilganda o'sha trek qaytadan", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(active(2, 30000));
    const master = ctx().nodes.find((n) => n.kind === 'gain');
    assert.equal(master.gain.value, 0.36);                // 60 % -> 0.6² (o'rtacha)
    a.setMuted(true);
    assert.equal(of('music-stop').at(-1).reason, 'mute');
    assert.equal(master.gain.events.at(-1)[1], 0);
    wait(500);
    const before = ctx().starts.length;
    wait(2000);
    assert.equal(ctx().starts.length, before, "o'chirilganda nota rejalashtirilmaydi");
    assert.equal(a.status().blocked, false);             // o'chirilgan — «Ovozni yoqish» tugmasi chiqmaydi
    a.setMuted(false);
    assert.equal(of('music-start').length, 2);
    assert.equal(of('music-start')[1].track, of('music-start')[0].track);
    a.setVolume(30);
    assert.deepEqual(master.gain.events.at(-1).slice(0, 2), ['target', 0.09]);
    a.dispose();
  });

  test("o'chirilgan holatda ochilsa — AudioContext umuman yaratilmaydi", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make({ muted: true });
    a.sync(active(0));
    a.unlock();
    assert.equal(FakeCtx.instances.length, 0);
    a.dispose();
  });

  test("brauzer ruxsat bermasa: jim, «Ovozni yoqish» ko'rsatiladi; ruxsat berilgach musiqa boshlanadi", async () => {
    FakeCtx.blocked = true;
    const a = make();
    a.sync(read(0));
    click();
    await flush();
    assert.equal(ctx().state, 'suspended');
    assert.equal(a.status().blocked, true);
    assert.equal(of('music-start').length, 0);
    FakeCtx.blocked = false;
    click();                                              // «Ovozni yoqish»
    await flush();
    assert.equal(a.status().blocked, false);
    assert.equal(of('music-start').length, 1);
    a.dispose();
  });

  test("oyna yashirilsa — ovoz to'xtatiladi (tugmasiz), qaytganda davom etadi", async () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(active(1, 30000));
    a.sync(result(1, 90, 4));                              // effekt chalinmoqda
    a.sync(active(1, 30000));
    doc.hidden = true;
    doc.dispatchEvent(new Event('visibilitychange'));
    await flush();
    assert.equal(ctx().state, 'suspended');
    assert.equal(a.status().blocked, false);
    doc.hidden = false;
    doc.dispatchEvent(new Event('visibilitychange'));
    await flush();
    assert.equal(ctx().state, 'running');
    a.dispose();
  });

  test("fon oynada ochilgan sahifa ko'ringanda «Ovozni yoqish» chiqadi (A-1)", () => {
    doc.hidden = true;                                    // masalan, «Davom ettirish» yangi oynada ochildi
    const a = make();
    a.sync(read(0));
    assert.equal(a.status().blocked, false);             // yashirin oynada tugma kerak emas
    doc.hidden = false;
    doc.dispatchEvent(new Event('visibilitychange'));
    assert.equal(a.status().blocked, true);
    assert.deepEqual(statuses.at(-1), { blocked: true, running: false, muted: false });
    a.dispose();
  });

  test("o'yin muddatidan oldin tugadi: musiqa so'nadi, baraban; yakuniy natijalarda hammasi jim", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(active(1, 30000));
    wait(2000);
    a.sync({ ...G, phase: 'podium_intro', index: 1, phaseStart: clock, phaseEnd: clock + 3000 });
    assert.equal(of('music-stop').at(-1).reason, 'phase');
    assert.equal(of('sfx').at(-1).name, 'roll');
    assert.ok(Math.abs(of('sfx').at(-1).end - of('sfx').at(-1).at - 3) < 0.35);
    wait(300);
    a.sync({ ...G, phase: 'final_results', index: 1 });
    assert.equal(of('sfx-cut').at(-1).name, 'roll');
    assert.equal(a.status().blocked, false);
    a.dispose();
  });

  test('podium: 3-, 2-, 1-o\'rin fanfaralari; kech ochilgan qadam — jim', () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    const step = (phase, ms = 3500) => a.sync({ ...G, phase, index: 4, phaseStart: clock, phaseEnd: clock + ms });
    a.sync(result(4, 50, 3));                              // oxirgi savol natijasi (hmm), keyin «G'oliblar»
    wait(2000);
    step('podium_intro', 3000);
    wait(3000);
    step('reveal_3rd');
    wait(3500);
    step('reveal_2nd');
    wait(3500);
    step('reveal_1st', 6000);
    assert.deepEqual(of('sfx').map((e) => e.name), ['roll', 'fanfare3', 'fanfare2', 'fanfare1']); // natija — birinchi holat
    a.dispose();
    events.length = 0;
    const b = make();
    b.sync({ ...G, phase: 'reveal_2nd', index: 4, phaseStart: clock - 1000, phaseEnd: clock + 2500 }); // sahifa yangilandi
    b.sync({ ...G, phase: 'reveal_1st', index: 4, phaseStart: clock - 3000, phaseEnd: clock + 3000 }); // qayta ulanish kech
    assert.equal(of('sfx').length, 0);
    b.dispose();
  });

  test("sahifadan chiqish: kontekst yopiladi, taymerlar va tinglovchilar qolmaydi", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    a.sync(active(0, 30000));
    wait(500);
    a.dispose();
    const c = ctx();
    assert.ok(c.calls.includes('close'));
    const n = c.starts.length;
    wait(3000);
    assert.equal(c.starts.length, n, "yopilgandan keyin nota yo'q");
    doc.hidden = true;
    doc.dispatchEvent(new Event('visibilitychange'));
    assert.ok(!c.calls.includes('suspend'), 'visibilitychange tinglovchisi olib tashlangan');
    a.sync(read(1));
    a.unlock();
    assert.equal(FakeCtx.instances.length, 1, "dispose'dan keyin yangi kontekst yo'q");
    a.dispose();                                          // ikki marta — xato yo'q
  });

  test("har bir effekt mavjud va xato bermaydi (sozlash sahifasidagi sinov tugmasi bilan)", () => {
    nav.userActivation.hasBeenActive = true;
    const a = make();
    for (const name of ['cheer', 'hmm', 'oops', 'soft', 'board', 'roll', 'fanfare3', 'fanfare2', 'fanfare1']) {
      a.preview(name);
      assert.equal(of('sfx').at(-1).name, name);
      wait(100);
    }
    a.dispose();
  });
});
