// Balloon Pop sahnasi (SVG): osmon, dengiz, akulalar, sharlar bog'lamida osilib turgan odamchalar va 3D zar.
import { h } from './lib.js';

const NS = 'http://www.w3.org/2000/svg';
const H = 900;          // sahna balandligi (shartli birliklarda); kengligi ekranga qarab o'zgaradi
const WATER = 720;      // suv sathi
const PERSON = 160;     // odamcha bo'yi: qo'llaridan oyog'igacha
const STRING = 78;      // eng pastki shardan qo'lgacha bo'lgan masofa

export const TEAM_COLORS = {
  red: { hex: '#e5383b', dark: '#a8201f', ink: '#ffffff', name: 'Qizil' },
  blue: { hex: '#2f6fe4', dark: '#1a46a3', ink: '#ffffff', name: 'Koʻk' },
  green: { hex: '#22a447', dark: '#14702e', ink: '#ffffff', name: 'Yashil' },
  orange: { hex: '#f28b0c', dark: '#b35c00', ink: '#2a1600', name: 'Zargʻaldoq' },
  purple: { hex: '#8b46e8', dark: '#5d24ad', ink: '#ffffff', name: 'Binafsha' },
  pink: { hex: '#e24585', dark: '#a8245a', ink: '#ffffff', name: 'Pushti' },
  teal: { hex: '#0ea5a4', dark: '#09706f', ink: '#ffffff', name: 'Feruza' },
  yellow: { hex: '#f5c518', dark: '#a37f00', ink: '#2b2200', name: 'Sariq' },
};

export function teamColor(key) {
  return TEAM_COLORS[key] || TEAM_COLORS.red;
}

/** Jamoa rangi uchun CSS o'zgaruvchilari (tugmalar, belgilar va h.k.). */
export function teamStyle(key) {
  const c = teamColor(key);
  return { '--team': c.hex, '--team-dark': c.dark, '--team-ink': c.ink, '--team-soft': mix(c.hex, '#ffffff', 0.85) };
}

const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
export const wait = (ms) => new Promise((r) => setTimeout(r, reduceMotion() ? Math.min(ms, 60) : ms));

// ------------------------------------------------------------------ ranglar
function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function mix(a, b, t) {
  const x = rgb(a);
  const y = rgb(b);
  return `#${x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('')}`;
}

function shade(hex, amt) {
  return amt >= 0 ? mix(hex, '#ffffff', amt) : mix(hex, '#000000', -amt);
}

// --------------------------------------------------------------------- SVG
function s(tag, attrs, ...children) {
  const el = document.createElementNS(NS, tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'style' && typeof v === 'object') {
        for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
      } else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, String(v));
    }
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

// ------------------------------------------------------------ shar bog'lami
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const VARIANT = [0, 0.12, -0.1, 0.2, -0.16, 0.06, -0.05, 0.15, -0.02];
const layouts = new Map();

/** n ta sharning bog'lamdagi joylashuvi (Vogel spirali). Qo'l (iplar uchrashadigan nuqta) — (0, 0). */
export function bunchLayout(n) {
  if (layouts.has(n)) return layouts.get(n);
  const R = Math.min(152, 34 * Math.sqrt(n));
  const d = R * Math.sqrt(Math.PI / n);
  const r = Math.max(15, Math.min(36, d * 0.64));
  const cy = -(STRING + R * 0.95 + r * 0.4);
  const pts = [];
  for (let i = 0; i < n; i++) {
    const rho = R * Math.sqrt((i + 0.5) / n);
    const th = i * GOLDEN + 1.2;
    pts.push({ i, x: Math.cos(th) * rho * 1.12, y: cy + Math.sin(th) * rho * 0.95, r: r * (0.93 + ((i * 37) % 11) / 90) });
  }
  const top = Math.min(...pts.map((p) => p.y - p.r)) - 6;
  const layout = { pts, order: [...pts].sort((a, b) => a.y - b.y), top, width: R * 1.12 * 2 + r * 2 };
  layouts.set(n, layout);
  return layout;
}

