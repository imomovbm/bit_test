// Octagon — o'qituvchi ekrani (proyektor) ovozi: savol paytida o'ynoqi musiqa, natija, reyting va g'oliblar ovozlari.
//
// Hammasi shu faylda Web Audio API bilan sintez qilinadi (chiptune uslubi): audio fayllar yo'q, kuylar va ovozlar shu
// kod bilan yaratilgan — original, litsenziya yoki mualliflikni ko'rsatish talab qilinmaydi (docs/audio-credits.md).
// Modulni faqat o'qituvchining Octagon sahifasi kerak bo'lganda yuklaydi (views/octagon.js: import()); o'quvchi sahifasi
// (/play) uni hech qachon yuklamaydi — telefonlar jim. Ovoz — faqat ko'rinish: o'yin holati va qarorlari serverda.
//
// Brauzer qoidasi: AudioContext faqat foydalanuvchi bosgandan keyin yaratiladi yoki davom ettiriladi («Boshlash»,
// «Ovozni yoqish», ovoz tugmasi, ekranda istalgan bosish). Ruxsat bo'lmasa — jim, ekranda «Ovozni yoqish» tugmasi.
// Sahifa yashirilsa ovoz to'xtaydi, qaytganda davom etadi; sahifadan chiqilganda hammasi yopiladi (dispose).

// ------------------------------------------------------------------ sozlamalar
// Natija ovozi chegaralari (foiz → ovoz) — serverda: app/config.py (OCTAGON_RESULT_SOUNDS), ekranga g.sounds bilan keladi.
export const AUDIO = Object.freeze({
  tracks: 5,          // savol musiqalari soni (TRACKS)
  fadeMs: 300,        // musiqa to'xtashi: vaqt tugadi yoki hamma javob berdi
  cutMs: 80,          // bosqich almashsa, oldingi effekt shunchalik tez o'chadi — ovozlar ustma-ust chalinmaydi
  tenseMs: 5000,      // savolning oxirgi 5 soniyasi: temp biroz tezlashadi va har zarbda yengil «tik»
  tenseTempo: 1.06,
  freshMs: 2500,      // vaqtli bosqich shundan oldin boshlangan bo'lsa (kech ulanish) — uning effekti chalinmaydi
  lookahead: 0.3,     // notalar shuncha soniya oldindan rejalashtiriladi (audio soati bo'yicha — uzilishsiz)
  tickMs: 100,        // rejalashtiruvchi qadami (asosiy oqimda juda kam ish)
  musicLevel: 0.55,   // musiqa effektlardan pastroq
  sfxLevel: 0.9,
  rollMax: 4,         // «Va g'oliblar…» baraban sadosining eng uzog'i (soniya)
});

// Bosqich → effekt (natija ovozi — alohida: pickResultSound). Nomlar — SFX dagi funksiyalar.
const STEP_SFX = { leaderboard: 'board', podium_intro: 'roll', reveal_3rd: 'fanfare3', reveal_2nd: 'fanfare2', reveal_1st: 'fanfare1' };
const MUSIC_PHASES = ['question_read', 'question_active'];  // musiqa savol ko'rinishi bilan boshlanadi, javob vaqti tugaguncha
const QUIET_PHASES = ['lobby', 'final_results'];              // o'yin boshlanmagan yoki tugagan — hech narsa chalinmaydi

// ------------------------------------------------------------------ 5 ta trek
// Kuy: har belgi — 16-lik nota; raqam/harf — shkala pog'onasi (0 — tonika, 7 — bir oktava yuqori, a=10 …), '.' — pauza,
// '-' — oldingi notani cho'zish. 4 takt (64 qadam) aylanib takrorlanadi. Bas: r — akkord asosi, f — kvinta, o — oktava.
// Akkordlar — har takt uchun shkala pog'onasi (uchtovush shkaladan olinadi). Hammasi major/miksolidiy — quvnoq, yengil.
const MAJOR = [0, 2, 4, 5, 7, 9, 11];
const MIXOLYDIAN = [0, 2, 4, 5, 7, 9, 10];
const DEGREE = '0123456789abcde';
const LOOP = 64;

