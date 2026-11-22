// Mavzular katalogi (bosh sahifa — Duel va O'rganish): davr yorliqlari (qizg'in/bugun/hafta/oy/hamma vaqt),
// kechiktirilgan qidiruv, server tomonida sahifalash (GET /api/topics/browse) va cheksiz aylantirish.
// Hech qachon barcha mavzular birdaniga yuklanmaydi: har so'rovda ko'pi bilan TOPICS_PAGE ta.
import { h, icon, fmtAgo, spinner, emptyState } from './lib.js';
import { api } from './api.js';
import { live } from './live.js';

const PERIOD_TABS = [
  ['hot', 'Qizgʻin'],
  ['today', 'Bugun'],
  ['week', 'Hafta'],
  ['month', 'Oy'],
  ['all', 'Hammasi'],
];
const PERIOD_LABEL = { today: 'Bugun', week: 'Shu hafta', month: 'Shu oy', all: 'Jami' };
const TOPICS_PAGE = 24;

function savedTab(key) {
  try {
    const v = localStorage.getItem(key);
    return PERIOD_TABS.some(([k]) => k === v) ? v : 'hot';
  } catch {
    return 'hot';
  }
}

function saveTab(key, v) {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* e'tiborsiz: maxfiy oyna */
  }
}

export function debounce(fn, ms) {
  let t = 0;
  const wrapped = (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
  wrapped.cancel = () => clearTimeout(t);
  return wrapped;
}

/** replaceChildren — null/false bolalarsiz (aks holda brauzer ularni "null" matni sifatida qo'yadi). */
export const fill = (el, ...kids) => el.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));

/** Kartochkadagi izoh: tanlangan davrdagi duellar soni va oxirgi o'yin vaqti. */
function topicHint(t, period) {
  let main = null;
  if (period === 'hot') {
    if (t.today) main = `Bugun ${t.today} ta duel`;
    else if (t.week) main = `Shu hafta ${t.week} ta duel`;
  } else if (t.periodCount) {
    main = `${PERIOD_LABEL[period]} ${t.periodCount} ta duel`;
  }
  const last = t.lastPlayedAt ? `oxirgi oʻyin: ${fmtAgo(t.lastPlayedAt)}` : 'hali oʻynalmagan';
  return { main, last };
}

/** Jonli belgi: "N kutmoqda · M oʻynamoqda" (ikkalasi 0 bo'lsa — yashirin). */
function liveBadge(el, waiting, playing) {
  fill(el,
    waiting ? h('span.lb-wait', h('span.pulse-dot'), `${waiting} kutmoqda`) : null,
    playing ? h('span.lb-play', icon('swords', 13), `${playing} oʻynamoqda`) : null);
  el.hidden = !waiting && !playing;
}

function skeletonCards(n) {
  return Array.from({ length: n }, () => h('div.topic-card.skeleton', { 'aria-hidden': 'true' },
    h('span.sk.sk-icon'), h('span.sk.sk-title'), h('span.sk.sk-line'), h('span.sk.sk-line.short')));
}

/**
 * Mavzular katalogi. variant: 'duel' (jonli kutish/o'ynash sonlari, "Raqib topish") yoki 'practice' ("Mashq qilish").
 * onPick(topic) — kartochka bosilganda; onWatch(ids) — ekrandagi kartochkalar o'zgarganda (jonli sonlar obunasi uchun).
 */