function balloonPath(r) {
  const w = r * 0.88;
  return `M0 ${-r}C${w * 1.3} ${-r} ${w * 1.12} ${r * 0.58} 0 ${r}C${-w * 1.12} ${r * 0.58} ${-w * 1.3} ${-r} 0 ${-r}Z`;
}

function balloonEl(p, c) {
  const fill = shade(c.hex, VARIANT[p.i % VARIANT.length]);
  const r = p.r;
  return s('g', { class: 'bp-balloon', transform: `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`, 'data-i': p.i },
    s('g', { class: 'bp-bal' },
      s('circle', { class: 'bp-hit', r: (r * 1.18).toFixed(1) }),
      s('path', { d: balloonPath(r), fill, stroke: shade(fill, -0.28), 'stroke-width': 2.2 }),
      s('ellipse', { cx: (-r * 0.34).toFixed(1), cy: (-r * 0.42).toFixed(1), rx: (r * 0.19).toFixed(1), ry: (r * 0.33).toFixed(1), fill: '#fff', opacity: 0.55, transform: `rotate(28 ${(-r * 0.34).toFixed(1)} ${(-r * 0.42).toFixed(1)})` }),
      s('path', { d: `M${-r * 0.16} ${r + 7}L0 ${r - 1}L${r * 0.16} ${r + 7}Z`, fill: shade(fill, -0.22) })));
}

function stringEl(p) {
  const y0 = p.y + p.r + 6;
  return s('path', { class: 'bp-string', 'data-i': p.i, d: `M${p.x.toFixed(1)} ${y0.toFixed(1)}Q${(p.x * 0.25).toFixed(1)} ${(y0 * 0.45).toFixed(1)} 0 0` });
}

/** Lobbi uchun kichik bog'lam (rangni tanlashda ko'rinadi). */
export function miniBunch(colorKey, n = 9) {
  const c = teamColor(colorKey);
  const L = bunchLayout(n);
  const pad = 12;
  const minX = Math.min(...L.pts.map((p) => p.x - p.r)) - pad;
  const maxX = Math.max(...L.pts.map((p) => p.x + p.r)) + pad;
  const svg = s('svg', { class: 'bp-mini', viewBox: `${minX.toFixed(0)} ${L.top.toFixed(0)} ${(maxX - minX).toFixed(0)} ${(-L.top + 70).toFixed(0)}`, 'aria-hidden': 'true' },
    s('g', { class: 'bp-strings' }, L.pts.map(stringEl)),
    L.order.map((p) => balloonEl(p, c)),
    s('circle', { cx: 0, cy: 6, r: 7, fill: c.hex, stroke: c.dark, 'stroke-width': 2 }));
  return svg;
}