export const TRACKS = Object.freeze([
  { // 1. «Sakrash» — Do major, I–V–vi–IV; kvadrat to'lqinli chertma kuy, to'rtta zarbli baraban
    name: 'hopscotch', bpm: 126, root: 60, scale: MAJOR, swing: 0, chords: [0, 4, 5, 3],
    lead: { wave: 'square', gain: 0.05, gate: 0.8 },
    bass: { wave: 'triangle', gain: 0.2, line: 'r...r.o.r...f.o.' },
    drums: { kick: 'x...x...x...x...', snare: '....x.......x...', hat: '..x...x...x...x.', snareVoice: 'snare', hatVoice: 'hat' },
    melody: '7.4.2.4.7.9.7...' + 'b.8.6.8.b.c.b...' + '9.7.5.7.9.c.9.7.' + 'a.9.7.5.4-------',
  },
  { // 2. «Konfet» — Fa major, I–vi–ii–V; svingli, nay ovoziga o'xshash uchburchak to'lqin, shaqildoq
    name: 'lollipop', bpm: 108, root: 65, scale: MAJOR, swing: 0.18, chords: [0, 5, 1, 4],
    lead: { wave: 'triangle', gain: 0.12, gate: 0.9, sustain: 0.6 },
    bass: { wave: 'sine', gain: 0.24, line: 'r.....f.r.....f.' },
    drums: { kick: 'x.......x.x.....', snare: '....x.......x...', hat: 'x.x.x.x.x.x.x.x.', snareVoice: 'rim', hatVoice: 'shaker' },
    melody: '4-2.4.7---4.2...' + '5-7.5.2---5.7...' + '8-5.3.1---3.5...' + '6.4.6.8.b-------',
  },
  { // 3. «Zuv» — Sol miksolidiy, I–♭VII–IV–I; tez, 8-bit bas, 16-lik arpedjio
    name: 'zoom', bpm: 138, root: 55, scale: MIXOLYDIAN, swing: 0, chords: [0, 6, 3, 0],
    lead: { wave: 'square', gain: 0.045, gate: 0.55, octave: 1 },
    bass: { wave: 'square', gain: 0.07, line: 'r.r.o.r.r.r.o.r.' },
    arp: { wave: 'triangle', gain: 0.03, notes: [0, 2, 4, 7] },
    drums: { kick: 'x...x.....x.x...', snare: '....x.......x...', hat: '.x.x.x.x.x.x.x.x', snareVoice: 'snare', hatVoice: 'hat' },
    melody: '7.7.4.2.4.7.9.7.' + '6.6.3.1.3.6.8.6.' + '3.5.7.5.3.5.7.a.' + '9.7.4.7.9---7...',
  },
  { // 4. «Marimba» — Re major, I–IV–vi–V; yumshoq marimba, sekinroq, shaqildoq
    name: 'marimba', bpm: 100, root: 62, scale: MAJOR, swing: 0, chords: [0, 3, 5, 4],
    lead: { wave: 'marimba', gain: 0.13, gate: 1 },
    bass: { wave: 'sine', gain: 0.22, line: 'r.....r.f.......' },
    drums: { kick: 'x.........x.....', snare: '........x.......', hat: 'x.xxx.xxx.xxx.xx', snareVoice: 'rim', hatVoice: 'shaker' },
    melody: '79b.9.7.4.2.4...' + 'aca.7.5.3.5.7...' + '579.c.9.7.5.7...' + '864.6.8.b-------',
  },
  { // 5. «Pufakchalar» — Si♭ major, I–iii–IV–V; chertma uchburchak + oktava, 8-bit bas, chapak
    name: 'bubbles', bpm: 132, root: 58, scale: MAJOR, swing: 0, chords: [0, 2, 3, 4],
    lead: { wave: 'pluck', gain: 0.11, gate: 0.85 },
    bass: { wave: 'square', gain: 0.06, line: 'r.o.r.o.r.o.f.o.' },
    drums: { kick: 'x..x..x...x..x..', snare: '....x.......x..x', hat: '..x...x...x...x.', snareVoice: 'clap', hatVoice: 'hat' },
    melody: '7.9.b.9.7---4.2.' + '9.b.d.b.9---6.4.' + 'a.c.e.c.a---7.5.' + 'b.d.b.8.b-------',
  },
]);

