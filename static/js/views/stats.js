// Reyting va shaxsiy natijalar.
import { h, icon, avatar, spinner, emptyState, fmtDate, fmtMs, pct } from '../lib.js';
import { api } from '../api.js';

const RESULT_BADGE = { win: ['Gʻalaba', 'good'], lose: ['Magʻlubiyat', 'bad'], draw: ['Durang', 'neutral'] };
const REASON = {
  score: 'koʻp toʻgʻri javob',
  time: 'tezroq bajarildi',
  draw: 'teng natija',
  left: 'tark etildi',
  afk: 'javob berilmadi',
  both_left: 'ikkalasi chiqdi',
};

export function statsView(root, params, ctx, query) {
  const tab = query.get('tab') === 'me' ? 'me' : 'top';
  const body = h('div.stats-body', spinner());
  const tabBtn = (id, label, ic) => h(`a.tab${tab === id ? '.active' : ''}`, { href: id === 'me' ? '#/stats?tab=me' : '#/stats' }, icon(ic, 16), label);
  root.append(h('section.screen.stats',
    h('div.page-head', h('div', h('h1', 'Reyting'), h('p.muted', 'Duel natijalari boʻyicha ishtirokchilar reytingi va shaxsiy tarixingiz.'))),
    h('div.tabs', tabBtn('top', 'Umumiy reyting', 'trophy'), tabBtn('me', 'Mening natijalarim', 'user')),
    body));

  let alive = true;
  (tab === 'top' ? loadTop(body, ctx) : loadMe(body))
    .catch((e) => alive && body.replaceChildren(emptyState('wifiOff', 'Maʼlumotlarni yuklab boʻlmadi', e.message)));
  return () => {
    alive = false;
  };
}

async function loadTop(body, ctx) {
  const { rows } = await api('/api/stats/leaderboard');
  if (!rows.length) {
    body.replaceChildren(emptyState('trophy', 'Hali duellar oʻtkazilmagan', 'Birinchi duelni oʻtkazing — reyting shu yerda paydo boʻladi.',
      h('a.btn.primary', { href: '#/duel' }, icon('swords', 16), 'Duelga kirish')));
    return;
  }
  const medal = (i) => (i < 3 ? h(`span.medal.m${i + 1}`, String(i + 1)) : h('span.rank', String(i + 1)));
  body.replaceChildren(h('div.card.table-card', h('div.table-wrap', h('table.table',
    h('thead', h('tr',
      h('th', '#'), h('th', 'Ishtirokchi'), h('th.num', 'Duellar'), h('th.num', 'Gʻalaba'), h('th.num.hide-sm', 'Durang'),
      h('th.num.hide-sm', 'Magʻlubiyat'), h('th.num', 'Gʻalaba %'), h('th.num.hide-sm', 'Aniqlik'))),
    h('tbody', rows.map((r, i) => h(`tr${r.id === ctx.user.id ? '.me' : ''}`,
      h('td', medal(i)),
      h('td', h('span.user-cell', avatar(r.login, 'xs'), h('span', r.login), r.id === ctx.user.id ? h('span.tag', 'siz') : null)),
      h('td.num', String(r.played)),
      h('td.num', h('b', String(r.wins))),
      h('td.num.hide-sm', String(r.draws)),
      h('td.num.hide-sm', String(r.losses)),
      h('td.num', `${pct(r.wins, r.played)}%`),
      h('td.num.hide-sm', `${pct(r.correct, r.questions)}%`))))))));
}

async function loadMe(body) {
  const data = await api('/api/stats/me');
  const ds = data.duelSummary;
  const ps = data.practiceSummary;
  const card = (ic, label, value, sub, cls = '') => h(`div.card.sum-card${cls ? `.${cls}` : ''}`,
    h('span.sum-ic', icon(ic, 18)), h('div', h('div.sum-value', value), h('div.sum-label', label), sub ? h('div.small.muted', sub) : null));

  const duelRows = data.duels.map((d) => {
    const [label, cls] = RESULT_BADGE[d.result];
    return h('tr',
      h('td.nowrap.small', fmtDate(d.finishedAt)),
      h('td', d.topicName),
      h('td', h('span.user-cell', avatar(d.opponent, 'xs'), d.opponent)),
      h('td.num.nowrap', h('b', `${d.myCorrect} : ${d.oppCorrect}`), h('div.small.muted', `${fmtMs(d.myTimeMs)} / ${fmtMs(d.oppTimeMs)}`)),
      h('td', h(`span.badge.${cls}`, label), h('div.small.muted', REASON[d.reason] || '')));
  });
  const practiceRows = data.practice.map((p) => h('tr',
    h('td.nowrap.small', fmtDate(p.createdAt)),
    h('td', p.topicName),
    h('td.num', `${p.correct} / ${p.total}`),
    h('td.num', h('b', `${pct(p.correct, p.total)}%`))));

  body.replaceChildren(
    h('div.sum-grid',
      card('swords', 'oʻtkazilgan duel', String(ds.played)),
      card('trophy', 'gʻalaba', String(ds.wins), `${pct(ds.wins, ds.played)}% · ${ds.draws} durang · ${ds.losses} magʻlubiyat`, 'accent'),
      card('target', 'dueldagi aniqlik', `${pct(ds.correct, ds.questions)}%`, `${ds.correct} / ${ds.questions} toʻgʻri javob`),
      card('book', 'mashgʻulot', String(ps.sessions), ps.questions ? `oʻrtacha natija ${pct(ps.correct, ps.questions)}%` : 'hali mashq qilinmagan', 'green')),
    h('h2.section-title', 'Soʻnggi duellar'),
    duelRows.length
      ? h('div.card.table-card', h('div.table-wrap', h('table.table',
        h('thead', h('tr', h('th', 'Sana'), h('th', 'Mavzu'), h('th', 'Raqib'), h('th.num', 'Hisob'), h('th', 'Natija'))),
        h('tbody', duelRows))))
      : h('div.card.muted.center', 'Hali duel oʻtkazmagansiz.'),
    h('h2.section-title', 'Soʻnggi mashgʻulotlar'),
    practiceRows.length
      ? h('div.card.table-card', h('div.table-wrap', h('table.table',
        h('thead', h('tr', h('th', 'Sana'), h('th', 'Mavzu'), h('th.num', 'Natija'), h('th.num', 'Foiz'))),
        h('tbody', practiceRows))))
      : h('div.card.muted.center', 'Hali oʻrganish rejimida mashq qilmagansiz.'));
}