// ---------------------------------------------------------------- odamcha
function personEl(c) {
  const face = (mood, ...parts) => s('g', { class: `bp-expr ${mood}` }, parts);
  // har bir ifoda uchun alohida ko'zlar (bitta DOM tugunini ikki joyga qo'shib bo'lmaydi)
  const eyes = () => [s('circle', { cx: -6, cy: 31, r: 2.6, class: 'bp-ink' }), s('circle', { cx: 6, cy: 31, r: 2.6, class: 'bp-ink' })];
  const bigEyes = [-6, 6].map((x) => s('g', {},
    s('circle', { cx: x, cy: 30, r: 4.6, fill: '#fff', class: 'bp-line', 'stroke-width': 1.6 }),
    s('circle', { cx: x, cy: 31, r: 2, class: 'bp-ink' })));
  return s('g', { class: 'bp-person' },
    s('path', { class: 'bp-arm', d: 'M-7 2L-19 62M7 2L19 62', stroke: c.dark }),
    s('g', { transform: 'translate(0 110)' },
      s('g', { class: 'bp-legs' },
        s('path', { class: 'bp-leg', d: 'M-8 0L-12 44M8 0L12 44' }),
        s('ellipse', { class: 'bp-shoe', cx: -15, cy: 47, rx: 8.5, ry: 4.6 }),
        s('ellipse', { class: 'bp-shoe', cx: 15, cy: 47, rx: 8.5, ry: 4.6 }))),
    s('path', { d: 'M-20 64Q-21 57-14 56H14Q21 57 20 64L18 110Q0 117-18 110Z', fill: c.hex, stroke: c.dark, 'stroke-width': 3 }),
    s('path', { d: 'M-7 57L0 66L7 57', fill: 'none', stroke: c.dark, 'stroke-width': 2.5, 'stroke-linejoin': 'round' }),
    s('circle', { class: 'bp-head', cx: 0, cy: 34, r: 17 }),
    face('happy', ...eyes(), s('path', { class: 'bp-mouth', d: 'M-7 39Q0 47 7 39' })),
    face('worried', ...eyes(),
      s('path', { class: 'bp-mouth', d: 'M-10 26L-3 23M10 26L3 23' }),
      s('path', { class: 'bp-mouth', d: 'M-6 43Q-3 40.5 0 43T6 43' })),
    face('scared', ...bigEyes,
      s('path', { class: 'bp-mouth', d: 'M-11 21L-3 19M11 21L3 19' }),
      s('ellipse', { cx: 0, cy: 43.5, rx: 4.2, ry: 5.6, class: 'bp-ink' }),
      s('path', { class: 'bp-sweat', d: 'M16 16Q20.5 23 16 26.5Q11.5 23 16 16Z' })),
    s('circle', { class: 'bp-hand', cx: -7, cy: 2, r: 5.5 }),
    s('circle', { class: 'bp-hand', cx: 7, cy: 2, r: 5.5 }));
}

// ------------------------------------------------------------------ akula
function sharkEl(c) {
  const body = mix(c.hex, '#5b6676', 0.22);
  const dark = shade(body, -0.3);
  return s('g', { class: 'bp-shark-art' },
    s('path', { d: 'M-94-4L-150-48Q-138-6-150 40Z', fill: body, stroke: dark, 'stroke-width': 3, 'stroke-linejoin': 'round' }),
    s('path', { d: 'M-22-34Q4-66 22-100Q36-62 34-30Z', fill: body, stroke: dark, 'stroke-width': 3, 'stroke-linejoin': 'round' }),
    s('path', { d: 'M-104-2C-70-46 40-54 98-18C114-8 116 6 102 13C60 36-50 38-104-2Z', fill: body, stroke: dark, 'stroke-width': 3 }),
    s('path', { d: 'M-78 12C-30 32 52 30 99 12C72 30-40 36-78 12Z', fill: '#eef3f6' }),
    s('path', { d: 'M4 16Q-6 42-22 54Q20 44 36 20Z', fill: dark }),
    s('path', { d: 'M46-18Q41-5 46 8M55-20Q50-6 55 8M64-20Q59-7 64 6', fill: 'none', stroke: dark, 'stroke-width': 2.4, 'stroke-linecap': 'round' }),
    s('circle', { cx: 77, cy: -15, r: 5.6, fill: '#fff' }),
    s('circle', { cx: 78.5, cy: -15, r: 3, fill: '#151821' }),
    s('path', { class: 'bp-brow', d: 'M68-25L86-19', stroke: dark, 'stroke-width': 3.2, 'stroke-linecap': 'round' }),
    s('path', { d: 'M74 10Q90 16 106 6', fill: 'none', stroke: dark, 'stroke-width': 2.6, 'stroke-linecap': 'round' }),
    s('path', { class: 'bp-teeth', d: 'M79 10.5L82 16L85 11.5L88 16.5L91 11.5L94 15.5L97 10Z', fill: '#fff' }));
}

// ------------------------------------------------------------------- bulut
function cloudEl(x, y, sc, dur, delay) {
  return s('g', { transform: `translate(${x} ${y}) scale(${sc})` },
    s('g', { class: 'bp-cloud', style: { '--d': `${dur}s`, 'animation-delay': `${delay}s` } },
      s('ellipse', { cx: 0, cy: 18, rx: 92, ry: 26 }),
      s('circle', { cx: -40, cy: 6, r: 32 }),
      s('circle', { cx: 6, cy: -8, r: 44 }),
      s('circle', { cx: 50, cy: 10, r: 28 })));
}