// ------------------------------------------------------------------ sof qoidalar
/** O'yin urug'i: PIN va o'yin yaratilgan vaqt — sahifa yangilansa ham o'zgarmaydi (32-bit FNV-1a). */
export function gameSeed(pin, createdAt) {
  let h = 0x811c9dc5;
  const text = `${pin}:${createdAt}`;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

function random(seed) { // mulberry32: kichik, tez, urug'li
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Savollar bo'yicha treklar tartibi: har `count` ta savolda har bir trek bir martadan, aralashtirilgan (urug' — o'yin);
 * ketma-ket ikki savolda bir xil trek hech qachon yo'q (bloklar chegarasida ham). */
export function trackOrder(seed, length, count = AUDIO.tracks) {
  const next = random(seed);
  const out = [];
  while (out.length < length) {
    const block = Array.from({ length: count }, (_, i) => i);
    for (let i = count - 1; i > 0; i--) {
      const j = Math.floor(next() * (i + 1));
      [block[i], block[j]] = [block[j], block[i]];
    }
    if (out.length && count > 1 && block[0] === out[out.length - 1]) { // oldingi blokning oxirgisi bilan bir xil bo'lmasin
      const j = 1 + Math.floor(next() * (count - 1));
      [block[0], block[j]] = [block[j], block[0]];
    }
    out.push(...block);
  }
  return out.slice(0, Math.max(0, length));
}

/** Shu savolning treki: o'yin ichida savol raqami bo'yicha aniq — sahifa yangilansa ham trek almashmaydi. */
export function trackFor(seed, index, count = AUDIO.tracks) {
  if (!Number.isInteger(index) || index < 0) return 0;
  return trackOrder(seed, index + 1, count)[index];
}

/** Natija ovozi: server hisoblagan foiz (correctPct — javob berganlar orasida to'g'ri javoblar) va jadval (bands:
 * [[foiz ≥, ovoz], …] yuqoridan pastga; nobody: 'soft' | 'silent'). null — hech narsa chalinmaydi. */
export function pickResultSound(result, rules) {
  if (!result || !rules || !Array.isArray(rules.bands)) return null;
  const pct = result.correctPct;
  if (!result.answered || typeof pct !== 'number') return rules.nobody === 'silent' ? null : 'soft';
  for (const [min, name] of rules.bands) {
    if (pct >= min) return name;
  }
  return null;
}

/** Bosqich uchun ovoz rejasi (sof): qaysi musiqa (yoki jimlik) va — bosqich shu sahifada hozirgina almashgan bo'lsa —
 * qaysi effekt. prevKey — oldingi holat kaliti (null: sahifa endi ochildi — effekt yo'q, faqat musiqa davom etadi). */
export function planFor(g, nowMs, prevKey) {
  const key = `${g.phase}:${g.index}`;
  const plan = { key, live: !QUIET_PHASES.includes(g.phase), music: null, sfx: null, until: null };
  if (MUSIC_PHASES.includes(g.phase) && Number.isInteger(g.index) && g.index >= 0) {
    const timed = g.phase === 'question_active' && typeof g.phaseEnd === 'number';
    plan.music = {
      index: g.index,
      track: trackFor(gameSeed(g.pin, g.createdAt), g.index),
      stopAt: timed ? g.phaseEnd : null,                    // javob vaqti tugashi (server soati, ms)
      tenseAt: timed ? g.phaseEnd - AUDIO.tenseMs : null,   // oxirgi 5 soniya
    };
  }
  const moved = prevKey != null && prevKey !== key;
  const stale = typeof g.phaseStart === 'number' && nowMs - g.phaseStart > AUDIO.freshMs;
  if (moved && !stale) {
    plan.sfx = g.phase === 'question_result' ? pickResultSound(g, g.sounds) : STEP_SFX[g.phase] || null;
    if (plan.sfx && typeof g.phaseEnd === 'number') plan.until = g.phaseEnd; // baraban sadosi — bosqich oxirigacha
  }
  return plan;
}

const hz = (midi) => 440 * 2 ** ((midi - 69) / 12);
const semitones = (tr, degree) => tr.scale[((degree % 7) + 7) % 7] + 12 * Math.floor(degree / 7);

/** Bir 16-lik qadam uzunligi (soniya): temp, sving (juft qadam uzunroq, toq — qisqaroq) va oxirgi soniyalar tezlashuvi. */
export function stepLength(tr, step, tense) {
  const base = 60 / tr.bpm / 4 / (tense ? AUDIO.tenseTempo : 1);
  return tr.swing ? base * (step % 2 === 0 ? 1 + tr.swing : 1 - tr.swing) : base;
}

// ------------------------------------------------------------------ dvigatel
/**
 * Ovoz dvigateli (faqat brauzerda). opts: { volume 0–100, muted, now() — server soati (ms), onStatus({blocked, running,
 * muted}) }. Sinov uchun: AudioContext, win, doc, nav almashtirilishi mumkin.
 * Har bosqich almashganda sync(holat) chaqiriladi; qolganini dvigatel o'zi hal qiladi.
 */
export function createAudio(opts = {}) {
  const win = opts.win !== undefined ? opts.win : (typeof window !== 'undefined' ? window : null);
  const doc = opts.doc !== undefined ? opts.doc : (typeof document !== 'undefined' ? document : null);
  const nav = opts.nav !== undefined ? opts.nav : (typeof navigator !== 'undefined' ? navigator : null);
  const Ctx = opts.AudioContext || (win && (win.AudioContext || win.webkitAudioContext)) || null;
  const now = opts.now || (() => Date.now());
  const onStatus = opts.onStatus || (() => {});
  let volume = clampVolume(opts.volume);
  let muted = !!opts.muted;
  let ctx = null;
  let master = null;
  let noiseBuffer = null;
  let music = null;       // hozirgi trek: { tr, track, index, bus, step, next, stopAt, tenseAt, tense, fading }
  let effect = null;      // hozirgi effekt (bir vaqtda faqat bittasi): { name, bus, at, end }
  let quietAt = 0;        // shu paytgacha oldingi ovoz so'nib bo'ladi (audio soati) — yangisi undan keyin boshlanadi
  let plan = null;        // so'nggi bosqich rejasi (ovoz keyinroq ochilsa — shundan davom etiladi)
  let lastKey = null;
  let timer = 0;
  let listening = false;
  let shown = { blocked: false, running: false };
  let disposed = false;
  const timeouts = new Set();

  // ---- yordamchilar
  function clampVolume(v) {
    const n = Number(v);
    return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 60;
  }
  const level = () => (volume / 100) ** 2;        // eshitilishiga yaqin: slayderning o'rtasi — haqiqatan ham o'rtacha
  const running = () => !!ctx && ctx.state === 'running';
  const hidden = () => !!doc && doc.hidden === true;
  // Sahifa foydalanuvchi tomonidan bosilganmi (sticky activation): bo'lmasa AudioContext yaratish faqat ogohlantirish
  // chiqaradi. canStart — bosish ichida (API bo'lmasa — ruxsat), wasActivated — o'zi boshlash uchun (faqat aniq bo'lsa).
  const canStart = () => !nav || !nav.userActivation || nav.userActivation.hasBeenActive;
  const wasActivated = () => !!(nav && nav.userActivation && nav.userActivation.hasBeenActive);

  function report(type, detail = {}) { // kuzatish uchun (E2E, nosozliklarni tuzatish): window'da «octagon-audio» hodisasi
    if (!win || typeof win.dispatchEvent !== 'function' || typeof CustomEvent !== 'function') return;
    try {
      win.dispatchEvent(new CustomEvent('octagon-audio', { detail: { type, t: ctx ? ctx.currentTime : null, ...detail } }));
    } catch {
      /* kuzatuv ixtiyoriy */
    }
  }

  function later(fn, ms) {
    const id = setTimeout(() => {
      timeouts.delete(id);
      fn();
    }, Math.max(0, ms));
    timeouts.add(id);
  }

  /** Tugagan ovoz yo'lagini ulanishdan uzish (tugunlar to'planib qolmasin). */
  function retire(node, at) {
    later(() => {
      try {
        node.disconnect();
      } catch {
        /* allaqachon uzilgan */
      }
    }, (at - (ctx ? ctx.currentTime : 0)) * 1000 + 80);
  }

  function noise() {
    if (!noiseBuffer) {
      noiseBuffer = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
      const data = noiseBuffer.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    }
    return noiseBuffer;
  }

  // ---- tovush manbalari (har nota — o'z tugunlari, start/stop bilan; tugagach brauzer o'zi tozalaydi)
  function envelope(t, dur, o) {
    const g = ctx.createGain();
    const peak = o.gain || 0.1;
    const attack = o.attack || 0.004;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + attack);
    if (o.sustain) { // cho'ziladigan nota: tez pasayish -> tutish -> qo'yib yuborish
      const hold = Math.max(attack + 0.08, dur);
      g.gain.exponentialRampToValueAtTime(peak * o.sustain, t + attack + 0.08);
      g.gain.setValueAtTime(peak * o.sustain, t + hold);
      g.gain.exponentialRampToValueAtTime(0.0001, t + hold + (o.release || 0.08));
    } else { // chertma: darhol so'nadi
      g.gain.exponentialRampToValueAtTime(0.0001, t + Math.max(attack + 0.01, dur));
    }
    return g;
  }

  function tone(t, freq, dur, o, dest) {
    const n = ctx.createOscillator();
    n.type = o.wave || 'square';
    n.frequency.setValueAtTime(freq, t);
    if (o.slideTo) n.frequency.exponentialRampToValueAtTime(o.slideTo, t + dur);
    if (o.detune) n.detune.setValueAtTime(o.detune, t);
    n.connect(envelope(t, dur, o)).connect(dest);
    n.start(t);
    n.stop(t + dur + (o.sustain ? (o.release || 0.08) : 0) + 0.05);
    return n;
  }

  function hiss(t, dur, o, dest) {
    const src = ctx.createBufferSource();
    src.buffer = noise();
    src.loop = true;
    const f = ctx.createBiquadFilter();
    f.type = o.filter || 'highpass';
    f.frequency.setValueAtTime(o.freq || 6000, t);
    if (o.freqTo) f.frequency.exponentialRampToValueAtTime(o.freqTo, t + dur);
    f.Q.value = o.q || 0.7;
    src.connect(f).connect(envelope(t, dur, o)).connect(dest);
    src.start(t, Math.random());
    src.stop(t + dur + 0.05);
  }

  const DRUM = {
    kick(t, d) {
      const n = ctx.createOscillator();
      n.type = 'sine';
      n.frequency.setValueAtTime(150, t);
      n.frequency.exponentialRampToValueAtTime(48, t + 0.12);
      n.connect(envelope(t, 0.16, { gain: 0.5, attack: 0.002 })).connect(d);
      n.start(t);
      n.stop(t + 0.2);
    },
    snare(t, d) {
      hiss(t, 0.12, { filter: 'bandpass', freq: 1900, q: 0.9, gain: 0.15, attack: 0.002 }, d);
      tone(t, 185, 0.06, { wave: 'triangle', gain: 0.07, attack: 0.002 }, d);
    },
    rim(t, d) {
      tone(t, 820, 0.03, { wave: 'triangle', gain: 0.07, attack: 0.001 }, d);
    },
    clap(t, d) {
      for (const k of [0, 0.011, 0.023]) hiss(t + k, 0.06, { filter: 'bandpass', freq: 1400, q: 1.2, gain: 0.11, attack: 0.001 }, d);
    },
    hat(t, d, x = 1) {
      hiss(t, 0.035, { filter: 'highpass', freq: 7500, gain: 0.045 * x, attack: 0.001 }, d);
    },
    shaker(t, d, x = 1) {
      hiss(t, 0.05, { filter: 'bandpass', freq: 6000, q: 1.1, gain: 0.04 * x, attack: 0.004 }, d);
    },
    tick(t, d) { // oxirgi soniyalar: yog'och «tik»
      tone(t, 1760, 0.03, { wave: 'sine', gain: 0.08, attack: 0.001 }, d);
    },
  };

  function leadNote(tr, t, freq, dur, d) {
    const l = tr.lead;
    if (l.wave === 'marimba') { // asosiy ton + 4-garmonika (yog'och zarbi)
      tone(t, freq, Math.max(dur, 0.35), { wave: 'sine', gain: l.gain }, d);
      tone(t, freq * 4, 0.08, { wave: 'sine', gain: l.gain * 0.22 }, d);
    } else if (l.wave === 'pluck') { // uchburchak + yuqori oktava (chertma)
      tone(t, freq, dur, { wave: 'triangle', gain: l.gain }, d);
      tone(t, freq * 2, dur * 0.5, { wave: 'square', gain: l.gain * 0.16 }, d);
    } else {
      tone(t, freq, dur, { wave: l.wave, gain: l.gain, sustain: l.sustain }, d);
    }
  }

  /** Trekning bitta 16-lik qadami: baraban, bas, arpedjio, kuy. */
  function playStep(m, t, tense) {
    const { tr, bus } = m;
    const s = m.step % 16;
    const chord = tr.chords[Math.floor(m.step / 16) % tr.chords.length];
    const len = stepLength(tr, m.step, tense);
    const dr = tr.drums;
    if (dr.kick[s] === 'x') DRUM.kick(t, bus);
    if (dr.snare[s] === 'x') DRUM[dr.snareVoice](t, bus);
    if (dr.hat[s] === 'x' || (tense && s % 2 === 1)) DRUM[dr.hatVoice](t, bus, tense ? 1.3 : 1);
    if (tense && s % 4 === 0) DRUM.tick(t, bus);
    const b = tr.bass.line[s];
    if (b !== '.') {
      const deg = chord + (b === 'f' ? 4 : b === 'o' ? 7 : 0);
      tone(t, hz(tr.root - 12 + semitones(tr, deg)), len * 1.7, { wave: tr.bass.wave, gain: tr.bass.gain }, bus);
    }
    if (tr.arp) {
      const deg = chord + tr.arp.notes[s % tr.arp.notes.length];
      tone(t, hz(tr.root + 12 + semitones(tr, deg)), len * 0.6, { wave: tr.arp.wave, gain: tr.arp.gain }, bus);
    }
    const ch = tr.melody[m.step];
    const deg = DEGREE.indexOf(ch);
    if (deg >= 0) {
      let steps = 1;
      while (tr.melody[(m.step + steps) % LOOP] === '-' && steps < 16) steps++;
      leadNote(tr, t, hz(tr.root + 12 * (tr.lead.octave || 0) + semitones(tr, deg)), len * steps * tr.lead.gate, bus);
    }
  }

  // ---- effektlar: (boshlanish, yo'lak, reja) -> davomiyligi (soniya)
  function hum(t, freq, dur, d) { // «hmm»: past, yumshoq g'o'ng'illash (filtrlangan arra to'lqini, yengil vibrato)
    const n = ctx.createOscillator();
    n.type = 'sawtooth';
    n.frequency.setValueAtTime(freq, t);
    const lfo = ctx.createOscillator();
    lfo.frequency.value = 5.5;
    const depth = ctx.createGain();
    depth.gain.value = 9;
    lfo.connect(depth).connect(n.detune);
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 900;
    lp.Q.value = 3;
    n.connect(lp).connect(envelope(t, dur, { gain: 0.1, attack: 0.05, sustain: 0.8, release: 0.12 })).connect(d);
    n.start(t);
    lfo.start(t);
    n.stop(t + dur + 0.25);
    lfo.stop(t + dur + 0.25);
  }

  function boing(t, d) { // o'ynoqi prujina
    const n = ctx.createOscillator();
    n.type = 'triangle';
    const f = n.frequency;
    f.setValueAtTime(330, t);
    f.exponentialRampToValueAtTime(165, t + 0.1);
    f.exponentialRampToValueAtTime(262, t + 0.18);
    f.exponentialRampToValueAtTime(196, t + 0.3);
    f.exponentialRampToValueAtTime(220, t + 0.42);
    n.connect(envelope(t, 0.45, { gain: 0.16, attack: 0.005 })).connect(d);
    n.start(t);
    n.stop(t + 0.5);
  }

  function brass(t, midi, dur, d, x = 1) { // fanfara: ikki arra to'lqini (sal farqli), ochilib-yopiladigan filtr
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.Q.value = 1.2;
    lp.frequency.setValueAtTime(700, t);
    lp.frequency.exponentialRampToValueAtTime(2600, t + 0.05);
    lp.frequency.exponentialRampToValueAtTime(1500, t + 0.25);
    lp.connect(envelope(t, dur, { gain: 0.07 * x, attack: 0.02, sustain: 0.75, release: 0.15 })).connect(d);
    for (const cents of [-7, 7]) {
      const n = ctx.createOscillator();
      n.type = 'sawtooth';
      n.frequency.setValueAtTime(hz(midi), t);
      n.detune.setValueAtTime(cents, t);
      n.connect(lp);
      n.start(t);
      n.stop(t + dur + 0.3);
    }
  }

  const sparkle = (t, notes, gap, d) => notes.forEach((m, i) => tone(t + i * gap, hz(m), 0.09, { wave: 'sine', gain: 0.035 }, d));

  const SFX = {
    cheer(t, d) { // ≥ 60 %: tez ko'tariluvchi arpedjio + yorqin major akkord + uchqunlar
      [72, 76, 79, 84].forEach((m, i) => tone(t + i * 0.075, hz(m), 0.1, { wave: 'square', gain: 0.06 }, d));
      for (const m of [72, 76, 79, 84]) tone(t + 0.32, hz(m), 0.5, { wave: 'triangle', gain: 0.09, sustain: 0.55, release: 0.35 }, d);
      sparkle(t + 0.36, [96, 100, 103, 108], 0.08, d);
      return 1.3;
    },
    hmm(t, d) { // 30–59 %: «hmm?» — ikki yumshoq nota, savol ohangida ko'tariladi
      hum(t, hz(57), 0.28, d);
      hum(t + 0.34, hz(60), 0.42, d);
      return 0.95;
    },
    oops(t, d) { // < 30 %: «voy» — hushtak pastga sirpanadi va prujina (kulgili, masxara emas)
      tone(t, 1046.5, 0.36, { wave: 'sine', gain: 0.1, slideTo: 330 }, d);
      boing(t + 0.4, d);
      return 0.95;
    },
    soft(t, d) { // hech kim javob bermadi: bitta yumshoq qo'ng'iroqcha
      tone(t, hz(81), 1.2, { wave: 'sine', gain: 0.07, attack: 0.003 }, d);
      tone(t, hz(81) * 2.76, 0.5, { wave: 'sine', gain: 0.02, attack: 0.002 }, d);
      return 1.3;
    },
    board(t, d) { // reyting: «shuv» + ikki «pop»
      hiss(t, 0.3, { filter: 'bandpass', freq: 500, freqTo: 5000, q: 1.4, gain: 0.08, attack: 0.12 }, d);
      tone(t + 0.24, hz(79), 0.07, { wave: 'square', gain: 0.06 }, d);
      tone(t + 0.32, hz(86), 0.14, { wave: 'square', gain: 0.06 }, d);
      return 0.6;
    },
    roll(t, d, p) { // «Va g'oliblar…»: kuchayib boruvchi baraban sadosi — bosqich oxirigacha
      const until = p && typeof p.until === 'number' ? (p.until - now()) / 1000 : 2.5;
      const len = Math.max(0.6, Math.min(AUDIO.rollMax, until));
      const n = Math.round(len / 0.055);
      for (let i = 0; i < n; i++) {
        const k = i / n;
        hiss(t + i * 0.055, 0.05, { filter: 'bandpass', freq: 2200, q: 0.8, gain: 0.03 + 0.14 * k * k, attack: 0.002 }, d);
      }
      return len;
    },
    fanfare3(t, d) { // 3-o'rin: «ta-daa»
      brass(t, 67, 0.12, d);
      brass(t + 0.15, 72, 0.55, d);
      return 0.9;
    },
    fanfare2(t, d) { // 2-o'rin: «ta-ta-daa»
      brass(t, 67, 0.1, d);
      brass(t + 0.13, 72, 0.1, d);
      brass(t + 0.26, 76, 0.65, d);
      return 1.1;
    },
    fanfare1(t, d) { // 1-o'rin: katta fanfara, akkord, tarelka va uchqunlar
      [67, 72, 76].forEach((m, i) => brass(t + i * 0.12, m, 0.1, d));
      brass(t + 0.36, 79, 0.35, d);
      for (const m of [72, 76, 79, 84]) brass(t + 0.78, m, 0.9, d, 0.6);
      hiss(t + 0.78, 1.4, { filter: 'highpass', freq: 5000, gain: 0.09, attack: 0.002 }, d);
      sparkle(t + 0.9, [96, 100, 103, 108, 103, 108], 0.07, d);
      return 2.3;
    },
  };

  // ---- musiqa
  function audioAt(ms) { // server vaqti (ms) -> audio soati (s)
    return ctx.currentTime + (ms - now()) / 1000;
  }

  function retime(m) {
    music.stopAt = m.stopAt == null ? null : audioAt(m.stopAt);
    music.tenseAt = m.tenseAt == null ? null : audioAt(m.tenseAt);
  }

  function startMusic(m) {
    const after = endMusic('switch');
    const bus = ctx.createGain();
    bus.gain.value = AUDIO.musicLevel;
    bus.connect(master);
    const at = Math.max(after, quietAt, ctx.currentTime + 0.05);
    music = { tr: TRACKS[m.track] || TRACKS[0], track: m.track, index: m.index, bus, step: 0, next: at, stopAt: null, tenseAt: null, tense: false, fading: 0 };
    retime(m);
    report('music-start', { track: m.track, name: music.tr.name, index: m.index, at });
    pump();
    if (!timer) timer = setInterval(pump, AUDIO.tickMs);
  }

  /** Rejalashtiruvchi: audio soati bo'yicha oldinga qarab notalar qo'yiladi. Vaqt tugasa — musiqa 300 ms davomida
   * chalinishda davom etib so'nadi (haqiqiy so'nish), undan keyin nota qo'yilmaydi. */
  function pump() {
    const m = music;
    if (!m || !running()) return;
    const horizon = ctx.currentTime + AUDIO.lookahead;
    while (m.next < horizon) {
      if (m.fading) {
        if (m.next >= m.fading) { // so'nish tugadi
          stopTimer();
          return;
        }
      } else if (m.stopAt != null && m.next >= m.stopAt) {
        fadeMusic(m, Math.max(m.stopAt, ctx.currentTime), 'timer');
        continue;
      }
      const tense = m.tenseAt != null && m.next >= m.tenseAt;
      if (tense && !m.tense) {
        m.tense = true;
        report('tense', { index: m.index, at: m.next });
      }
      playStep(m, m.next, tense);
      m.next += stepLength(m.tr, m.step, tense);
      m.step = (m.step + 1) % LOOP;
    }
  }

  function stopTimer() {
    if (timer) clearInterval(timer);
    timer = 0;
  }

  function fadeMusic(m, at, reason) {
    if (m.fading) return m.fading;
    const end = at + AUDIO.fadeMs / 1000;
    const g = m.bus.gain;
    g.cancelScheduledValues(at);
    g.setValueAtTime(AUDIO.musicLevel, at);
    g.linearRampToValueAtTime(0.0001, end);
    m.fading = end;
    quietAt = Math.max(quietAt, end);
    retire(m.bus, end);
    report('music-stop', { reason, index: m.index, at, end });
    return end;
  }

  /** Musiqani to'xtatish (so'nib): qaytaradi — qachon butunlay jim bo'ladi (audio soati). */
  function endMusic(reason) {
    const m = music;
    music = null;
    stopTimer();
    if (!m || !ctx) return ctx ? ctx.currentTime : 0;
    return fadeMusic(m, ctx.currentTime, reason);
  }

  // ---- effektlar
  function playEffect(name, p) {
    const fn = SFX[name];
    if (!fn || !running() || muted) return;
    const at = Math.max(ctx.currentTime + 0.02, quietAt); // musiqa yoki oldingi effekt so'nib bo'lgach
    const bus = ctx.createGain();
    bus.gain.value = AUDIO.sfxLevel;
    bus.connect(master);
    const len = fn(at, bus, p);
    effect = { name, bus, at, end: at + len };
    retire(bus, at + len + 0.4);
    report('sfx', { name, at, end: at + len });
  }

  function cutEffect() {
    const e = effect;
    effect = null;
    if (!e || !ctx || e.end <= ctx.currentTime) return;
    const t = ctx.currentTime;
    const end = t + AUDIO.cutMs / 1000;
    e.bus.gain.cancelScheduledValues(t);
    e.bus.gain.setValueAtTime(AUDIO.sfxLevel, t);
    e.bus.gain.linearRampToValueAtTime(0.0001, end);
    quietAt = Math.max(quietAt, end);
    retire(e.bus, end);
    report('sfx-cut', { name: e.name, at: t, end });
  }

  // ---- reja -> ovoz
  function apply(p, fresh) {
    if (fresh) cutEffect(); // bosqich almashdi: oldingi effekt tez o'chadi
    const m = p.music && !(p.music.stopAt != null && p.music.stopAt <= now()) ? p.music : null;
    if (!m) endMusic(fresh ? 'phase' : 'sync');
    if (!muted && !ctx && p.live && wasActivated()) build(); // sahifa allaqachon bosilgan bo'lsa — ruxsat bor
    if (running() && !muted) {
      if (m && (!music || music.index !== m.index)) startMusic(m);
      else if (m) retime(m);
      if (fresh && p.sfx && !hidden()) playEffect(p.sfx, p);
    }
    status();
  }

  function resync() {
    if (plan && !disposed) apply(plan, false);
    else status();
  }

  function build() {
    if (!Ctx || disposed) return;
    try {
      ctx = new Ctx({ latencyHint: 'playback' }); // katta bufer — sekin noutbukda ham uzilishsiz
    } catch {
      try {
        ctx = new Ctx();
      } catch {
        ctx = null;
      }
    }
    if (!ctx) return;
    master = ctx.createGain();
    master.gain.value = muted ? 0 : level();
    const comp = ctx.createDynamicsCompressor(); // bir nechta ovoz ustma-ust tushsa ham xirillamasin
    comp.threshold.value = -14;
    comp.knee.value = 8;
    comp.ratio.value = 4;
    comp.attack.value = 0.004;
    comp.release.value = 0.2;
    master.connect(comp).connect(ctx.destination);
    quietAt = 0;
    ctx.onstatechange = () => {
      if (disposed || !ctx) return;
      report('context', { state: ctx.state });
      if (running()) resync();
      else status();
    };
    report('context', { state: ctx.state });
  }

  // ---- brauzer: bosish, yashirish
  function unlock() {
    if (disposed || muted || !Ctx || !canStart()) return; // hali bosilmagan: yaratilsa faqat ogohlantirish chiqadi
    if (!ctx) build();
    if (!ctx) {
      status();
      return;
    }
    if (ctx.state !== 'running' && !hidden()) {
      ctx.resume().then(resync, () => status());
    } else {
      resync();
    }
  }

  function onGesture(e) {
    if (e.type === 'keydown' && (e.repeat || e.key === 'Escape')) return;
    if (nav && nav.userActivation && !nav.userActivation.isActive) return;
    unlock();
  }

  function listen(on) {
    if (!doc || on === listening) return;
    listening = on;
    const fn = on ? 'addEventListener' : 'removeEventListener';
    doc[fn]('click', onGesture, true);
    doc[fn]('keydown', onGesture, true);
  }

  function status() {
    if (disposed) return;
    const run = running();
    const want = !muted && !!plan && plan.live && !!Ctx;
    listen(want && !run);                    // ovoz kerak, lekin hali ochilmagan: birinchi bosishda ochiladi
    const blocked = want && !run && !hidden();
    if (blocked !== shown.blocked || run !== shown.running) {
      shown = { blocked, running: run };
      report('status', shown);
      onStatus({ ...shown, muted });
    }
  }

  function onVisibility() {
    if (disposed) return;
    if (ctx && hidden()) {
      cutEffect(); // yashirilgan oynada effekt kechikib chalinmasin
      if (ctx.state === 'running') ctx.suspend().catch(() => {});
    } else if (ctx && !muted && ctx.state !== 'running') {
      ctx.resume().then(resync, () => status());
    }
    status(); // kontekst hali yo'q bo'lsa ham: fon oynada ochilib, endi ko'rindi — «Ovozni yoqish» (A-1)
  }

  function stop() {
    cutEffect();
    endMusic('stop');
    plan = null;
    lastKey = null;
    status();
  }

  if (doc) doc.addEventListener('visibilitychange', onVisibility);
  if (win) win.addEventListener('pagehide', stop);

  return {
    /** O'qituvchi ekranining yangi holati (host state). */
    sync(g) {
      if (disposed || !g) return;
      const p = planFor(g, now(), lastKey);
      const fresh = p.key !== lastKey;
      lastKey = p.key;
      plan = p;
      if (fresh || p.music) apply(p, fresh);
      else status();
    },
    /** Foydalanuvchi bosganda chaqiriladi (Boshlash, Ovozni yoqish, ovoz tugmasi/slayderi). */
    unlock,
    setVolume(v) {
      volume = clampVolume(v);
      if (master && !muted) master.gain.setTargetAtTime(level(), ctx.currentTime, 0.02);
    },
    setMuted(m) {
      muted = !!m;
      if (muted) {
        cutEffect();
        endMusic('mute');
        if (master) master.gain.setTargetAtTime(0, ctx.currentTime, 0.015);
      } else if (master) {
        master.gain.setTargetAtTime(level(), ctx.currentTime, 0.02);
        resync();
      }
      status();
    },
    /** Sozlash sahifasidagi «Sinab ko'rish»: hozirgi balandlikda bitta effekt. */
    preview(name = 'cheer') {
      unlock();
      const go = () => {
        if (!running() || muted) return;
        cutEffect();
        playEffect(name, null);
      };
      if (running()) go();
      else if (ctx && !muted) ctx.resume().then(go, () => {});
    },
    /** O'yin yopildi/tugadi: hamma ovoz to'xtaydi. */
    stop,
    status: () => ({ ...shown, muted }),
    dispose() {
      if (disposed) return;
      stop();
      disposed = true;
      listen(false);
      for (const id of timeouts) clearTimeout(id);
      timeouts.clear();
      if (doc) doc.removeEventListener('visibilitychange', onVisibility);
      if (win) win.removeEventListener('pagehide', stop);
      const c = ctx;
      ctx = null;
      master = null;
      music = null;
      effect = null;
      if (c) {
        c.onstatechange = null;
        try {
          c.close().catch(() => {});
        } catch {
          /* allaqachon yopilgan */
        }
      }
      report('dispose');
    },
  };
}
