// «O'yinlar» paneli (faqat o'qituvchilar va administratorlar): Balloon Pop, Octagon va kelajakdagi o'yinlar.
import { h, icon } from '../lib.js';
import { api } from '../api.js';
import { GAME_NAME, SHAPES, formatPin, octagonMark, shapeClass, shapeIcon } from '../octagon/common.js';

const T = {
  title: 'Oʻyinlar',
  lead: 'Sinf uchun jamoaviy va jonli oʻyinlar. Oʻyinlarni faqat oʻqituvchilar va administratorlar yaratadi va boshqaradi.',
  open: 'Ochish',
  resume: 'Davom ettirish',
  activeTitle: 'Davom etayotgan oʻyinlar',
  phase: {
    lobby: 'lobbi', topic_intro: 'boshlanmoqda', question_read: 'savol oʻqilmoqda', question_active: 'savol',
    question_result: 'natija', leaderboard: 'reyting', podium: 'tugagan',
  },
  players: (n) => `${n} ta oʻquvchi`,
  octagon: {
    tag: 'Jonli viktorina',
    text: 'Savollar proyektorda, oʻquvchilar esa telefonda PIN kod bilan qoʻshilib, rangli shakllarni bosib javob beradi. Roʻyxatdan oʻtish shart emas.',
    points: ['PIN va QR kod bilan qoʻshilish', 'Tez va toʻgʻri javob — koʻproq ball (1000 gacha)', 'Har savoldan keyin natija va reyting'],
  },
  balloon: {
    tag: 'Jamoaviy oʻyin',
    text: 'Ikki jamoa «tosh-qaychi-qogʻoz» oʻynaydi, savollarga javob beradi va zar tashlab raqib sharlarini portlatadi. Sharlari tugagan jamoa akulalarga yem!',
    points: ['Bitta ekranda (proyektor yoki doska)', 'Sharlar soni va javob vaqti sozlanadi', 'Yordamlar: AI, guruh, 50:50'],
  },
};

/** Keyingi ehtimoliy sahifa (Octagon o'qituvchi ekrani) moduli bo'sh vaqtda oldindan yuklanadi — bajarilmaydi. */
function prefetchModule(rel) {
  const href = new URL(rel, import.meta.url).href;
  if ([...document.querySelectorAll('link[rel="modulepreload"]')].some((l) => l.href === href)) return;
  const add = () => document.head.append(h('link', { rel: 'modulepreload', href }));
  if ('requestIdleCallback' in window) window.requestIdleCallback(add, { timeout: 2000 });
  else setTimeout(add, 300);
}

export function gamesView(root) {
  let alive = true;
  prefetchModule('./octagon.js');
  const activeBox = h('div');
  root.append(h('section.screen.games',
    h('div.page-head', h('div', h('h1', T.title), h('p.muted', T.lead))),
    activeBox,
    h('div.games-grid',
      gameCard({
        href: '#/games/octagon', art: octagonArt(), title: GAME_NAME, ...T.octagon, cls: 'oct',
      }),
      gameCard({
        href: '#/games/balloon', art: h('span.game-art-ic', icon('balloon', 44)), title: 'Balloon Pop', ...T.balloon, cls: 'balloon',
      }))));

  api('/api/octagon/games').then(({ games }) => {
    if (!alive) return;
    const active = games.filter((g) => g.phase !== 'podium');
    if (!active.length) return;
    activeBox.replaceChildren(h('div.card.games-active',
      h('h2.card-title', icon('activity', 18), T.activeTitle),
      h('ul.adm-list', active.map((g) => h('li.adm-row',
        h('span.adm-act-ic', icon('octagon', 18)),
        h('div.adm-row-main',
          h('div.adm-row-title', `${GAME_NAME} · PIN ${formatPin(g.pin)}`),
          h('div.adm-row-sub', `${g.topicName} · ${T.phase[g.phase] || g.phase} · ${T.players(g.players)}`)),
        h('a.btn.primary.sm', { href: `#/games/octagon/${g.pin}` }, icon('play', 14), T.resume))))));
  }).catch(() => {});

  return () => {
    alive = false;
  };
}

function gameCard({ href, art, title, tag, text, points, cls }) {
  return h(`a.card.game-card.${cls}`, { href },
    h('div.game-art', art),
    h('div.game-body',
      h('span.game-tag', tag),
      h('h2', title),
      h('p.muted', text),
      h('ul.game-points', points.map((p) => h('li', icon('check', 14), p))),
      h('span.btn.primary.game-open', T.open, icon('right', 16))));
}

function octagonArt() {
  return h('div.oct-art', octagonMark(88),
    h('div.oct-art-shapes', SHAPES.map((s, i) => h(`span.oc-fill.${shapeClass(i)}`, { role: 'img', 'aria-label': s.name }, shapeIcon(i, 22)))));
}