function wavePath(W, y, amp, len) {
  let d = `M${-2 * len} ${y}`;
  for (let x = -2 * len; x < W + 2 * len; x += len) d += `q${len / 4} ${-amp} ${len / 2} 0t${len / 2} 0`;
  return `${d}V${H + 20}H${-2 * len}Z`;
}

const rand = (seed) => () => {
  seed = (seed * 16807) % 2147483647;
  return (seed - 1) / 2147483646;
};

// ================================================================== jamoa
class TeamView {
  constructor(scene, index) {
    this.scene = scene;
    this.index = index;
    this.x = 0;
    this.y = 400;
    this.k = 1;
    this.el = s('g', { class: 'bp-team', 'data-team': index, 'data-mood': 'happy' });
    this.shark = s('g', { class: 'bp-shark', 'data-mood': 'calm' });
    this.balloonEls = new Map();
    this.stringEls = new Map();
    this.onPick = null;
  }

  build(team, opponent, total) {
    const c = teamColor(team.color);
    this.total = total;
    this.layout = bunchLayout(total);
    const gone = new Set(team.popped);
    this.balloonEls.clear();
    this.stringEls.clear();
    const strings = s('g', { class: 'bp-strings' });
    const balloons = s('g', { class: 'bp-balloons' });
    for (const p of this.layout.pts) {
      if (gone.has(p.i)) continue;
      const str = stringEl(p);
      this.stringEls.set(p.i, str);
      strings.append(str);
    }
    for (const p of this.layout.order) {
      if (gone.has(p.i)) continue;
      const b = balloonEl(p, c);
      b.addEventListener('click', () => this.onPick && this.onPick(this.index, p.i));
      this.balloonEls.set(p.i, b);
      balloons.append(b);
    }
    this.el.replaceChildren(s('g', { class: 'bp-bob', style: { 'animation-delay': `${-this.index * 1.7}s` } },
      strings,
      balloons,
      s('g', { class: 'bp-swing', style: { 'animation-delay': `${-this.index * 2.3}s` } }, personEl(c))));
    this.el.classList.remove('falling', 'gone', 'no-anim');
    this.shark.classList.remove('leaping');
    this.shark.replaceChildren(s('g', { class: 'bp-shark-swim', style: { 'animation-delay': `${-this.index * 3.1}s` } },
      s('g', { class: 'bp-shark-bob' }, s('g', { class: 'bp-shark-leap' }, sharkEl(teamColor(opponent.color))))));
    this.left = total - gone.size;
    if (this.left <= 0) this.el.classList.add('gone');
    this.update(this.left, false);
  }

  yFor(left) {
    const top = 26 - this.layout.top * this.k;
    const low = WATER - PERSON * this.k - 10;
    const f = this.total ? left / this.total : 0;
    return low - f * (low - top);
  }

  place(x, k) {
    this.x = x;
    this.k = k;
    this.el.classList.add('no-anim');
    this.apply();
    this.shark.setAttribute('transform', `translate(${x.toFixed(1)} 800) scale(${(0.9 * k).toFixed(3)})`);
    requestAnimationFrame(() => this.el.classList.remove('no-anim'));
  }

  apply() {
    if (!this.layout) return;
    this.y = this.yFor(this.left);
    if (!this.el.classList.contains('falling')) {
      this.el.style.transform = `translate(${this.x.toFixed(1)}px, ${this.y.toFixed(1)}px) scale(${this.k.toFixed(3)})`;
    }
  }

  update(left, animate = true) {
    this.left = left;
    const f = this.total ? left / this.total : 0;
    this.el.dataset.mood = f > 0.6 ? 'happy' : f > 0.3 ? 'worried' : 'scared';
    this.shark.dataset.mood = left <= 0 ? 'full' : f > 0.5 ? 'calm' : f > 0.25 ? 'hungry' : 'frenzy';
    if (!animate) this.el.classList.add('no-anim');
    this.apply();
    if (!animate) requestAnimationFrame(() => this.el.classList.remove('no-anim'));
  }

