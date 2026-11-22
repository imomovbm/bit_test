// Octagon (jonli viktorina) — o'qituvchi ekrani va o'quvchi sahifasi uchun umumiy: o'yin nomi, shakllar va ranglar.
// Bu modul hech narsa import qilmaydi: o'quvchilar sahifasi (/play) asosiy ilovani yuklamaydi.

// O'yin nomi faqat shu yerda. Nomini o'zgartirish uchun shu qatorni almashtiring (masalan: 'Blitz').
export const GAME_NAME = 'Octagon';

// Javob variantlari: rang + shakl (rang yagona belgi emas — shakl doim bor). Ko'pi bilan 4 ta.
export const SHAPES = [
  { id: 'triangle', name: 'qizil uchburchak', bg: '#d7263d', fg: '#ffffff', path: 'M12 2.8 22.4 20.8H1.6Z' },
  { id: 'diamond', name: 'koʻk romb', bg: '#1f63d8', fg: '#ffffff', path: 'M12 1.6 22.4 12 12 22.4 1.6 12Z' },
  { id: 'circle', name: 'sariq doira', bg: '#f2b705', fg: '#2b2000', path: 'M12 2a10 10 0 1 1 0 20a10 10 0 1 1 0-20Z' },
  { id: 'square', name: 'yashil kvadrat', bg: '#1d8a3b', fg: '#ffffff', path: 'M3 3h18v18H3Z' },
];

const SVG_NS = 'http://www.w3.org/2000/svg';

/** Shakl belgisi (inline SVG, tashqi fayllarsiz). */
export function shapeIcon(index, size = 24) {
  const s = SHAPES[index];
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', s.path);
  path.setAttribute('fill', 'currentColor');
  svg.append(path);
  return svg;
}

/** PIN ni o'qish oson bo'lishi uchun guruhlab ko'rsatish: 123456 -> "123 456". */
export function formatPin(pin) {
  const p = String(pin || '');
  return p.length === 6 ? `${p.slice(0, 3)} ${p.slice(3)}` : p;
}
