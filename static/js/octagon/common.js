// Octagon (jonli viktorina) — o'qituvchi ekrani va o'quvchi sahifasi uchun umumiy: o'yin nomi, shakllar, logotip.
// Bu modul hech narsa import qilmaydi: o'quvchilar sahifasi (/play) asosiy ilovani yuklamaydi.
// Ranglar JS da yo'q — faqat static/css/octagon-theme.css dagi o'zgaruvchilar (.oc-c0 … .oc-c3 sinflari orqali).

// O'yin nomi faqat shu yerda. Nomini o'zgartirish uchun shu qatorni almashtiring (masalan: 'Blitz').
export const GAME_NAME = 'Octagon';

// Javob variantlari: rang + shakl (rang yagona belgi emas — har bir rangning o'z shakli bor). Ko'pi bilan 4 ta.
// Shakllar kichik o'lchamda ham bir-biridan aniq farq qiladi: burchakli, tomchi, yulduz, plyus.
export const SHAPES = [
  { id: 'octagon', name: 'Qizil sakkizburchak', path: 'M8.06 2.5h7.88l5.56 5.56v7.88l-5.56 5.56H8.06L2.5 15.94V8.06Z' },
  { id: 'drop', name: 'Koʻk tomchi', path: 'M12 2C12 2 4.5 9.6 4.5 14.5a7.5 7.5 0 0 0 15 0C19.5 9.6 12 2 12 2Z' },
  { id: 'star', name: 'Sariq yulduz', path: 'M12 2.45l2.73 6.64 7.16.55-5.47 4.65 1.69 6.97L12 17.5l-6.11 3.76 1.69-6.97-5.47-4.65 7.16-.55Z' },
  { id: 'plus', name: 'Yashil plyus', path: 'M8.9 2.5h6.2v6.4h6.4v6.2h-6.4v6.4H8.9v-6.4H2.5V8.9h6.4Z' },
];

const SVG_NS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

/** Rang sinfi: .oc-c0 … .oc-c3 (octagon-theme.css). */
export function shapeClass(index) {
  return `oc-c${index}`;
}

/** Shakl belgisi (inline SVG, tashqi fayllarsiz; rangi — currentColor). */
export function shapeIcon(index, size = 24) {
  const svg = svgEl('svg', { viewBox: '0 0 24 24', width: size, height: size, 'aria-hidden': 'true', focusable: 'false', class: 'oc-shape' });
  svg.append(svgEl('path', { d: SHAPES[index].path, fill: 'currentColor' }));
  return svg;
}

// Logotip: to'rtta javob rangidan (o'quvchi tugmalari tartibida) tuzilgan sakkizburchak
const MARK_PARTS = [
  ['q0', 'M16 16H1.5V9.99L9.99 1.5H16Z'],
  ['q1', 'M16 16V1.5h6.01l8.49 8.49V16Z'],
  ['q2', 'M16 16v14.5H9.99L1.5 22.01V16Z'],
  ['q3', 'M16 16h14.5v6.01l-8.49 8.49H16Z'],
  ['hub', 'M14.03 11.25h3.94l2.78 2.78v3.94l-2.78 2.78h-3.94l-2.78-2.78v-3.94Z'],
];

export function octagonMark(size = 32, label = '') {
  const svg = svgEl('svg', { viewBox: '0 0 32 32', width: size, height: size, class: 'oc-mark', focusable: 'false' });
  if (label) {
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', label);
  } else {
    svg.setAttribute('aria-hidden', 'true');
  }
  for (const [cls, d] of MARK_PARTS) svg.append(svgEl('path', { class: cls, d }));
  return svg;
}

// Sakkizburchak yo'li (viewBox 0 0 100 100), yuqori o'rtadan soat yo'nalishida — taymer va yuklanish belgisi uchun
export const OCTAGON_RING = 'M50 6H68.23L94 31.77V68.23L68.23 94H31.77L6 68.23V31.77L31.77 6Z';

/** Yuklanish belgisi: aylanayotgan sakkizburchak chizig'i. */
export function octagonLoader(small = false) {
  const svg = svgEl('svg', { viewBox: '0 0 100 100', class: `oc-loader${small ? ' sm' : ''}`, 'aria-hidden': 'true', focusable: 'false' });
  svg.append(svgEl('path', { class: 'track', d: OCTAGON_RING }), svgEl('path', { d: OCTAGON_RING, pathLength: 100 }));
  return svg;
}

/** PIN ni o'qish oson bo'lishi uchun guruhlab ko'rsatish: 123456 -> "123 456". */
export function formatPin(pin) {
  const p = String(pin || '');
  return p.length === 6 ? `${p.slice(0, 3)} ${p.slice(3)}` : p;
}