  setPickable(on) {
    this.el.classList.toggle('pickable', !!on);
  }

  has(i) {
    return this.balloonEls.has(i);
  }

  alive() {
    return [...this.balloonEls.keys()];
  }

  pop(i) {
    const b = this.balloonEls.get(i);
    if (!b) return false;
    this.balloonEls.delete(i);
    const str = this.stringEls.get(i);
    this.stringEls.delete(i);
    const p = this.layout.pts[i];
    const burst = s('g', { class: 'bp-burst' });
    for (let k = 0; k < 10; k++) {
      const a = (k / 10) * Math.PI * 2 + 0.3;
      const r0 = p.r * 0.8;
      const r1 = p.r * (1.45 + (k % 3) * 0.18);
      burst.append(s('line', { x1: (Math.cos(a) * r0).toFixed(1), y1: (Math.sin(a) * r0).toFixed(1), x2: (Math.cos(a) * r1).toFixed(1), y2: (Math.sin(a) * r1).toFixed(1) }));
    }
    burst.append(s('text', { class: 'bp-pop-text', y: (-p.r * 1.35).toFixed(1) }, 'POP!'));
    b.append(burst);
    b.classList.add('popping');
    if (str) str.classList.add('gone');
    setTimeout(() => {
      b.remove();
      if (str) str.remove();
    }, 900);
    return true;
  }

  /** Oxirgi shar portladi: odamcha suvga tushadi, akula sakrab uni yeb qo'yadi. */
  async fall() {
    const swim = this.shark.querySelector('.bp-shark-swim');
    if (swim) {
      // akulani hozirgi joyidan odamcha ostiga silliq olib kelamiz
      const current = getComputedStyle(swim).transform;
      swim.style.transform = current === 'none' ? '' : current;
      swim.classList.add('stopped');
      void swim.getBoundingClientRect();
      swim.style.transition = 'transform 0.45s ease-out';
      swim.style.transform = 'translateX(0px) scaleX(1)';
    }
    this.el.dataset.mood = 'scared';
    this.el.classList.add('falling');
    await wait(260);
    this.el.style.transform = `translate(${this.x.toFixed(1)}px, ${H + 160}px) scale(${this.k.toFixed(3)})`;
    await wait(560);
    this.scene.splash(this.x, this.k);
    this.shark.classList.add('leaping');
    await wait(900);
    this.el.classList.add('gone');
  }
}

// ================================================================== sahna
export class Scene {
  constructor() {
    this.W = 1600;
    this.px = 0.5;
    this.teams = [new TeamView(this, 0), new TeamView(this, 1)];
    const sky = s('linearGradient', { id: 'bp-sky', x1: 0, y1: 0, x2: 0, y2: 1 },
      s('stop', { offset: 0, class: 'bp-sky1' }), s('stop', { offset: 1, class: 'bp-sky2' }));
    const sea = s('linearGradient', { id: 'bp-sea', x1: 0, y1: 0, x2: 0, y2: 1 },
      s('stop', { offset: 0, class: 'bp-sea1' }), s('stop', { offset: 1, class: 'bp-sea2' }));
    const glow = s('radialGradient', { id: 'bp-glow' },
      s('stop', { offset: 0.45, class: 'bp-glow1' }), s('stop', { offset: 1, class: 'bp-glow2' }));
    this.skyRect = s('rect', { x: 0, y: 0, height: WATER + 30, fill: 'url(#bp-sky)' });
    const rnd = rand(42);
    this.stars = s('g', { class: 'bp-stars' });
    this.starPts = Array.from({ length: 46 }, () => [rnd(), rnd() * 0.55, 0.8 + rnd() * 1.9, rnd() * 3]);
    this.sun = s('g', { class: 'bp-sun' },
      s('circle', { r: 120, fill: 'url(#bp-glow)' }),
      s('circle', { class: 'bp-sun-disc', r: 54 }),
      s('circle', { class: 'bp-crater', cx: -16, cy: -12, r: 10 }),
      s('circle', { class: 'bp-crater', cx: 18, cy: 10, r: 7 }),
      s('circle', { class: 'bp-crater', cx: -4, cy: 22, r: 5 }));
    this.clouds = s('g', { class: 'bp-clouds' });
    this.birds = s('g', { class: 'bp-birds' });
    this.backWave = s('path', { class: 'bp-wave back', fill: 'url(#bp-sea)' });
    this.frontWave = s('path', { class: 'bp-wave front' });
    this.bubbles = s('g', { class: 'bp-bubbles' });
    this.fx = s('g', { class: 'bp-fx' });
    this.svg = s('svg', { class: 'bp-svg', viewBox: `0 0 ${this.W} ${H}`, preserveAspectRatio: 'xMidYMid slice', role: 'img', 'aria-label': 'Oʻyin sahnasi: sharlarda osilib turgan jamoalar va akulalar' },
      s('defs', {}, sky, sea, glow),
      this.skyRect, this.stars, this.sun, this.clouds, this.birds,
      this.teams[0].el, this.teams[1].el,
      this.backWave,
      s('g', { class: 'bp-sharks' }, this.teams[0].shark, this.teams[1].shark),
      this.bubbles,
      this.frontWave,
      this.fx);
    this.el = this.svg;
  }