export function topicBrowser({ user, onPick, variant = 'duel', onWatch = null, storageKey = 'td-topic-tab', title = 'Mavzular' }) {
  const duel = variant === 'duel';
  let period = savedTab(storageKey);
  let query = '';
  let items = [];
  let total = 0;
  let nextOffset = 0;
  let loading = false;
  let error = null;
  let req = 0;
  const cards = new Map();
  const visible = new Set();

  const tabs = h('div.period-tabs', { role: 'tablist', 'aria-label': 'Davr' });
  const search = h('input', {
    type: 'search', placeholder: 'Mavzu qidirish…', maxlength: '100', 'aria-label': 'Mavzu qidirish', autocomplete: 'off',
    oninput: () => onSearch(),
  });
  const summary = h('p.small.muted.browse-summary', { 'aria-live': 'polite' });
  const grid = h('div.topic-grid');
  const more = h('div.browse-more');
  const sentinel = h('div.browse-sentinel', { 'aria-hidden': 'true' });
  const el = h('section.browse',
    h('div.browse-head',
      h('h2', title),
      h('div.browse-search', icon('search', 17), search)),
    tabs,
    summary,
    grid,
    more,
    sentinel);

  const onSearch = debounce(() => {
    const v = search.value.trim();
    if (v === query) return;
    query = v;
    load(true);
  }, 300);

  function paintTabs() {
    tabs.replaceChildren(...PERIOD_TABS.map(([key, label]) => h('button.period-tab', {
      type: 'button',
      role: 'tab',
      'aria-selected': key === period ? 'true' : 'false',
      class: key === period ? 'active' : '',
      onclick: () => {
        if (key === period) return;
        period = key;
        saveTab(storageKey, key);
        paintTabs();
        load(true);
      },
    }, label)));
  }

  const watchChanged = debounce(() => onWatch && onWatch([...visible].slice(0, 60)), 400);
  const cardObserver = onWatch && 'IntersectionObserver' in window
    ? new IntersectionObserver((entries) => {
      let changed = false;
      for (const e of entries) {
        const id = Number(e.target.dataset.tid);
        if (e.isIntersecting && !visible.has(id)) {
          visible.add(id);
          changed = true;
        } else if (!e.isIntersecting && visible.has(id)) {
          visible.delete(id);
          changed = true;
        }
      }
      if (changed) watchChanged();
    }, { rootMargin: '120px 0px' })
    : null;
  const moreObserver = 'IntersectionObserver' in window
    ? new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMore();
    }, { rootMargin: '400px 0px' })
    : null;
  if (moreObserver) moreObserver.observe(sentinel);

  function counts(t) {
    const c = live.lobby.counts[String(t.id)];
    return c ? c : [t.waiting || 0, t.playing || 0];
  }

  function makeCard(t) {
    const hint = topicHint(t, period);
    const badge = h('span.topic-live', { hidden: true });
    const cta = h('span.topic-cta');
    const meta = duel
      ? `${t.questionCount} ta savol · duelda ${Math.min(t.questionCount, live.rules.duelQuestions)} ta`
      : `${t.questionCount} ta savol`;
    const card = h(`button.topic-card${duel ? '' : '.practice'}`, {
      type: 'button',
      dataset: { tid: String(t.id) },
      onclick: () => onPick(t),
    },
    h('div.topic-top', duel ? h('span.topic-icon', icon('swords', 22)) : h('span.topic-icon.green', icon('book', 22)), badge),
    h('div.topic-name', t.name),
    h('div.topic-hint', hint.main ? h('b', hint.main) : null, h('span', hint.last)),
    h('div.topic-meta', meta),
    cta);
    const entry = {
      card,
      paint() {
        if (!duel) {
          cta.replaceChildren('Mashq qilish', icon('right', 16));
          return;
        }
        const [w, p] = counts(t);
        liveBadge(badge, w, p);
        card.classList.toggle('hot', w > 0);
        cta.replaceChildren(w > 0 ? 'Hoziroq bellashish' : 'Raqib topish', icon('right', 16));
      },
    };
    entry.paint();
    cards.set(t.id, entry);
    if (cardObserver) cardObserver.observe(card);
    return card;
  }

  function paintSummary() {
    if (!items.length) {
      summary.textContent = '';
      return;
    }
    summary.textContent = query
      ? `«${query}» boʻyicha ${total} ta mavzu topildi`
      : `${total} ta mavzu · ${items.length} tasi koʻrsatilmoqda`;
  }

  function paintMore() {
    if (error && items.length) {
      more.replaceChildren(h('div.alert.error', icon('wifiOff', 18), h('span', error),
        h('button.btn.ghost.sm', { type: 'button', onclick: () => loadMore(true) }, 'Qayta urinish')));
    } else if (loading && items.length) {
      more.replaceChildren(spinner('Yana yuklanmoqda…'));
    } else if (nextOffset != null && items.length) {
      more.replaceChildren(h('button.btn.ghost.block.browse-more-btn', { type: 'button', onclick: () => loadMore(true) },
        `Yana yuklash (${total - items.length})`));
    } else {
      more.replaceChildren();
    }
  }

  function paintEmpty() {
    if (error) {
      grid.replaceChildren(emptyState('wifiOff', 'Mavzularni yuklab boʻlmadi', error,
        h('button.btn.primary', { type: 'button', onclick: () => load(true) }, icon('refresh', 16), 'Qayta urinish')));
    } else if (query) {
      grid.replaceChildren(emptyState('search', 'Hech narsa topilmadi', `«${query}» boʻyicha mavzu yoʻq. Boshqa soʻz bilan qidirib koʻring.`,
        h('button.btn.ghost', { type: 'button', onclick: () => { search.value = ''; query = ''; load(true); } }, 'Qidiruvni tozalash')));
    } else {
      grid.replaceChildren(emptyState('file', 'Hozircha test mavzulari yoʻq',
        user.isAdmin ? 'Test faylini yuklang — u shu yerda paydo boʻladi.' : 'Administrator test faylini yuklaganidan keyin mavzular shu yerda paydo boʻladi.',
        user.isAdmin ? h('a.btn.primary', { href: '#/admin' }, icon('upload', 16), 'Test yuklash') : null));
    }
  }

  async function load(reset) {
    if (reset) {
      req += 1;
      items = [];
      total = 0;
      nextOffset = 0;
      error = null;
      cards.clear();
      visible.clear();
      if (cardObserver) cardObserver.disconnect();
      grid.replaceChildren(...skeletonCards(6));
      grid.setAttribute('aria-busy', 'true');
      summary.textContent = '';
    }
    if (nextOffset == null) return;
    const my = req;
    loading = true;
    paintMore();
    const qs = new URLSearchParams({ period, offset: String(nextOffset), limit: String(TOPICS_PAGE) });
    if (query) qs.set('q', query);
    try {
      const page = await api(`/api/topics/browse?${qs}`);
      if (my !== req) return;
      error = null;
      if (!items.length) grid.replaceChildren();
      total = page.total;
      nextOffset = page.nextOffset;
      const fresh = page.items.filter((t) => !cards.has(t.id));
      items = items.concat(fresh);
      grid.append(...fresh.map(makeCard));
      if (!items.length) paintEmpty();
    } catch (e) {
      if (my !== req) return;
      error = e.message || 'Tarmoq xatosi';
      if (!items.length) paintEmpty();
    } finally {
      if (my === req) {
        loading = false;
        grid.removeAttribute('aria-busy');
        paintSummary();
        paintMore();
      }
    }
  }

  function loadMore(force = false) {
    if (loading || nextOffset == null || !items.length) return;
    if (error && !force) return;
    error = null;
    load(false);
  }

  paintTabs();
  load(true);
  return {
    el,
    paintCounts() {
      for (const c of cards.values()) c.paint();
    },
    reload() {
      if (items.length <= TOPICS_PAGE) load(true); // foydalanuvchi pastga aylantirgan bo'lsa — joyini buzmaymiz
    },
    destroy() {
      onSearch.cancel();
      watchChanged.cancel();
      if (cardObserver) cardObserver.disconnect();
      if (moreObserver) moreObserver.disconnect();
      req += 1;
    },
  };
}