  build(game) {
    this.teams.forEach((t, i) => t.build(game.teams[i], game.teams[1 - i], game.balloons));
  }

  set onPick(fn) {
    this.teams.forEach((t) => {
      t.onPick = fn;
    });
  }

  /** Sahna o'lchami o'zgarganda: kenglikni ekranga moslaymiz (balandlik doim H birlik). */
  layout(width, height) {
    if (!width || !height) return;
    const W = Math.max(700, Math.round((H * width) / height));
    this.px = height / H;
    const key = `${W}:${Math.round(width)}`;
    if (key === this.layoutKey) return;
    this.layoutKey = key;
    this.W = W;
    this.svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    this.skyRect.setAttribute('width', W);
    // tor ekranlarda (telefon) jamoalar biroz kichikroq chiziladi;
    // jamoalar orasidagi masofa piksellarda hisoblanadi — past va keng sahnada ham ular markazga yopishib qolmaydi
    const k = Math.max(0.7, Math.min(1, width / 800));
    const dx = Math.min(Math.min(width * 0.29, 540) / this.px, W * 0.4);
    this.teams[0].place(W / 2 - dx, k);
    this.teams[1].place(W / 2 + dx, k);
    this.sun.setAttribute('transform', `translate(${W - Math.min(170, W * 0.1)} 118) scale(${k})`);
    this.stars.replaceChildren(...this.starPts.map(([x, y, r, d]) => s('circle', { cx: (x * W).toFixed(0), cy: (y * H).toFixed(0), r: r.toFixed(1), style: { 'animation-delay': `${-d}s` } })));
    this.clouds.replaceChildren(
      cloudEl(W * 0.08, 120, 0.9 * k, 26, -4),
      cloudEl(W * 0.36, 70, 0.62 * k, 31, -11),
      cloudEl(W * 0.66, 160, 0.75 * k, 23, -7),
      cloudEl(W * 0.93, 300, 0.58 * k, 35, -15),
      cloudEl(W * 0.22, 390, 0.5 * k, 29, -2));
    this.birds.replaceChildren(...[[0.3, 230, 0], [0.34, 262, -0.4], [0.72, 110, -0.2]].map(([x, y, d]) => s('g', { transform: `translate(${(x * W).toFixed(0)} ${y}) scale(${k})` },
      s('path', { class: 'bp-bird', d: 'M-14 0Q-7-8 0 0Q7-8 14 0', style: { 'animation-delay': `${d}s` } }))));
    this.backWave.setAttribute('d', wavePath(W, WATER, 9, 140));
    this.frontWave.setAttribute('d', wavePath(W, WATER + 26, 7, 110));
    const rnd = rand(7);
    this.bubbles.replaceChildren(...Array.from({ length: 10 }, () => s('circle', {
      cx: (rnd() * W).toFixed(0), cy: (812 + rnd() * 70).toFixed(0), r: (3 + rnd() * 5).toFixed(1),
      style: { 'animation-delay': `${-(rnd() * 6).toFixed(2)}s`, 'animation-duration': `${(4 + rnd() * 4).toFixed(2)}s` },
    })));
  }

  splash(x, k) {
    const g = s('g', { class: 'bp-splash', transform: `translate(${x.toFixed(0)} ${WATER}) scale(${k})` });
    for (let i = 0; i < 3; i++) g.append(s('ellipse', { class: 'bp-ripple', rx: 60, ry: 12, style: { 'animation-delay': `${i * 0.18}s` } }));
    for (let i = 0; i < 16; i++) {
      const a = -Math.PI / 2 + (Math.random() - 0.5) * 2.2;
      const v = 120 + Math.random() * 170;
      g.append(s('circle', { class: 'bp-drop', r: (4 + Math.random() * 7).toFixed(1), style: { '--dx': `${(Math.cos(a) * v).toFixed(0)}px`, '--dy': `${(Math.sin(a) * v).toFixed(0)}px`, 'animation-delay': `${(Math.random() * 0.12).toFixed(2)}s` } }));
    }
    g.append(s('text', { class: 'bp-chomp-text', y: -170 }, 'CHOMP!'));
    this.fx.append(g);
    setTimeout(() => g.remove(), 2600);
  }
}

// ====================================================================== zar
const FACE_ROT = { 1: [0, 0], 6: [0, 180], 2: [0, -90], 5: [0, 90], 3: [-90, 0], 4: [90, 0] };
const PIPS = { 1: [5], 2: [3, 7], 3: [3, 5, 7], 4: [1, 3, 7, 9], 5: [1, 3, 5, 7, 9], 6: [1, 3, 4, 6, 7, 9] };

export class Dice {
  constructor() {
    this.cube = h('div.bp-dice', [1, 2, 3, 4, 5, 6].map((n) => h(`div.bp-face.f${n}`,
      PIPS[n].map((c) => h('i', { style: { gridArea: `${Math.ceil(c / 3)} / ${((c - 1) % 3) + 1}` } })))));
    this.num = h('div.bp-dice-num');
    this.el = h('div.bp-dice-wrap', h('div.bp-dice-toss', this.cube), this.num);
    this.rx = 0;
    this.ry = 0;
    this.show(6);
  }

  setColor(key) {
    const c = teamColor(key);
    this.el.style.setProperty('--dice', c.hex);
    this.el.style.setProperty('--dice-dark', c.dark);
    this.el.style.setProperty('--pip', c.ink === '#ffffff' ? '#ffffff' : c.ink);
  }

  show(value) {
    const [x, y] = FACE_ROT[value] || FACE_ROT[1];
    this.rx = x;
    this.ry = y;
    this.cube.style.transition = 'none';
    this.cube.style.transform = `rotateX(${x}deg) rotateY(${y}deg)`;
    this.num.textContent = '';
    this.el.classList.remove('shaking', 'tossing', 'landed');
  }

  shake() {
    this.num.textContent = '';
    this.el.classList.remove('landed');
    this.el.classList.add('shaking');
  }

  async roll(value) {
    const [bx, by] = FACE_ROT[value];
    const next = (cur, base, spins) => base + 360 * Math.ceil((cur - base) / 360) + 360 * spins;
    this.rx = next(this.rx, bx, 2 + Math.floor(Math.random() * 2));
    this.ry = next(this.ry, by, 2 + Math.floor(Math.random() * 2));
    this.el.classList.remove('shaking', 'landed');
    void this.el.offsetWidth;
    this.el.classList.add('tossing');
    this.cube.style.transition = reduceMotion() ? 'none' : 'transform 1.3s cubic-bezier(0.18, 0.72, 0.24, 1)';
    this.cube.style.transform = `rotateX(${this.rx}deg) rotateY(${this.ry}deg)`;
    await wait(1350);
    this.el.classList.remove('tossing');
    this.num.textContent = String(value);
    this.el.classList.add('landed');
  }
}
