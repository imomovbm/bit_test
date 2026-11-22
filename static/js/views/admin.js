// Boshqaruv paneli (faqat administratorlar uchun): umumiy ko'rinish, test mavzulari, savollar banki va foydalanuvchilar.
import { h, icon, avatar, toast, openModal, confirmDialog, promptDialog, readTextFile, copyText, spinner, emptyState, fmtDate, fmtAgo, pager, slicePage, LETTERS } from '../lib.js';
import { api } from '../api.js';
import { live } from '../live.js';
import { teamStyle } from '../balloon-scene.js';

const SECTIONS = [
  { id: 'overview', path: '/admin', icon: 'grid', label: 'Umumiy koʻrinish' },
  { id: 'topics', path: '/admin/topics', icon: 'file', label: 'Test mavzulari' },
  { id: 'bank', path: '/admin/bank', icon: 'database', label: 'Savollar banki' },
  { id: 'users', path: '/admin/users', icon: 'users', label: 'Foydalanuvchilar' },
];

const FORMAT_EXAMPLE = `Savol matni
====
Notoʻgʻri javob
====
#Toʻgʻri javob
====
Notoʻgʻri javob
++++
Keyingi savol matni
====
#Toʻgʻri javob
====
Notoʻgʻri javob`;

const DUEL_REASON = { score: 'koʻp toʻgʻri javob', time: 'tezroq', draw: 'durang', left: 'tark etildi', afk: 'javobsizlik', both_left: 'ikkalasi chiqdi' };

export function adminView(root, params, ctx, query) {
  if (!params.section && query.get('tab') === 'users') { // eski havola: #/admin?tab=users
    setTimeout(() => ctx.navigate('/admin/users'), 0);
    return null;
  }
  const section = SECTIONS.find((s) => s.id === (params.section || 'overview'));
  if (!section || (params.id && section.id !== 'topics')) {
    setTimeout(() => ctx.navigate('/admin'), 0);
    return null;
  }
  const counts = {};
  const nav = h('nav.adm-nav', { 'aria-label': 'Boshqaruv boʻlimlari' }, SECTIONS.map((s) => {
    counts[s.id] = h('span.adm-count');
    return h('a', { href: `#${s.path}`, class: `adm-link${s.id === section.id ? ' active' : ''}`, 'aria-current': s.id === section.id ? 'page' : null },
      icon(s.icon, 18), h('span', s.label), counts[s.id]);
  }));
  const body = h('div.adm-body');
  root.append(h('section.screen.adm',
    h('div.page-head', h('div',
      h('h1', 'Boshqaruv paneli'),
      h('p.muted', 'Faqat administratorlar uchun: test mavzularini yuklash, foydalanuvchilarni boshqarish va umumiy statistika.'))),
    h('div.adm-layout', nav, body)));

  const state = {
    alive: true,
    cleanups: [],
    overview: null,
    loadOverview() {
      state.overview = api('/api/admin/overview').then((data) => {
        if (state.alive) {
          counts.topics.textContent = String(data.stats.topics.total);
          counts.bank.textContent = String(data.stats.topics.questions);
          counts.users.textContent = String(data.stats.users.total);
        }
        return data;
      });
      state.overview.catch(() => {});
      return state.overview;
    },
  };
  state.loadOverview();
  if (params.id) topicEditor(body, ctx, state, Number(params.id));
  else ({ overview: overviewSection, topics: topicsSection, bank: bankSection, users: usersSection })[section.id](body, ctx, state, query);
  return () => {
    state.alive = false;
    state.cleanups.forEach((fn) => fn());
  };
}

// ================================================================ umumiy
function overviewSection(body, ctx, state) {
  body.append(h('div.card', spinner('Statistika yuklanmoqda…')));
  state.overview.then((data) => {
    if (!state.alive) return;
    const s = data.stats;
    const card = (ic, label, value, sub, cls = '') => h(`div.card.sum-card${cls ? `.${cls}` : ''}`,
      h('span.sum-ic', icon(ic, 18)),
      h('div', h('div.sum-value', String(value)), h('div.sum-label', label), sub ? h('div.small.muted', sub) : null));
    const users = [`+${s.users.newWeek} bu hafta`, `${s.users.admins} admin`, s.users.blocked ? `${s.users.blocked} bloklangan` : null].filter(Boolean).join(' · ');
    body.replaceChildren(
      h('div.sum-grid',
        card('users', 'foydalanuvchi', s.users.total, users),
        card('activity', 'hozir onlayn', s.users.online, 'saytni ochib turganlar', 'green'),
        card('file', 'test mavzusi', s.topics.total, `bankda ${s.topics.questions} ta savol`),
        card('swords', 'duel', s.duels.total, `${s.duels.week} ta bu hafta`, 'accent'),
        card('book', 'mashgʻulot', s.practice.total, `${s.practice.week} ta bu hafta`, 'green'),
        card('balloon', 'Balloon Pop oʻyini', s.balloon.total, s.balloon.active ? `${s.balloon.active} tasi davom etmoqda` : `${s.balloon.week} ta bu hafta`, 'accent')),
      h('div.card.adm-quick',
        h('div.adm-quick-actions',
          h('a.btn.primary', { href: '#/admin/topics' }, icon('upload', 16), 'Test yuklash'),
          h('a.btn.ghost', { href: '#/admin/bank' }, icon('database', 16), 'Savollar banki'),
          ctx.user.isSuperadmin ? h('a.btn.ghost', { href: '#/admin/users?new=1' }, icon('userPlus', 16), 'Foydalanuvchi qoʻshish') : null),
        registrationSwitch(data.settings.registrationOpen, !!ctx.user.isSuperadmin)),
      h('div.adm-grid2',
        h('div.card',
          h('div.card-title', icon('userPlus', 18), 'Yangi foydalanuvchilar', h('a.adm-more', { href: '#/admin/users' }, 'Barchasi', icon('right', 14))),
          data.recentUsers.length
            ? h('ul.adm-list', data.recentUsers.map((u) => h('li.adm-row',
              avatar(u.login, 'sm'),
              h('div.adm-row-main',
                h('div.adm-row-title', h('span.ellipsis', u.login), u.online ? h('span.live-dot', { title: 'onlayn' }) : null, roleBadge(u)),
                h('div.adm-row-sub', fmtAgo(u.createdAt))))))
            : h('p.muted.small', 'Hali foydalanuvchi yoʻq.')),
        h('div.card',
          h('div.card-title', icon('activity', 18), 'Soʻnggi faollik'),
          activityList(data))));
  }).catch((e) => {
    if (state.alive) body.replaceChildren(emptyState('wifiOff', 'Statistikani yuklab boʻlmadi', e.message));
  });
}

function activityList(data) {
  const items = [
    ...data.recentDuels.map((d) => ({ at: d.finishedAt, el: duelRow(d) })),
    ...data.recentGames.map((g) => ({ at: g.updatedAt, el: gameRow(g) })),
  ].sort((a, b) => b.at - a.at).slice(0, 8);
  if (!items.length) return h('p.muted.small', 'Hali duel yoki Balloon Pop oʻyini oʻtkazilmagan.');
  return h('ul.adm-list', items.map((x) => x.el));
}

function duelRow(d) {
  const [a, b] = d.players;
  const winner = d.winner === 1 ? a : d.winner === 2 ? b : null;
  return h('li.adm-row',
    h('span.adm-act-ic', icon('swords', 16)),
    h('div.adm-row-main',
      h('div.adm-row-title', h('span.ellipsis', `${a} — ${b}`), h('b.adm-score', `${d.score[0]}:${d.score[1]}`)),
      h('div.adm-row-sub', `Duel · ${d.topicName} · ${winner ? `${winner} gʻolib` : 'durang'} (${DUEL_REASON[d.reason] || d.reason}) · ${fmtAgo(d.finishedAt)}`)));
}

function gameRow(g) {
  const [t0, t1] = g.teams;
  const status = g.phase !== 'finished' ? 'davom etmoqda' : g.winner === null ? 'durang' : `${g.teams[g.winner].name} gʻolib`;
  return h('li.adm-row',
    h('span.adm-act-ic.balloon', icon('balloon', 16)),
    h('div.adm-row-main',
      h('div.adm-row-title',
        h('span.bp-team-label', { style: teamStyle(t0.color) }, h('span.bp-dot'), t0.name),
        h('b.adm-score', `${t0.left}:${t1.left}`),
        h('span.bp-team-label', { style: teamStyle(t1.color) }, h('span.bp-dot'), t1.name)),
      h('div.adm-row-sub', `Balloon Pop · ${g.owner || '—'} · ${g.topicName} · ${status} · ${fmtAgo(g.updatedAt)}`)));
}

function roleBadge(u) {
  if (u.blocked) return h('span.badge.bad', icon('lock', 11), 'bloklangan');
  if (u.isSuperadmin) return h('span.badge.owner', icon('crown', 11), 'bosh admin');
  if (u.isAdmin) return h('span.badge.admin', 'admin');
  return u.isTeacher ? h('span.badge.teacher', 'oʻqituvchi') : null;
}

/** Ro'yxatdan o'tish holati: bosh administrator uchun almashtirgich, boshqalar uchun faqat ma'lumot. */
function registrationSwitch(open, editable = true) {
  if (!editable) {
    return h('div.adm-reg.readonly',
      h('span.adm-reg-state', { class: open ? 'on' : 'off' }, icon(open ? 'unlock' : 'lock', 16)),
      h('span.adm-reg-text',
        h('b', open ? 'Roʻyxatdan oʻtish ochiq' : 'Roʻyxatdan oʻtish yopiq'),
        h('span.small.muted', 'Buni faqat bosh administrator oʻzgartira oladi.')));
  }
  const input = h('input', { type: 'checkbox', checked: open, 'aria-label': 'Roʻyxatdan oʻtish ochiq' });
  const hint = h('span.small.muted');
  const paint = () => {
    hint.textContent = input.checked
      ? 'Har kim oʻzi roʻyxatdan oʻta oladi.'
      : 'Yangi akkauntlarni faqat administrator yaratadi.';
  };
  paint();
  input.addEventListener('change', async () => {
    input.disabled = true;
    try {
      const res = await api('/api/admin/settings', { method: 'PATCH', body: { registrationOpen: input.checked } });
      input.checked = res.settings.registrationOpen;
      toast(input.checked ? 'Roʻyxatdan oʻtish ochildi' : 'Roʻyxatdan oʻtish yopildi', 'success');
    } catch (e) {
      input.checked = !input.checked;
      toast(e.message, 'error');
    } finally {
      input.disabled = false;
      paint();
    }
  });
  return h('label.adm-reg', h('span.switch', input, h('span.slider')), h('span.adm-reg-text', h('b', 'Roʻyxatdan oʻtish ochiq'), hint));
}

// ============================================================== mavzular
function topicsSection(body, ctx, state, query) {
  const input = h('input', { type: 'file', accept: '.txt,text/plain', multiple: true, hidden: true });
  const drop = h('label.dropzone',
    input,
    h('span.drop-ic', icon('upload', 28)),
    h('b', '.txt test faylini shu yerga tashlang yoki tanlash uchun bosing'),
    h('span.muted.small', 'Fayldagi savollar bilan yangi mavzu yaratiladi. Bir nechta faylni birdaniga tanlash mumkin — har biri alohida mavzu boʻladi.'));
  input.addEventListener('change', () => {
    const files = [...input.files];
    input.value = '';
    handleFiles(files);
  });
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.remove('over');
  }));
  drop.addEventListener('drop', (e) => handleFiles([...(e.dataTransfer?.files || [])]));

  const VIEWS = [['list', 'Barcha mavzular', 'file'], ['suggested', 'Oʻchirishga tavsiya', 'alert'], ['log', 'Jurnal', 'history']];
  let view = VIEWS.some(([k]) => k === query.get('view')) ? query.get('view') : 'list';
  const suggestCount = h('span.adm-filter-n');
  const tabs = h('div.adm-filters.adm-views', { role: 'tablist', 'aria-label': 'Mavzular boʻlimi' });
  const panel = h('div.adm-topics-panel');
  body.append(
    h('div.card.adm-quick',
      h('div.adm-reg-text', h('b', 'Mavzu yarating va savollarni qoʻlda qoʻshing'), h('span.small.muted', 'Yoki quyida .txt faylni yuklang — mavzu savollari bilan birga yaratiladi.')),
      h('button.btn.primary', { type: 'button', onclick: () => createTopic(ctx) }, icon('plus', 16), 'Yangi mavzu')),
    h('div.upload-grid',
      h('div.card', h('h2.card-title', icon('upload', 18), 'Fayldan yangi mavzu'), drop),
      h('div.card.format-card',
        h('h2.card-title', icon('file', 18), 'Fayl formati'),
        h('ul.format-rules',
          h('li', 'Savollar ', h('code', '++++'), ' bilan ajratiladi'),
          h('li', 'Savol va variantlar ', h('code', '===='), ' bilan ajratiladi'),
          h('li', 'Toʻgʻri javob oldiga ', h('code', '#'), ' qoʻyiladi')),
        h('pre.format-example', FORMAT_EXAMPLE))),
    tabs,
    panel);

  let current = null;
  function show(next) {
    view = next;
    tabs.replaceChildren(...VIEWS.map(([key, label, ic]) => h('button', {
      type: 'button',
      role: 'tab',
      class: `adm-filter${key === view ? ' active' : ''}`,
      'aria-selected': key === view ? 'true' : 'false',
      onclick: () => key !== view && show(key),
    }, icon(ic, 15), label, key === 'suggested' ? suggestCount : null)));
    if (current && current.destroy) current.destroy();
    panel.replaceChildren();
    const make = { list: topicActivityList, suggested: suggestedTopics, log: statusLog }[view];
    current = make(panel, { state, refresh: refreshSuggested });
  }

  async function refreshSuggested() {
    try {
      const data = await api('/api/admin/topic-activity/suggested?per=5');
      if (state.alive) suggestCount.textContent = data.total ? String(data.total) : '';
    } catch {
      /* hisoblagich — ixtiyoriy */
    }
  }

  async function handleFiles(files) {
    const txt = files.filter((f) => /\.txt$/i.test(f.name) || f.type === 'text/plain');
    if (!txt.length) {
      if (files.length) toast('Faqat .txt formatidagi fayllarni yuklash mumkin', 'error');
      return;
    }
    if (txt.length < files.length) toast('.txt boʻlmagan fayllar oʻtkazib yuborildi', 'warning');
    let saved = false;
    for (let i = 0; i < txt.length; i++) {
      const res = await reviewFile(txt[i], { k: i + 1, n: txt.length });
      if (res === 'saved') saved = true;
      if (res === 'stop') break;
    }
    if (saved && state.alive) {
      if (view === 'list') current.reload();
      else show('list');
      state.loadOverview();
    }
  }

  show(view);
  refreshSuggested();
  state.cleanups.push(() => current && current.destroy && current.destroy());
}

// ------------------------------------------- mavzular faolligi (server tomonida)
const TOPIC_COLUMNS = [
  // [saralash kaliti, sarlavha, ustun klassi]
  ['name', 'Mavzu', 'adm-th-main'],
  ['status', 'Holat', ''],
  ['lastPlayed', 'Oxirgi oʻyin', ''],
  ['total', 'Jami duel', 'num'],
  ['recent', '30 kunda', 'num'],
];
// telefonda jadval sarlavhasi yashiriladi — saralash ro'yxatdan tanlanadi
const SORT_OPTIONS = [
  ['name:asc', 'Saralash: nomi (A–Z)'],
  ['lastPlayed:desc', 'Oxirgi oʻyin: yangilari'],
  ['lastPlayed:asc', 'Oxirgi oʻyin: eskilari'],
  ['total:desc', 'Jami duel: koʻpi'],
  ['recent:desc', '30 kunda: koʻpi'],
  ['recent:asc', '30 kunda: kami'],
  ['status:asc', 'Holat: yopiqlari oldin'],
  ['created:desc', 'Yangi qoʻshilganlar'],
];
const IDLE_OPTIONS = [[0, 'Oxirgi oʻyin: istalgan'], [30, '30+ kun oʻynalmagan'], [60, '60+ kun oʻynalmagan'], [90, '90+ kun oʻynalmagan'], [180, '180+ kun oʻynalmagan']];
const LOG_REASON = { manual: 'qoʻlda', bulk: 'ommaviy', suggested: 'tavsiya boʻyicha' };
const TOPICS_PER = 25;

function reasonLabel(reason) {
  if (reason && reason.startsWith('auto:')) return `avtomatik (${reason.slice(5)} kun)`;
  return LOG_REASON[reason] || reason || '—';
}

function lastPlayedCell(t) {
  if (!t.lastPlayedAt) return h('span.muted', 'hech oʻynalmagan');
  return h('span', { title: fmtDate(t.lastPlayedAt) }, fmtAgo(t.lastPlayedAt));
}

function liveNote(t) {
  if (!t.waiting && !t.playing) return null;
  return h('span.adm-live', h('span.pulse-dot'), [t.waiting ? `${t.waiting} kutmoqda` : '', t.playing ? `${t.playing} duel` : ''].filter(Boolean).join(' · '));
}

/** Ko'plab mavzuni yopish/ochish (soni bilan tasdiqlash). Muvaffaqiyatli bo'lsa — o'zgargan mavzular soni. */
async function bulkStatus(ids, active, source) {
  const n = ids.length;
  const ok = await confirmDialog({
    title: active ? 'Mavzularni ochish' : 'Mavzularni yopish',
    message: active
      ? `${n} ta mavzu yana foydalanuvchilarga ochiladi.`
      : `${n} ta mavzu yopiladi: bosh sahifa va lobbida koʻrinmaydi, ulardagi kutishlar bekor qilinadi, boshlangan duellar oxirigacha davom etadi. Savollar va tarix saqlanadi — istalgan vaqtda qayta ochish mumkin.`,
    okText: active ? `${n} ta mavzuni ochish` : `${n} ta mavzuni yopish`,
    danger: !active,
  });
  if (!ok) return null;
  try {
    const res = await api('/api/admin/topic-activity/status', { method: 'POST', body: { ids, active, source } });
    toast(active ? `${res.changed} ta mavzu ochildi` : `${res.changed} ta mavzu yopildi`, 'success');
    return res.changed;
  } catch (e) {
    toast(e.message, 'error');
    return null;
  }
}

function sortHeader(key, label, cls, sort, onSort) {
  const activeSort = sort.key === key;
  return h(`th${cls ? `.${cls}` : ''}`, { 'aria-sort': activeSort ? (sort.desc ? 'descending' : 'ascending') : null },
    h('button.th-sort', { type: 'button', onclick: () => onSort(key), title: `${label} boʻyicha saralash` },
      label, h('span.th-arrow', { 'aria-hidden': 'true' }, activeSort ? (sort.desc ? '↓' : '↑') : '↕')));
}

function topicActivityList(panel, { state, refresh }) {
  const params = { status: 'all', q: '', idle: 0, page: 1 };
  const sort = { key: 'name', desc: false };
  const selected = new Map(); // id -> {id, name, active} (sahifalar orasida saqlanadi)
  let data = null;
  let req = 0;
  let searchTimer = 0;

  const search = searchBox('Mavzu nomi boʻyicha qidirish', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      if (search.value() === params.q) return;
      params.q = search.value();
      params.page = 1;
      load();
    }, 300);
  });
  const statusTabs = h('div.adm-filters', { role: 'group', 'aria-label': 'Holat' });
  const idle = h('select.adm-select', { 'aria-label': 'Oʻynalmagan muddat', onchange: () => { params.idle = Number(idle.value); params.page = 1; load(); } },
    IDLE_OPTIONS.map(([v, label]) => h('option', { value: String(v) }, label)));
  const sortSelect = h('select.adm-select.adm-sort-sm', {
    'aria-label': 'Saralash',
    onchange: () => {
      const [key, dir] = sortSelect.value.split(':');
      sort.key = key;
      sort.desc = dir === 'desc';
      params.page = 1;
      load();
    },
  });
  const selbar = h('div.bank-selbar.adm-selbar');
  const list = h('div', spinner());
  panel.append(
    h('div.adm-toolbar', search.el, statusTabs, idle, sortSelect,
      h('button.btn.ghost.sm', { type: 'button', onclick: () => load() }, icon('refresh', 16), 'Yangilash')),
    selbar,
    list);

  function paintStatusTabs() {
    const c = data ? data.counts : { active: 0, inactive: 0 };
    const items = [['all', 'Hammasi', c.active + c.inactive], ['active', 'Faol', c.active], ['inactive', 'Yopiq', c.inactive]];
    statusTabs.replaceChildren(...items.map(([key, label, n]) => h('button', {
      type: 'button',
      class: `adm-filter${params.status === key ? ' active' : ''}`,
      'aria-pressed': params.status === key ? 'true' : 'false',
      onclick: () => {
        if (params.status === key) return;
        params.status = key;
        params.page = 1;
        load();
      },
    }, label, data ? h('span.adm-filter-n', String(n)) : null)));
  }

  function paintSelbar() {
    if (!selected.size) {
      selbar.replaceChildren();
      selbar.classList.remove('has-sel');
      return;
    }
    const all = [...selected.values()];
    const toClose = all.filter((t) => t.active).map((t) => t.id);
    const toOpen = all.filter((t) => !t.active).map((t) => t.id);
    selbar.classList.add('has-sel');
    selbar.replaceChildren(
      h('b.bank-sel-n', `${selected.size} ta mavzu tanlandi`),
      h('div.bank-sel-actions',
        toClose.length ? h('button.btn.danger.sm', { type: 'button', onclick: () => bulk(toClose, false) }, icon('lock', 15), `Yopish (${toClose.length})`) : null,
        toOpen.length ? h('button.btn.ghost.sm', { type: 'button', onclick: () => bulk(toOpen, true) }, icon('unlock', 15), `Ochish (${toOpen.length})`) : null,
        h('button.btn.ghost.sm', { type: 'button', onclick: () => { selected.clear(); paint(); } }, icon('x', 15), 'Bekor qilish')));
  }

  async function bulk(ids, active) {
    const changed = await bulkStatus(ids, active, 'bulk');
    if (changed === null) return;
    selected.clear();
    load();
    refresh();
    state.loadOverview();
  }

  async function load() {
    const my = ++req;
    const qs = new URLSearchParams({ status: params.status, idle: String(params.idle), sort: sort.key, dir: sort.desc ? 'desc' : 'asc', page: String(params.page), per: String(TOPICS_PER) });
    if (params.q) qs.set('q', params.q);
    list.setAttribute('aria-busy', 'true');
    if (!data) list.replaceChildren(spinner());
    try {
      const res = await api(`/api/admin/topic-activity?${qs}`);
      if (my !== req || !state.alive) return;
      data = res;
      if (params.page > res.pages) {
        params.page = res.pages;
        load();
        return;
      }
      paint();
    } catch (e) {
      if (my !== req || !state.alive) return;
      list.replaceChildren(emptyState('wifiOff', 'Roʻyxatni yuklab boʻlmadi', e.message,
        h('button.btn.primary', { type: 'button', onclick: () => load() }, icon('refresh', 16), 'Qayta urinish')));
    } finally {
      if (my === req) list.removeAttribute('aria-busy');
    }
  }

  function onSort(key) {
    if (sort.key === key) sort.desc = !sort.desc;
    else {
      sort.key = key;
      sort.desc = key !== 'name' && key !== 'status'; // sonlar va sanalar — avval kattasi/yangisi
    }
    params.page = 1;
    load();
  }

  function paintSort() {
    const value = `${sort.key}:${sort.desc ? 'desc' : 'asc'}`;
    const opts = SORT_OPTIONS.some(([v]) => v === value) ? SORT_OPTIONS : [[value, `Saralash: ${value}`], ...SORT_OPTIONS];
    sortSelect.replaceChildren(...opts.map(([v, label]) => h('option', { value: v }, label)));
    sortSelect.value = value;
  }

  function paint() {
    paintStatusTabs();
    paintSelbar();
    paintSort();
    if (!data) return;
    if (!data.total) {
      const filtered = params.q || params.idle || params.status !== 'all';
      list.replaceChildren(filtered
        ? h('div.card.muted.center', 'Bu shartlarga mos mavzu topilmadi.')
        : emptyState('file', 'Hali mavzu yoʻq', 'Yuqoridagi maydon orqali birinchi test faylini yuklang.'));
      return;
    }
    const pageIds = data.items.map((t) => t.id);
    const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
    const checkAll = h('input', {
      type: 'checkbox', checked: allOnPage, 'aria-label': 'Sahifadagi hammasini tanlash',
      onchange: () => {
        for (const t of data.items) {
          if (checkAll.checked) selected.set(t.id, { id: t.id, name: t.name, active: t.active });
          else selected.delete(t.id);
        }
        paint();
      },
    });
    const first = (data.page - 1) * data.per + 1;
    list.replaceChildren(
      h('p.small.muted.adm-summary', `${data.total} ta mavzu · ${first}–${first + data.items.length - 1} koʻrsatilmoqda`),
      h('div.card.table-card', h('div.table-wrap', h('table.table.adm-table.adm-topics.adm-activity-table',
        h('thead', h('tr',
          h('th.adm-th-check', h('label.bank-check.bank-check-all', checkAll)),
          ...TOPIC_COLUMNS.map(([key, label, cls]) => sortHeader(key, label, cls, sort, onSort)),
          h('th.right', 'Amallar'))),
        h('tbody', data.items.map(row))))),
      pager({ page: data.page, pages: data.pages, total: data.total, per: data.per, onChange: (p) => { params.page = p; load(); scrollToTop(list); } }));
  }

  function row(t) {
    const check = h('input', {
      type: 'checkbox', checked: selected.has(t.id), 'aria-label': `Tanlash: ${t.name}`,
      onchange: () => {
        if (check.checked) selected.set(t.id, { id: t.id, name: t.name, active: t.active });
        else selected.delete(t.id);
        paint();
      },
    });
    const href = `#/admin/topics/${t.id}`;
    return h(`tr${t.active ? '' : '.is-inactive'}${selected.has(t.id) ? '.is-selected' : ''}`,
      h('td.adm-td-check', h('label.bank-check', check)),
      h('td.adm-td-main', h('div.topic-cell',
        h('a.adm-topic-link', { href }, t.name),
        h('span.small.muted', t.questionCount ? `${t.questionCount} ta savol · ${t.sourceFile || 'qoʻlda kiritilgan'}` : 'savol qoʻshilmagan'),
        liveNote(t))),
      h('td.adm-td-role', activeSwitch(t, () => {
        selected.delete(t.id);
        load();
        refresh();
      })),
      h('td.adm-td-played.small.nowrap', h('span.adm-sm-only', 'oxirgi oʻyin: '), lastPlayedCell(t)),
      h('td.num.adm-td-count', String(t.totalDuels), h('span.adm-sm-only', ' ta duel')),
      h('td.num.adm-td-count', String(t.duels30), h('span.adm-sm-only', ' ta 30 kunda')),
      h('td.right.nowrap.adm-td-actions',
        h('a.icon-btn', { href, title: 'Savollarni boshqarish', 'aria-label': `Savollarni boshqarish: ${t.name}` }, icon('edit', 17)),
        h('a.icon-btn', { href: `/api/admin/topics/${t.id}/export`, download: `${t.name}.txt`, title: '.txt fayl sifatida yuklab olish', 'aria-label': 'Yuklab olish' }, icon('download', 17)),
        h('button.icon-btn.danger', { type: 'button', title: 'Oʻchirish', 'aria-label': `Oʻchirish: ${t.name}`, onclick: () => remove(t) }, icon('trash', 17))));
  }

  async function remove(t) {
    const ok = await confirmDialog({
      title: 'Mavzuni oʻchirish',
      message: `«${t.name}» mavzusi butunlay oʻchiriladi. Undagi ${t.questionCount} ta savol savollar bankida qoladi — ularni boshqa mavzularga qoʻshish mumkin. Duel va oʻyinlar tarixi ham saqlanadi. Vaqtincha yashirish uchun oʻchirish oʻrniga «Holat» tugmasi bilan yoping.`,
      okText: 'Oʻchirish',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/admin/topics/${t.id}`, { method: 'DELETE' });
      toast('Mavzu oʻchirildi', 'success');
      selected.delete(t.id);
      load();
      refresh();
      state.loadOverview();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  paintStatusTabs();
  load();
  return { reload: load, destroy: () => clearTimeout(searchTimer) };
}

function suggestedTopics(panel, { state, refresh }) {
  let days = null;
  let page = 1;
  let data = null;
  let settings = null;
  let req = 0;
  const daysInput = h('input.adm-days', { type: 'number', min: '1', max: '3650', step: '1', inputmode: 'numeric', 'aria-label': 'Kunlar soni' });
  const intro = h('div.card.adm-suggest-head',
    h('h2.card-title', icon('alert', 18), 'Oʻchirishga tavsiya etilgan mavzular'),
    h('p.small.muted', 'Faol, lekin uzoq vaqtdan beri hech kim oʻynamagan mavzular (hech oʻynalmaganlari uchun yaratilgan sana hisobga olinadi). ',
      'Yopish yumshoq: mavzu bosh sahifa va lobbidan yashiriladi, savollar va tarix saqlanadi, istalgan vaqtda qayta ochish mumkin. Hech narsa avtomatik yopilmaydi (quyidagi sozlama yoqilmagan boʻlsa).'),
    h('form.adm-days-row', {
      onsubmit: (e) => {
        e.preventDefault();
        const v = Number(daysInput.value);
        if (!Number.isInteger(v) || v < 1 || v > 3650) {
          toast('Kunlar soni 1 dan 3650 gacha boʻlishi kerak', 'error');
          return;
        }
        days = v;
        page = 1;
        load();
      },
    },
    h('label.adm-days-label', 'Oʻynalmaganiga kamida', daysInput, 'kun'),
    h('button.btn.primary.sm', { type: 'submit' }, 'Koʻrsatish'),
    h('button.link-btn', { type: 'button', onclick: saveDefault }, 'Standart qilib saqlash')));
  const summary = h('div.adm-suggest-summary');
  const list = h('div', spinner());
  const auto = h('div.card.adm-auto');
  panel.append(intro, summary, list, auto);

  async function saveDefault() {
    const v = Number(daysInput.value);
    if (!Number.isInteger(v) || v < 1 || v > 3650) {
      toast('Kunlar soni 1 dan 3650 gacha boʻlishi kerak', 'error');
      return;
    }
    try {
      const res = await api('/api/admin/topic-activity/settings', { method: 'PATCH', body: { suggestDays: v } });
      settings = res.settings;
      toast(`Tavsiya chegarasi: ${v} kun`, 'success');
      days = v;
      load();
      refresh();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function load() {
    const my = ++req;
    const qs = new URLSearchParams({ page: String(page), per: String(TOPICS_PER) });
    if (days) qs.set('days', String(days));
    list.setAttribute('aria-busy', 'true');
    try {
      const [res, s] = await Promise.all([
        api(`/api/admin/topic-activity/suggested?${qs}`),
        settings ? Promise.resolve(null) : api('/api/admin/topic-activity?per=5'),
      ]);
      if (my !== req || !state.alive) return;
      data = res;
      if (s) settings = s.settings;
      if (days == null) {
        days = res.days;
        daysInput.value = String(days);
      }
      paint();
      paintAuto();
    } catch (e) {
      if (my !== req || !state.alive) return;
      list.replaceChildren(emptyState('wifiOff', 'Roʻyxatni yuklab boʻlmadi', e.message,
        h('button.btn.primary', { type: 'button', onclick: () => load() }, icon('refresh', 16), 'Qayta urinish')));
    } finally {
      if (my === req) list.removeAttribute('aria-busy');
    }
  }

  async function deactivateAll() {
    let ids;
    try {
      ids = (await api(`/api/admin/topic-activity/suggested/ids?days=${days}`)).ids;
    } catch (e) {
      toast(e.message, 'error');
      return;
    }
    if (!ids.length) {
      load();
      return;
    }
    const changed = await bulkStatus(ids, false, 'suggested');
    if (changed === null) return;
    page = 1;
    load();
    refresh();
    state.loadOverview();
  }

  async function deactivateOne(t, btn) {
    btn.disabled = true;
    try {
      await api('/api/admin/topic-activity/status', { method: 'POST', body: { ids: [t.id], active: false, source: 'suggested' } });
      toast(`«${t.name}» yopildi — «Jurnal» va «Barcha mavzular»dan qayta ochish mumkin`, 'success');
      load();
      refresh();
      state.loadOverview();
    } catch (e) {
      btn.disabled = false;
      toast(e.message, 'error');
    }
  }

  function paint() {
    if (!data.total) {
      summary.replaceChildren();
      list.replaceChildren(emptyState('check', 'Tavsiya yoʻq', `Barcha faol mavzular oxirgi ${days} kun ichida oʻynalgan.`));
      return;
    }
    summary.replaceChildren(
      h('p', h('b', `${data.total} ta faol mavzu`), ` ${days} kundan beri oʻynalmagan`),
      h('button.btn.danger', { type: 'button', onclick: deactivateAll }, icon('lock', 16), `Hammasini yopish (${data.total})`));
    list.replaceChildren(
      h('div.card.table-card', h('div.table-wrap', h('table.table.adm-table.adm-suggest-table',
        h('thead', h('tr', h('th', 'Mavzu'), h('th', 'Oxirgi oʻyin'), h('th.num', 'Jami duel'), h('th.num.hide-sm', 'Savollar'), h('th.right', 'Amal'))),
        h('tbody', data.items.map((t) => {
          const btn = h('button.btn.ghost.sm.adm-close-btn', { type: 'button' }, icon('lock', 15), 'Yopish');
          btn.addEventListener('click', () => deactivateOne(t, btn));
          return h('tr',
            h('td.adm-td-main', h('div.topic-cell', h('a.adm-topic-link', { href: `#/admin/topics/${t.id}` }, t.name),
              h('span.small.muted', `yaratilgan: ${fmtDate(t.createdAt)}`), liveNote(t))),
            h('td.adm-td-played.small.nowrap', h('span.adm-sm-only', 'oxirgi oʻyin: '), lastPlayedCell(t)),
            h('td.num.adm-td-count', String(t.totalDuels), h('span.adm-sm-only', ' ta duel')),
            h('td.num.hide-sm', String(t.questionCount)),
            h('td.right', btn));
        }))))),
      pager({ page: data.page, pages: data.pages, total: data.total, per: data.per, onChange: (p) => { page = p; load(); scrollToTop(list); } }));
  }

  function paintAuto() {
    if (!settings) return;
    const on = settings.autoDeactivateDays > 0;
    const toggle = h('input', { type: 'checkbox', checked: on, 'aria-label': 'Avtomatik yopish' });
    const autoDays = h('input.adm-days', { type: 'number', min: '7', max: '3650', step: '1', inputmode: 'numeric', value: String(on ? settings.autoDeactivateDays : 180), 'aria-label': 'Avtomatik yopish chegarasi (kun)', disabled: !on });
    toggle.addEventListener('change', () => {
      autoDays.disabled = !toggle.checked;
      if (!toggle.checked) save(0);
    });
    async function save(value) {
      try {
        const res = await api('/api/admin/topic-activity/settings', { method: 'PATCH', body: { autoDeactivateDays: value } });
        settings = res.settings;
        toast(value ? `Avtomatik yopish yoqildi: ${value} kundan beri oʻynalmagan mavzular` : 'Avtomatik yopish oʻchirildi', 'success');
      } catch (e) {
        toast(e.message, 'error');
      }
      paintAuto();
    }
    auto.replaceChildren(
      h('div.adm-reg-text',
        h('b', 'Avtomatik yopish'),
        h('span.small.muted', on
          ? `Yoqilgan: ${settings.autoDeactivateDays} kundan beri oʻynalmagan faol mavzular har soatda avtomatik yopiladi va jurnalga yoziladi.`
          : 'Oʻchiq (standart). Yoqilsa, belgilangan kundan beri oʻynalmagan faol mavzular har soatda avtomatik yopiladi va jurnalga yoziladi.')),
      h('form.adm-days-row', {
        onsubmit: (e) => {
          e.preventDefault();
          const v = Number(autoDays.value);
          if (!Number.isInteger(v) || v < 7 || v > 3650) {
            toast('Avtomatik yopish uchun 7 dan 3650 gacha kun kiriting', 'error');
            return;
          }
          save(v);
        },
      },
      h('label.switch', toggle, h('span.slider'), h('span.small', 'yoqish')),
      h('label.adm-days-label', autoDays, 'kun'),
      h('button.btn.ghost.sm', { type: 'submit', disabled: !on && !toggle.checked }, 'Saqlash')));
    toggle.addEventListener('change', () => {
      auto.querySelector('button[type="submit"]').disabled = !toggle.checked;
    });
  }

  load();
  return { reload: load };
}

function statusLog(panel, { state }) {
  let page = 1;
  let req = 0;
  const list = h('div', spinner());
  panel.append(
    h('p.small.muted.adm-summary', 'Mavzular holatining har bir oʻzgarishi: kim, qachon va qanday sabab bilan yopgan yoki ochgan.'),
    list);

  async function load() {
    const my = ++req;
    try {
      const data = await api(`/api/admin/topic-activity/log?page=${page}&per=${TOPICS_PER}`);
      if (my !== req || !state.alive) return;
      if (!data.total) {
        list.replaceChildren(emptyState('history', 'Jurnal boʻsh', 'Mavzu yopilganda yoki ochilganda shu yerda yozuv paydo boʻladi.'));
        return;
      }
      list.replaceChildren(
        h('div.card.table-card', h('div.table-wrap', h('table.table.adm-table.adm-log-table',
          h('thead', h('tr', h('th', 'Vaqt'), h('th', 'Mavzu'), h('th', 'Amal'), h('th', 'Kim'), h('th', 'Sabab'))),
          h('tbody', data.items.map((e) => h('tr',
            h('td.small.nowrap.adm-td-time', fmtDate(e.at)),
            h('td.adm-td-main', h('a.adm-topic-link', { href: `#/admin/topics/${e.topicId}` }, e.topicName)),
            h('td', e.active ? h('span.badge.good', icon('unlock', 11), 'ochildi') : h('span.badge.bad', icon('lock', 11), 'yopildi')),
            h('td.small', e.by || h('span.muted', 'tizim')),
            h('td.small.muted', reasonLabel(e.reason)))))))),
        pager({ page: data.page, pages: data.pages, total: data.total, per: data.per, onChange: (p) => { page = p; load(); scrollToTop(list); } }));
    } catch (e) {
      if (my !== req || !state.alive) return;
      list.replaceChildren(emptyState('wifiOff', 'Jurnalni yuklab boʻlmadi', e.message,
        h('button.btn.primary', { type: 'button', onclick: () => load() }, icon('refresh', 16), 'Qayta urinish')));
    }
  }

  load();
  return { reload: load };
}

function suggestName(fileName) {
  return fileName.replace(/\.txt$/i, '').replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120);
}

function questionPreview(q, i) {
  return h('li.preview-q',
    h('div.preview-text', h('span.review-n', String(i + 1)), h('span', q.text)),
    h('ul.review-opts', q.options.map((o, j) => h('li', { class: j === q.correct ? 'is-correct' : '' }, h('span.opt-key.sm', LETTERS[j]), h('span.review-opt', o)))));
}

/**
 * Faylni tekshirib ko'rsatadi va saqlaydi: yangi mavzu (nom so'raladi) yoki mavjud mavzuni almashtirish (opts.replace).
 * Natija: 'saved' | 'skip' | 'stop'.
 */
async function reviewFile(file, { k = 1, n = 1, replace = null, append = null, bank = null } = {}) {
  const target = replace || append || bank; // yangi mavzu yaratilmaydi
  let text;
  try {
    text = await readTextFile(file);
  } catch {
    toast(`${file.name}: faylni oʻqib boʻlmadi`, 'error');
    return 'skip';
  }
  let parsed;
  try {
    parsed = await api('/api/admin/topics/parse', { method: 'POST', body: { content: text } });
  } catch (e) {
    toast(`${file.name}: ${e.message}`, 'error');
    return 'skip';
  }

  return new Promise((resolve) => {
    let result = 'skip';
    const nameInput = h('input', { type: 'text', value: suggestName(file.name), maxlength: 120, placeholder: 'Masalan: Dasturiy taʼminotni testlash' });
    const shuffle = h('input', { type: 'checkbox', checked: true });
    const bankTopic = bank ? topicSelect(bank.topics, bank.preset, '— faqat bankka —') : null;
    const err = h('div.alert.error', { hidden: true });
    const errorsBlock = parsed.errorCount
      ? h('details.parse-errors', { open: parsed.count === 0 },
        h('summary', icon('alert', 16), `${parsed.errorCount} ta savolda xato bor — ular saqlanmaydi`),
        h('ul', parsed.errors.map((e) => h('li', h('b', `${e.n}-savol: `), e.message, h('div.small.muted', e.snippet)))))
      : null;
    const body = [
      h('div.file-line', icon('file', 18), h('b', file.name), h('span.muted.small', `${(file.size / 1024).toFixed(1)} KB`)),
      parsed.count
        ? h('div.alert.success', icon('check', 18), h('span', h('b', `${parsed.count} ta savol`), ' muvaffaqiyatli oʻqildi.'))
        : h('div.alert.error', icon('alert', 18), h('span', 'Faylda yaroqli savol topilmadi. Fayl formatini tekshiring.')),
      replace && parsed.count
        ? h('div.alert.warning', icon('refresh', 18), h('span', `«${replace.name}» mavzusidagi ${replace.questionCount} ta savol shu fayldagi ${parsed.count} ta savol bilan almashtiriladi. Eski savollar bankda qoladi; mavzu nomi, sozlamalari va oʻyinlar tarixi saqlanadi.`))
        : null,
      append && parsed.count
        ? h('div.alert.info', icon('plus', 18), h('span', `${parsed.count} ta savol «${append.name}» mavzusi oxiriga qoʻshiladi (hozir ${append.questionCount} ta).`))
        : null,
      bank && parsed.count
        ? h('div.alert.info', icon('database', 18), h('span', 'Savollar bankka alohida-alohida yoziladi. Bankda allaqachon bor savollar takrorlanmaydi.'))
        : null,
      bank && parsed.count && bank.topics.length
        ? h('label.field', h('span.field-label', 'Mavzuga ham qoʻshish (ixtiyoriy)'), bankTopic, h('span.field-hint', 'Keyin ham bank sahifasida savollarni belgilab istalgan mavzuga qoʻshish mumkin.'))
        : null,
      errorsBlock,
      parsed.preview.length
        ? h('details.preview', h('summary', icon('eye', 16), `Dastlabki ${parsed.preview.length} ta savolni koʻrish`), h('ol.preview-list', parsed.preview.map(questionPreview)))
        : null,
      !target && parsed.count ? h('label.field', h('span.field-label', 'Mavzu nomi'), nameInput, h('span.field-hint', 'Bu nom duel, oʻrganish va Balloon Pop boʻlimlarida koʻrinadi.')) : null,
      !target && parsed.count ? h('label.check', shuffle, h('span', 'Javob variantlari tartibini har safar aralashtirish')) : null,
      err,
    ];
    const save = async (m) => {
      err.hidden = true;
      try {
        if (replace) {
          const res = await api(`/api/admin/topics/${replace.id}/content`, { method: 'PUT', body: { content: text, fileName: file.name } });
          toast(`«${res.topic.name}» yangilandi — ${res.topic.questionCount} ta savol`, 'success', 5000);
        } else if (append) {
          const res = await api(`/api/admin/topics/${append.id}/append`, { method: 'POST', body: { content: text, fileName: file.name } });
          const had = parsed.count - res.added;
          toast(`${res.added} ta savol qoʻshildi — jami ${res.topic.questionCount} ta${had ? ` (${had} tasi mavzuda bor edi)` : ''}`, 'success', 5000);
        } else if (bank) {
          const tid = Number(bankTopic.value) || null;
          const res = await api('/api/admin/bank/upload', { method: 'POST', body: { content: text, fileName: file.name, topicIds: tid ? [tid] : [] } });
          const name = tid ? bank.topics.find((t) => t.id === tid)?.name : null;
          const head = res.created
            ? `Bankka ${res.created} ta yangi savol qoʻshildi${res.reused ? ` (${res.reused} tasi bankda bor edi)` : ''}`
            : `Fayldagi ${res.reused} ta savol bankda allaqachon bor — takrorlanmadi`;
          toast(`${head}${name ? ` · «${name}» mavzusiga biriktirildi` : ''}`, res.created ? 'success' : 'info', 6000);
        } else {
          const name = nameInput.value.trim();
          if (!name) {
            err.textContent = 'Mavzu nomini kiriting';
            err.hidden = false;
            nameInput.focus();
            return;
          }
          const res = await api('/api/admin/topics', { method: 'POST', body: { name, content: text, shuffle: shuffle.checked, fileName: file.name } });
          toast(`«${res.topic.name}» saqlandi — ${res.topic.questionCount} ta savol`, 'success', 5000);
        }
        result = 'saved';
        m.close();
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
        if (!target) nameInput.focus();
      }
    };
    const many = n > 1 && k < n;
    const modal = openModal({
      title: replace ? `Mavzuni yangilash: ${replace.name}` : append ? `Savollar qoʻshish: ${append.name}` : bank ? `Bankka yuklash${n > 1 ? ` (${k}/${n})` : ''}` : n > 1 ? `Yangi mavzu (${k}/${n})` : 'Yangi mavzu',
      body,
      wide: true,
      onClose: () => resolve(result),
      actions: [
        many ? { text: 'Hammasini bekor qilish', onClick: (m) => { result = 'stop'; m.close(); } } : null,
        { text: many ? 'Bu faylni oʻtkazish' : 'Bekor qilish' },
        parsed.count ? { text: replace ? 'Almashtirish' : append || bank ? 'Qoʻshish' : 'Saqlash', kind: 'primary', icon: 'check', onClick: save } : null,
      ],
    });
    nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        save(modal);
      }
    });
    if (!target) setTimeout(() => nameInput.select(), 60);
  });
}

/** Mavzuni faol/nofaol qilish: nofaol mavzu foydalanuvchilarga ko'rinmaydi (duel, o'rganish, Balloon Pop). */
function activeSwitch(t, onChange) {
  const input = h('input', { type: 'checkbox', checked: t.active, 'aria-label': `Faol: ${t.name}` });
  const text = h('span.small');
  const paint = () => {
    text.textContent = input.checked ? 'faol' : 'yopiq';
    text.className = `small ${input.checked ? 'adm-on' : 'adm-off'}`;
  };
  paint();
  input.addEventListener('change', async () => {
    input.disabled = true;
    try {
      const res = await api(`/api/admin/topics/${t.id}`, { method: 'PATCH', body: { active: input.checked } });
      t.active = res.topic.active;
      toast(t.active ? `«${t.name}» foydalanuvchilarga ochildi` : `«${t.name}» yopildi — foydalanuvchilarga koʻrinmaydi`, 'success');
      if (onChange) onChange(t);
    } catch (e) {
      input.checked = !input.checked;
      toast(e.message, 'error');
    } finally {
      input.disabled = false;
      paint();
    }
  });
  return h('label.switch', { title: 'Faol mavzular foydalanuvchilarga koʻrinadi' }, input, h('span.slider'), text);
}

function createTopic(ctx) {
  const name = h('input', { type: 'text', maxlength: 120, placeholder: 'Masalan: Dasturiy taʼminotni testlash' });
  const shuffle = h('input', { type: 'checkbox', checked: true });
  const err = h('div.field-error');
  const submit = async (m) => {
    err.textContent = '';
    if (!name.value.trim()) {
      err.textContent = 'Mavzu nomini kiriting';
      name.focus();
      return;
    }
    try {
      const res = await api('/api/admin/topics', { method: 'POST', body: { name: name.value.trim(), shuffle: shuffle.checked } });
      m.close();
      toast(`«${res.topic.name}» yaratildi — endi savollar qoʻshing`, 'success');
      ctx.navigate(`/admin/topics/${res.topic.id}`);
    } catch (e) {
      err.textContent = e.message;
      name.focus();
    }
  };
  const m = openModal({
    title: 'Yangi mavzu',
    body: [
      h('label.field', h('span.field-label', 'Mavzu nomi'), name, h('span.field-hint', 'Savollarni keyingi sahifada qoʻlda yoki fayldan qoʻshasiz.')),
      h('label.check', shuffle, h('span', 'Javob variantlari tartibini har safar aralashtirish')),
      err,
    ],
    actions: [{ text: 'Bekor qilish' }, { text: 'Yaratish', kind: 'primary', icon: 'plus', onClick: submit }],
  });
  name.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit(m);
    }
  });
  setTimeout(() => name.focus(), 60);
}

// ========================================================= mavzu sahifasi
function topicEditor(body, ctx, state, tid) {
  let topic = null;
  let questions = null;
  let page = 1;
  const head = h('div');
  const search = searchBox('Savol yoki variant matni boʻyicha qidirish', () => {
    page = 1;
    paint();
  });
  const list = h('div', spinner('Savollar yuklanmoqda…'));
  const fileInput = (onFile) => {
    const input = h('input', { type: 'file', accept: '.txt,text/plain', hidden: true });
    input.addEventListener('change', () => {
      const file = input.files[0];
      input.value = '';
      if (file) onFile(file);
    });
    return input;
  };
  const appendInput = fileInput(async (file) => {
    if ((await reviewFile(file, { append: topic })) === 'saved') reload();
  });
  const replaceInput = fileInput(async (file) => {
    if ((await reviewFile(file, { replace: topic })) === 'saved') reload();
  });
  body.append(
    h('a.back-link.adm-back', { href: '#/admin/topics' }, icon('left', 16), 'Barcha mavzular'),
    head,
    h('div.adm-toolbar', search.el, h('span.small.muted.adm-q-count')),
    list,
    appendInput,
    replaceInput);

  async function reload() {
    try {
      const data = await api(`/api/admin/topics/${tid}/questions`);
      if (!state.alive) return;
      topic = data.topic;
      questions = data.questions;
    } catch (e) {
      if (state.alive) body.replaceChildren(emptyState('alert', 'Mavzuni ochib boʻlmadi', e.message, h('a.btn.primary', { href: '#/admin/topics' }, 'Mavzular')));
      return;
    }
    paintHead();
    paint();
    state.loadOverview();
  }

  function paintHead() {
    const shuffle = h('input', { type: 'checkbox', checked: topic.shuffle, 'aria-label': 'Variantlarni aralashtirish' });
    shuffle.addEventListener('change', async () => {
      try {
        const res = await api(`/api/admin/topics/${tid}`, { method: 'PATCH', body: { shuffle: shuffle.checked } });
        topic.shuffle = res.topic.shuffle;
        toast(topic.shuffle ? 'Variantlar endi aralashtiriladi' : 'Variantlar kiritilgan tartibda beriladi', 'success');
      } catch (e) {
        shuffle.checked = !shuffle.checked;
        toast(e.message, 'error');
      }
    });
    head.replaceChildren(h('div.card.adm-topic-head',
      h('div.adm-topic-title',
        h('h2', topic.name),
        h('button.icon-btn', { type: 'button', title: 'Nomini oʻzgartirish', 'aria-label': 'Nomini oʻzgartirish', onclick: rename }, icon('edit', 17)),
        topic.active ? null : h('span.badge.bad', icon('lock', 11), 'yopiq')),
      h('div.small.muted', `${topic.questionCount} ta savol · yaratilgan: ${fmtDate(topic.createdAt)}${topic.createdBy ? ` · ${topic.createdBy}` : ''}${topic.sourceFile ? ` · fayl: ${topic.sourceFile}` : ''}`),
      h('div.adm-topic-switches',
        activeSwitch(topic, () => paintHead()),
        h('label.switch', shuffle, h('span.slider'), h('span.small', 'variantlarni aralashtirish'))),
      h('div.adm-topic-actions',
        h('button.btn.primary', { type: 'button', onclick: () => questionDialog(null, reload, { tid }) }, icon('plus', 16), 'Savol qoʻshish'),
        h('a.btn.ghost', { href: `#/admin/bank?target=${tid}` }, icon('database', 16), 'Bankdan tanlash'),
        h('button.btn.ghost', { type: 'button', onclick: () => appendInput.click() }, icon('upload', 16), 'Fayldan savol qoʻshish'),
        h('button.btn.ghost', { type: 'button', onclick: () => replaceInput.click(), disabled: !topic.questionCount }, icon('refresh', 16), 'Fayl bilan almashtirish'),
        topic.questionCount ? h('a.btn.ghost', { href: `/api/admin/topics/${tid}/export`, download: `${topic.name}.txt` }, icon('download', 16), 'Yuklab olish') : null)));
  }

  function paint() {
    const q = search.value().toLocaleLowerCase();
    const shown = questions
      .map((item, i) => ({ item, n: i + 1 }))
      .filter(({ item }) => !q || item.text.toLocaleLowerCase().includes(q) || item.options.some((o) => o.toLocaleLowerCase().includes(q)));
    body.querySelector('.adm-q-count').textContent = q ? `topildi: ${shown.length} / ${questions.length}` : `${questions.length} ta savol`;
    if (!questions.length) {
      list.replaceChildren(emptyState('file', 'Bu mavzuda hali savol yoʻq',
        'Savollarni qoʻlda qoʻshing yoki .txt fayldan yuklang. Savoli yoʻq mavzu foydalanuvchilarga koʻrinmaydi.',
        h('div.empty-actions',
          h('button.btn.primary', { type: 'button', onclick: () => questionDialog(null, reload, { tid }) }, icon('plus', 16), 'Birinchi savolni qoʻshish'),
          h('a.btn.ghost', { href: `#/admin/bank?target=${tid}` }, icon('database', 16), 'Bankdan tanlash'))));
      return;
    }
    const cut = slicePage(shown, page, PER_PAGE);
    page = cut.page;
    list.replaceChildren(
      shown.length
        ? h('ol.preview-list.adm-qlist', cut.items.map(({ item, n }) => h('li.preview-q',
          h('div.preview-text', h('span.review-n', String(n)), h('span', item.text),
            h('span.adm-q-tools',
              h('button.icon-btn', { type: 'button', title: 'Tahrirlash', 'aria-label': `${n}-savolni tahrirlash`, onclick: () => questionDialog(item, reload, { tid, shared: item.topicCount }) }, icon('edit', 16)),
              h('button.icon-btn.danger', { type: 'button', title: 'Mavzudan olib tashlash', 'aria-label': `${n}-savolni mavzudan olib tashlash`, onclick: () => removeQuestion(item, n) }, icon('minus', 16)))),
          h('ul.review-opts', item.options.map((o, j) => h('li', { class: j === item.correct ? 'is-correct' : '' }, h('span.opt-key.sm', LETTERS[j]), h('span.review-opt', o)))),
          item.topicCount > 1 ? h('div.bank-meta', h('span.tag', icon('link', 11), `yana ${item.topicCount - 1} ta mavzuda ishlatiladi`)) : null)))
        : h('div.card.muted.center', 'Hech narsa topilmadi.'),
      pager({ ...cut, onChange: (p) => { page = p; paint(); scrollToTop(list); } }));
  }

  async function rename() {
    const name = await promptDialog({ title: 'Mavzu nomini oʻzgartirish', label: 'Yangi nom', value: topic.name, validate: (v) => (v ? '' : 'Nomni kiriting') });
    if (!name || name === topic.name) return;
    try {
      await api(`/api/admin/topics/${tid}`, { method: 'PATCH', body: { name } });
      toast('Mavzu nomi oʻzgartirildi', 'success');
      reload();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function removeQuestion(item, n) {
    const ok = await confirmDialog({
      title: `${n}-savolni mavzudan olib tashlash`,
      message: `«${item.text.slice(0, 120)}» savoli bu mavzudan olib tashlanadi. Savol bankda qoladi — uni butunlay oʻchirish «Savollar banki» boʻlimida.`,
      okText: 'Olib tashlash',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/admin/topics/${tid}/questions/${item.id}`, { method: 'DELETE' });
      toast('Savol mavzudan olib tashlandi', 'success');
      reload();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  reload();
}

/**
 * Ko'p variantli savolni qo'lda qo'shish yoki tahrirlash (2–10 variant, bitta to'g'ri javob).
 * tid berilsa — mavzu orqali (yangi savol mavzuga biriktiriladi), aks holda — to'g'ridan-to'g'ri bankda.
 * shared — savol nechta mavzuda ishlatilishi (tahrir hammasida ko'rinishini ogohlantirish uchun).
 */
function questionDialog(item, onSaved, { tid = null, topicIds = [], note = '', shared = 0 } = {}) {
  const MAX = 10;
  const text = h('textarea.adm-q-text', { rows: 3, maxlength: 5000, placeholder: 'Savol matni' });
  text.value = item ? item.text : '';
  const rows = h('div.adm-opts');
  const err = h('div.field-error');
  const group = `correct-${Math.random().toString(36).slice(2)}`;
  let opts = item ? item.options.map((o, j) => ({ text: o, correct: j === item.correct })) : [0, 1, 2, 3].map(() => ({ text: '', correct: false }));
  const addBtn = h('button.btn.ghost.sm', { type: 'button', onclick: () => { sync(); opts.push({ text: '', correct: false }); paint(opts.length - 1); } }, icon('plus', 14), 'Variant qoʻshish');

  function sync() {
    [...rows.children].forEach((row, j) => {
      opts[j].text = row.querySelector('input[type=text]').value;
      opts[j].correct = row.querySelector('input[type=radio]').checked;
    });
  }

  function paint(focusIndex) {
    rows.replaceChildren(...opts.map((o, j) => {
      const radio = h('input', { type: 'radio', name: group, checked: o.correct, 'aria-label': `${LETTERS[j]} — toʻgʻri javob`, title: 'Toʻgʻri javob' });
      const input = h('input', { type: 'text', value: o.text, maxlength: 2000, placeholder: `${LETTERS[j]} variant` });
      return h(`div.adm-opt${o.correct ? '.is-correct' : ''}`,
        h('label.adm-opt-key', radio, h('span.opt-key.sm', LETTERS[j])),
        input,
        h('button.icon-btn', { type: 'button', title: 'Variantni olib tashlash', 'aria-label': `${LETTERS[j]} variantni olib tashlash`, disabled: opts.length <= 2, onclick: () => { sync(); opts.splice(j, 1); paint(); } }, icon('x', 16)));
    }));
    rows.querySelectorAll('input[type=radio]').forEach((r) => r.addEventListener('change', () => {
      sync();
      paint();
    }));
    addBtn.disabled = opts.length >= MAX;
    if (focusIndex !== undefined) rows.children[focusIndex]?.querySelector('input[type=text]').focus();
  }

  /** Saqlaydi; again=true bo'lsa oyna ochiq qoladi va keyingi savol uchun tozalanadi. */
  async function save(m, again = false) {
    sync();
    err.textContent = '';
    const filled = opts.filter((o) => o.text.trim());
    const correct = filled.findIndex((o) => o.correct);
    if (!text.value.trim()) return fail('Savol matnini kiriting', text);
    if (filled.length < 2) return fail('Kamida 2 ta variant kiriting');
    if (correct < 0) return fail('Toʻgʻri javobni belgilang (variant yonidagi doiracha)');
    const body = { text: text.value, options: filled.map((o) => o.text), correct };
    try {
      const url = tid
        ? `/api/admin/topics/${tid}/questions${item ? `/${item.id}` : ''}`
        : `/api/admin/bank${item ? `/${item.id}` : ''}`;
      await api(url, { method: item ? 'PUT' : 'POST', body: item || tid ? body : { ...body, topicIds } });
    } catch (e) {
      return fail(e.message);
    }
    toast(item ? 'Savol saqlandi' : 'Savol qoʻshildi', 'success');
    onSaved();
    if (!again) {
      m.close();
      return true;
    }
    text.value = '';
    opts = [0, 1, 2, 3].map(() => ({ text: '', correct: false }));
    paint();
    text.focus();
    return true;
  }

  function fail(message, el) {
    err.textContent = message;
    if (el) el.focus();
    return false;
  }

  const actions = item
    ? [{ text: 'Bekor qilish' }, { text: 'Saqlash', kind: 'primary', icon: 'check', onClick: (m) => save(m) }]
    : [
      { text: 'Bekor qilish' },
      { text: 'Qoʻshish va yana', icon: 'plus', onClick: (m) => save(m, true) },
      { text: 'Qoʻshish', kind: 'primary', icon: 'check', onClick: (m) => save(m) },
    ];
  const modal = openModal({
    title: item ? 'Savolni tahrirlash' : 'Yangi savol',
    wide: true,
    body: [
      shared > 1 ? h('div.alert.warning', icon('link', 18), h('span', `Bu savol ${shared} ta mavzuda ishlatiladi — oʻzgarish hammasida koʻrinadi.`)) : null,
      note ? h('div.alert.info', icon('help', 18), h('span', note)) : null,
      h('label.field', h('span.field-label', 'Savol'), text),
      h('div.field', h('span.field-label', 'Javob variantlari — toʻgʻrisini doiracha bilan belgilang'), rows, h('div', addBtn)),
      h('p.small.muted', 'Hozircha faqat bitta toʻgʻri javobli test savollari. Boʻsh qolgan variantlar hisobga olinmaydi.'),
      err,
    ],
    actions,
  });
  text.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      save(modal);
    }
  });
  paint();
  setTimeout(() => { // foydalanuvchi allaqachon variant yozayotgan bo'lsa fokusni tortib olmaymiz
    if (!modal.el.contains(document.activeElement) || document.activeElement.type === 'radio') text.focus();
  }, 60);
}

// ========================================================== savollar banki
const BANK_PER = 30;

function bankSection(body, ctx, state, query) {
  const selected = new Set(); // sahifalar va filtrlar almashganda ham saqlanadi
  const filter = { search: '', topic: query.get('topic') || '' };
  let target = Number(query.get('target')) || null; // mavzu sahifasidan «Bankdan tanlash»
  let topics = [];
  let data = null;
  let page = 1;
  let seq = 0;
  let lastIndex = null; // Shift bilan oraliqni belgilash uchun

  let timer = 0;
  const search = searchBox('Savol yoki variant matni boʻyicha qidirish', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      filter.search = search.value();
      page = 1;
      load();
    }, 250);
  });
  state.cleanups.push(() => clearTimeout(timer));
  const topicFilter = h('select.adm-select', { 'aria-label': 'Mavzu boʻyicha filtr' });
  topicFilter.addEventListener('change', () => {
    filter.topic = topicFilter.value;
    page = 1;
    load();
  });
  const fileInput = h('input', { type: 'file', accept: '.txt,text/plain', multiple: true, hidden: true });
  fileInput.addEventListener('change', async () => {
    const files = [...fileInput.files].filter((f) => /\.txt$/i.test(f.name) || f.type === 'text/plain');
    if (fileInput.files.length && !files.length) toast('Faqat .txt formatidagi fayllarni yuklash mumkin', 'error');
    fileInput.value = '';
    let saved = false;
    for (let i = 0; i < files.length; i++) {
      const res = await reviewFile(files[i], { k: i + 1, n: files.length, bank: { topics, preset: target } });
      if (res === 'saved') saved = true;
      if (res === 'stop') break;
    }
    if (saved) changed();
  });
  const targetBox = h('div');
  const selBar = h('div.bank-selbar');
  const summary = h('p.small.muted.adm-summary');
  const list = h('div', spinner('Savollar yuklanmoqda…'));
  const pagerBox = h('div');
  body.append(
    targetBox,
    h('div.card.adm-quick',
      h('div.adm-reg-text',
        h('b', 'Barcha savollar bir joyda'),
        h('span.small.muted', 'Savollarni belgilab istalgan mavzuga qoʻshing: bitta savol bir nechta mavzuda ishlatilishi, bir mavzu esa turli mavzulardagi savollardan tuzilishi mumkin.')),
      h('div.adm-quick-actions',
        h('button.btn.primary', { type: 'button', onclick: () => addQuestion() }, icon('plus', 16), 'Savol qoʻshish'),
        h('button.btn.ghost', { type: 'button', onclick: () => fileInput.click() }, icon('upload', 16), 'Fayldan yuklash'))),
    fileInput,
    h('div.adm-toolbar', search.el, topicFilter),
    selBar,
    summary,
    list,
    pagerBox);

  const targetTopic = () => topics.find((t) => t.id === target) || null;
  const changed = () => {
    load();
    loadTopics();
    state.loadOverview();
  };

  async function loadTopics() {
    try {
      topics = (await api('/api/admin/topics')).topics;
    } catch {
      return;
    }
    if (!state.alive) return;
    if (target && !targetTopic()) target = null;
    const known = filter.topic === '' || filter.topic === 'none' || topics.some((t) => String(t.id) === filter.topic);
    if (!known) {
      filter.topic = '';
      load();
    }
    topicFilter.replaceChildren(
      h('option', { value: '' }, 'Barcha mavzular'),
      h('option', { value: 'none' }, 'Hech bir mavzuda yoʻq'),
      ...topics.map((t) => h('option', { value: String(t.id) }, `${t.name} (${t.questionCount})`)));
    topicFilter.value = filter.topic;
    paintTarget();
    paintSel();
  }

  async function load() {
    const my = ++seq;
    const params = new URLSearchParams({ page: String(page), per: String(BANK_PER) });
    if (filter.search) params.set('search', filter.search);
    if (filter.topic) params.set('topic', filter.topic);
    let res;
    try {
      res = await api(`/api/admin/bank?${params}`);
    } catch (e) {
      if (my === seq && state.alive) list.replaceChildren(emptyState('wifiOff', 'Savollarni yuklab boʻlmadi', e.message));
      return;
    }
    if (my !== seq || !state.alive) return;
    const pages = Math.max(1, Math.ceil(res.total / BANK_PER));
    if (page > pages) { // oxirgi sahifadagi savollar o'chirilgan bo'lsa
      page = pages;
      load();
      return;
    }
    data = res;
    lastIndex = null;
    paint();
  }

  function paintTarget() {
    const t = targetTopic();
    if (!t) {
      targetBox.replaceChildren();
      return;
    }
    targetBox.replaceChildren(h('div.card.bank-target',
      h('span.bank-target-ic', icon('folderPlus', 20)),
      h('div.adm-reg-text',
        h('b', `«${t.name}» mavzusiga savol tanlash`),
        h('span.small.muted', `Hozir mavzuda ${t.questionCount} ta savol. Kerakli savollarni belgilang va «Mavzuga qoʻshish»ni bosing — istalgan mavzudan, qidiruv orqali.`)),
      h('div.adm-quick-actions',
        h('a.btn.ghost.sm', { href: `#/admin/topics/${t.id}` }, icon('left', 14), 'Mavzuga qaytish'),
        h('button.icon-btn', { type: 'button', title: 'Tanlash rejimini yopish', 'aria-label': 'Tanlash rejimini yopish', onclick: () => { target = null; paintTarget(); paintSel(); paint(); } }, icon('x', 16)))));
  }

  function paintSel() {
    if (!data) return;
    const n = selected.size;
    const onPage = data.questions.map((q) => q.id);
    const pageAll = onPage.length > 0 && onPage.every((id) => selected.has(id));
    const pageCb = h('input', { type: 'checkbox', checked: pageAll, 'aria-label': 'Sahifadagi barcha savollarni belgilash' });
    pageCb.indeterminate = !pageAll && onPage.some((id) => selected.has(id));
    pageCb.addEventListener('change', () => {
      onPage.forEach((id) => (pageCb.checked ? selected.add(id) : selected.delete(id)));
      paint();
    });
    const t = targetTopic();
    selBar.classList.toggle('has-sel', n > 0);
    selBar.replaceChildren(...[
      h('label.bank-check.bank-check-all', { title: 'Sahifadagilarni belgilash' }, pageCb),
      n ? h('b.bank-sel-n', `${n} ta tanlandi`) : h('span.small.muted', 'Savollarni belgilang'),
      data.total > onPage.length && !(n >= data.total)
        ? h('button.link-btn', { type: 'button', onclick: selectAllMatching }, `Filtrdagi barchasini tanlash (${data.total})`)
        : null,
      n ? h('button.link-btn', { type: 'button', onclick: () => { selected.clear(); paint(); } }, 'Tozalash') : null,
      h('span.bank-sel-actions',
        n ? h('button.btn.ghost.sm.bank-del', { type: 'button', onclick: removeSelected }, icon('trash', 15), h('span.hide-xs', 'Oʻchirish')) : null,
        t && n ? h('button.btn.ghost.sm', { type: 'button', onclick: () => addToTopic(null) }, icon('folderPlus', 15), h('span.hide-xs', 'Boshqa mavzuga')) : null,
        h('button.btn.primary.sm', { type: 'button', disabled: !n, onclick: () => addToTopic(t) }, icon('folderPlus', 15), t ? `«${clip(t.name, 24)}»ga qoʻshish` : 'Mavzuga qoʻshish')),
    ].filter(Boolean)); // DOM replaceChildren null'ni matn sifatida qo'yadi
  }

  function paint() {
    if (!data) return;
    paintSel();
    const { total, questions } = data;
    const filtered = filter.search || filter.topic;
    summary.textContent = filtered ? `Topildi: ${total} ta savol` : `Bankda ${total} ta savol`;
    if (!questions.length) {
      list.replaceChildren(filtered
        ? h('div.card.muted.center', 'Bu filtr boʻyicha savol topilmadi.')
        : emptyState('database', 'Bank hali boʻsh', 'Savollarni qoʻlda qoʻshing yoki .txt fayldan yuklang. Mavzular uchun yuklangan savollar ham shu yerda koʻrinadi.'));
      pagerBox.replaceChildren();
      return;
    }
    const t = targetTopic();
    const from = (data.page - 1) * data.per;
    list.replaceChildren(h('ol.preview-list.adm-qlist.bank-list', questions.map((q, i) => card(q, i, from + i + 1, t))));
    pagerBox.replaceChildren(pager({
      page: data.page,
      pages: Math.max(1, Math.ceil(total / data.per)),
      total,
      per: data.per,
      onChange: (p) => {
        page = p;
        load();
        scrollToTop(list);
      },
    }));
  }

  function card(q, index, n, t) {
    const cb = h('input', { type: 'checkbox', checked: selected.has(q.id), 'aria-label': `${n}-savolni belgilash` });
    const li = h(`li.preview-q.bank-q${selected.has(q.id) ? '.is-selected' : ''}`);
    cb.addEventListener('click', (e) => {
      const on = cb.checked;
      if (e.shiftKey && lastIndex !== null && lastIndex !== index) { // Shift — oraliqdagi hammasini
        const [a, b] = [Math.min(lastIndex, index), Math.max(lastIndex, index)];
        data.questions.slice(a, b + 1).forEach((x) => (on ? selected.add(x.id) : selected.delete(x.id)));
        lastIndex = index;
        paint();
        return;
      }
      lastIndex = index;
      if (on) selected.add(q.id);
      else selected.delete(q.id);
      li.classList.toggle('is-selected', on);
      paintSel();
    });
    const inTarget = t && q.topics.some((x) => x.id === t.id);
    li.append(
      h('div.preview-text',
        h('label.bank-check', cb),
        h('span.review-n', String(n)),
        h('span.bank-q-text', q.text),
        h('span.adm-q-tools',
          h('button.icon-btn', { type: 'button', title: 'Tahrirlash', 'aria-label': `${n}-savolni tahrirlash`, onclick: () => questionDialog(q, changed, { shared: q.topics.length }) }, icon('edit', 16)),
          h('button.icon-btn.danger', { type: 'button', title: 'Bankdan oʻchirish', 'aria-label': `${n}-savolni bankdan oʻchirish`, onclick: () => removeOne(q) }, icon('trash', 16)))),
      h('ul.review-opts', q.options.map((o, j) => h('li', { class: j === q.correct ? 'is-correct' : '' }, h('span.opt-key.sm', LETTERS[j]), h('span.review-opt', o)))),
      h('div.bank-meta',
        inTarget ? h('span.tag.ok', icon('check', 11), 'mavzuda bor') : null,
        q.topics.length
          ? q.topics.map((x) => h('a.bank-chip', { href: `#/admin/topics/${x.id}`, class: t && x.id === t.id ? 'bank-chip is-target' : 'bank-chip' }, x.name))
          : h('span.tag.opp', 'hech bir mavzuda yoʻq'),
        h('span.bank-src', [q.sourceFile ? q.sourceFile : 'qoʻlda kiritilgan', q.author, q.createdAt ? fmtDate(q.createdAt).split(' ')[0] : null].filter(Boolean).join(' · '))));
    return li;
  }

  async function selectAllMatching() {
    const params = new URLSearchParams();
    if (filter.search) params.set('search', filter.search);
    if (filter.topic) params.set('topic', filter.topic);
    try {
      const { ids } = await api(`/api/admin/bank/ids?${params}`);
      ids.forEach((id) => selected.add(id));
      if (ids.length < data.total) toast(`Bir martada koʻpi bilan ${ids.length} ta savol tanlanadi`, 'warning');
    } catch (e) {
      toast(e.message, 'error');
    }
    if (state.alive) paint();
  }

  function addQuestion() {
    const t = targetTopic();
    questionDialog(null, changed, t ? { topicIds: [t.id], note: `Savol bankka va «${t.name}» mavzusiga qoʻshiladi.` } : {});
  }

  /** Tanlangan savollarni mavjud yoki yangi mavzuga qo'shish. preset — oldindan tanlangan mavzu. */
  function addToTopic(preset) {
    const ids = [...selected];
    if (!ids.length) return;
    const finish = (res, name) => {
      const had = ids.length - res.linked;
      toast(`${res.linked} ta savol «${name}» mavzusiga qoʻshildi${had ? ` (${had} tasi oldin bor edi)` : ''}`, 'success', 5000);
      selected.clear();
      changed();
    };
    if (preset) {
      api(`/api/admin/topics/${preset.id}/link`, { method: 'POST', body: { questionIds: ids } })
        .then((res) => finish(res, preset.name))
        .catch((e) => toast(e.message, 'error'));
      return;
    }
    const group = `dest-${Math.random().toString(36).slice(2)}`;
    const useNew = h('input', { type: 'radio', name: group, checked: !topics.length });
    const useOld = h('input', { type: 'radio', name: group, checked: !!topics.length, disabled: !topics.length });
    const select = topicSelect(topics, target, null);
    const name = h('input', { type: 'text', maxlength: 120, placeholder: 'Masalan: Takrorlash — 1-chorak' });
    const shuffle = h('input', { type: 'checkbox', checked: true });
    const err = h('div.field-error');
    select.addEventListener('focus', () => { useOld.checked = true; });
    name.addEventListener('focus', () => { useNew.checked = true; });
    const submit = async (m) => {
      err.textContent = '';
      try {
        if (useNew.checked) {
          if (!name.value.trim()) {
            err.textContent = 'Yangi mavzu nomini kiriting';
            name.focus();
            return;
          }
          const created = await api('/api/admin/topics', { method: 'POST', body: { name: name.value.trim(), shuffle: shuffle.checked } });
          const res = await api(`/api/admin/topics/${created.topic.id}/link`, { method: 'POST', body: { questionIds: ids } });
          m.close();
          finish(res, created.topic.name);
          ctx.navigate(`/admin/topics/${created.topic.id}`);
        } else {
          const tid = Number(select.value);
          const res = await api(`/api/admin/topics/${tid}/link`, { method: 'POST', body: { questionIds: ids } });
          m.close();
          finish(res, res.topic.name);
        }
      } catch (e) {
        err.textContent = e.message;
      }
    };
    openModal({
      title: `${ids.length} ta savolni mavzuga qoʻshish`,
      body: [
        h('label.check.bank-dest', useOld, h('span', 'Mavjud mavzuga')),
        h('div.bank-dest-field', select),
        h('label.check.bank-dest', useNew, h('span', 'Yangi mavzu yaratish')),
        h('div.bank-dest-field', name, h('label.check', shuffle, h('span', 'Javob variantlari tartibini har safar aralashtirish'))),
        h('p.small.muted', 'Savollar mavzu oxiriga qoʻshiladi. Mavzuda allaqachon bor savollar takrorlanmaydi.'),
        err,
      ],
      actions: [{ text: 'Bekor qilish' }, { text: 'Qoʻshish', kind: 'primary', icon: 'check', onClick: submit }],
    });
    name.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') e.preventDefault();
    });
  }

  async function removeOne(q) {
    const where = q.topics.length ? ` U ${q.topics.length} ta mavzudan ham olib tashlanadi: ${q.topics.map((t) => `«${t.name}»`).join(', ')}.` : '';
    const ok = await confirmDialog({
      title: 'Savolni bankdan oʻchirish',
      message: `«${clip(q.text, 120)}» savoli butunlay oʻchiriladi.${where} Bu amalni qaytarib boʻlmaydi.`,
      okText: 'Oʻchirish',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/admin/bank/${q.id}`, { method: 'DELETE' });
      selected.delete(q.id);
      toast('Savol bankdan oʻchirildi', 'success');
      changed();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function removeSelected() {
    const ids = [...selected];
    const ok = await confirmDialog({
      title: `${ids.length} ta savolni oʻchirish`,
      message: `Tanlangan ${ids.length} ta savol bankdan butunlay oʻchiriladi va ular biriktirilgan barcha mavzulardan olib tashlanadi. Bu amalni qaytarib boʻlmaydi. Faqat bitta mavzudan olib tashlash uchun mavzu sahifasidan foydalaning.`,
      okText: 'Oʻchirish',
      danger: true,
    });
    if (!ok) return;
    try {
      const res = await api('/api/admin/bank/delete', { method: 'POST', body: { questionIds: ids } });
      selected.clear();
      toast(`${res.deleted} ta savol oʻchirildi${res.topics ? ` · ${res.topics} ta mavzu yangilandi` : ''}`, 'success');
      changed();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  loadTopics();
  load();
  state.cleanups.push(live.on('topics', () => {
    loadTopics();
    load();
  }));
}

// ======================================================= foydalanuvchilar
const FILTERS = [
  ['all', 'Hammasi'],
  ['admins', 'Adminlar'],
  ['teachers', 'Oʻqituvchilar'],
  ['members', 'Foydalanuvchilar'],
  ['online', 'Onlayn'],
  ['blocked', 'Bloklangan'],
];

function usersSection(body, ctx, state, query) {
  let users = null;
  let filter = 'all';
  let page = 1;
  const manage = !!ctx.user.isSuperadmin; // foydalanuvchilarni faqat bosh administrator boshqaradi
  const search = searchBox('Login boʻyicha qidirish', () => {
    page = 1;
    paint();
  });
  const filters = h('div.adm-filters', { role: 'tablist' });
  const list = h('div', spinner());
  const regBox = h('div.adm-reg-slot');
  body.append(
    manage
      ? h('div.card.adm-quick',
        h('div.adm-quick-actions', h('button.btn.primary', { type: 'button', onclick: () => createUser() }, icon('userPlus', 16), 'Foydalanuvchi qoʻshish')),
        regBox)
      : h('div.card.adm-quick',
        h('div.alert.info.adm-readonly-note', icon('shield', 18), h('span',
          'Foydalanuvchilarni (bloklash, parolni tiklash, admin yoki oʻqituvchi qilish) faqat bosh administrator boshqaradi. Siz roʻyxatni koʻrishingiz mumkin.')),
        regBox),
    h('div.adm-toolbar', search.el, filters,
      h('button.btn.ghost.sm', { type: 'button', onclick: () => load() }, icon('refresh', 16), 'Yangilash')),
    list);

  state.overview.then((data) => {
    if (state.alive) regBox.replaceChildren(registrationSwitch(data.settings.registrationOpen, manage));
  }).catch(() => {});

  // onlayn holat jonli: administratorlarga onlayn identifikatorlar obunasi (aks holda — ro'yxat yuklangan paytdagi holat)
  const isOnline = (u) => (live.onlineIds ? live.onlineIds.has(u.id) : u.online);
  const match = {
    all: () => true,
    admins: (u) => u.isAdmin,
    teachers: (u) => u.isTeacher && !u.isAdmin,
    members: (u) => !u.isAdmin && !u.isTeacher,
    online: isOnline,
    blocked: (u) => u.blocked,
  };

  async function load() {
    try {
      users = (await api('/api/admin/users')).users;
    } catch (e) {
      if (state.alive) list.replaceChildren(emptyState('wifiOff', 'Roʻyxatni yuklab boʻlmadi', e.message));
      return;
    }
    if (state.alive) paint();
  }

  function paint() {
    if (!users) return;
    filters.replaceChildren(...FILTERS.map(([id, label]) => h('button', {
      type: 'button',
      role: 'tab',
      'aria-selected': String(id === filter),
      class: `adm-filter${id === filter ? ' active' : ''}`,
      onclick: () => {
        filter = id;
        page = 1;
        paint();
      },
    }, label, h('span.adm-filter-n', String(users.filter(match[id]).length)))));
    const q = search.value().toLocaleLowerCase();
    const shown = users.filter((u) => match[filter](u) && (!q || u.login.toLocaleLowerCase().includes(q)));
    const cut = slicePage(shown, page, PER_PAGE);
    page = cut.page;
    list.replaceChildren(
      shown.length
        ? h('div.card.table-card', h('div.table-wrap', h('table.table.adm-table.adm-users',
          h('thead', h('tr',
            h('th', 'Foydalanuvchi'), h('th', 'Rol'), h('th.hide-sm', 'Faollik'), h('th.hide-sm', 'Oxirgi kirish'), manage ? h('th.right', 'Amallar') : null)),
          h('tbody', cut.items.map(row)))))
        : h('div.card.muted.center', 'Hech kim topilmadi.'),
      pager({ ...cut, onChange: (p) => { page = p; paint(); scrollToTop(list); } }));
  }

  function row(u) {
    const self = u.id === ctx.user.id;
    const online = isOnline(u);
    const btn = (ic, title, onclick, cls = '') => h(`button.icon-btn${cls}`, { type: 'button', title, 'aria-label': `${title}: ${u.login}`, onclick }, icon(ic, 17));
    return h(`tr${u.blocked ? '.is-blocked' : ''}`,
      h('td.adm-td-main', h('div.adm-user',
        avatar(u.login, 'sm'),
        h('div.adm-row-main',
          h('div.adm-row-title', h('span.ellipsis', u.login), online ? h('span.live-dot', { title: 'hozir onlayn' }) : null, self ? h('span.tag', 'siz') : null),
          h('div.adm-row-sub', `roʻyxatdan oʻtgan: ${fmtDate(u.createdAt).split(' ')[0]}`)))),
      h('td.adm-td-role', h('div.adm-badges',
        u.isSuperadmin
          ? h('span.badge.owner', icon('crown', 11), 'bosh admin')
          : u.isAdmin ? h('span.badge.admin', icon('shield', 11), 'admin')
            : u.isTeacher ? h('span.badge.teacher', icon('teacher', 11), 'oʻqituvchi') : h('span.badge.neutral', 'foydalanuvchi'),
        u.blocked ? h('span.badge.bad', icon('lock', 11), 'bloklangan') : null)),
      h('td.hide-sm.small', h('span.adm-activity', { title: 'duel · mashgʻulot · Balloon Pop' },
        h('span', icon('swords', 13), String(u.duels)), h('span', icon('book', 13), String(u.practices)), h('span', icon('balloon', 13), String(u.balloonGames)))),
      h('td.hide-sm.small.nowrap', online ? h('span.adm-online', 'hozir onlayn') : fmtAgo(u.lastSeenAt)),
      manage ? h('td.right.nowrap',
        self || u.isAdmin ? null : btn('teacher', u.isTeacher ? 'Oʻqituvchi huquqini olish' : 'Oʻqituvchi qilish', () => toggleTeacher(u), u.isTeacher ? '.on' : ''),
        self ? null : btn('shield', u.isAdmin ? 'Admin huquqini olish' : 'Admin qilish', () => toggleAdmin(u), u.isAdmin ? '.on' : ''),
        btn('key', 'Parolni yangilash', () => resetPassword(u)),
        self ? null : btn(u.blocked ? 'unlock' : 'lock', u.blocked ? 'Blokdan chiqarish' : 'Bloklash', () => toggleBlock(u), u.blocked ? '.on' : ''),
        self ? null : btn('trash', 'Oʻchirish', () => remove(u), '.danger')) : null);
  }

  async function patch(u, body, done) {
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'PATCH', body });
      toast(done, 'success');
      load();
      state.loadOverview();
      return true;
    } catch (e) {
      toast(e.message, 'error');
      return false;
    }
  }

  async function toggleAdmin(u) {
    const ok = await confirmDialog({
      title: u.isAdmin ? 'Admin huquqini olish' : 'Admin qilish',
      message: u.isAdmin
        ? `${u.login} endi test yuklay olmaydi va boshqaruv paneliga kira olmaydi.`
        : `${u.login} test mavzularini yuklash va foydalanuvchilarni boshqarish huquqini oladi.`,
      okText: u.isAdmin ? 'Huquqni olish' : 'Admin qilish',
    });
    if (ok) patch(u, { isAdmin: !u.isAdmin }, u.isAdmin ? `${u.login} endi oddiy foydalanuvchi` : `${u.login} endi administrator`);
  }

  async function toggleTeacher(u) {
    const ok = await confirmDialog({
      title: u.isTeacher ? 'Oʻqituvchi huquqini olish' : 'Oʻqituvchi qilish',
      message: u.isTeacher
        ? `${u.login} endi «Oʻyinlar» boʻlimini koʻrmaydi; uning davom etayotgan Octagon oʻyinlari yopiladi.`
        : `${u.login} «Oʻyinlar» boʻlimida Balloon Pop va Octagon oʻyinlarini yaratib, boshqara oladi.`,
      okText: u.isTeacher ? 'Huquqni olish' : 'Oʻqituvchi qilish',
    });
    if (ok) patch(u, { isTeacher: !u.isTeacher }, u.isTeacher ? `${u.login} endi oddiy foydalanuvchi` : `${u.login} endi oʻqituvchi`);
  }

  async function toggleBlock(u) {
    const ok = await confirmDialog({
      title: u.blocked ? 'Blokdan chiqarish' : 'Foydalanuvchini bloklash',
      message: u.blocked
        ? `${u.login} yana tizimga kira oladi.`
        : `${u.login} tizimdan chiqarib yuboriladi va qayta kira olmaydi (duelda boʻlsa — magʻlub deb topiladi). Natijalari saqlanib qoladi, istalgan payt blokdan chiqarish mumkin.`,
      okText: u.blocked ? 'Blokdan chiqarish' : 'Bloklash',
      danger: !u.blocked,
    });
    if (ok) patch(u, { blocked: !u.blocked }, u.blocked ? `${u.login} blokdan chiqarildi` : `${u.login} bloklandi`);
  }

  async function resetPassword(u) {
    const self = u.id === ctx.user.id;
    const pass = passwordField(genPassword());
    const err = h('div.field-error');
    const submit = async (m) => {
      const password = pass.input.value.trim();
      if (password.length < 4) {
        err.textContent = 'Parol kamida 4 ta belgidan iborat boʻlsin';
        pass.input.focus();
        return;
      }
      try {
        await api(`/api/admin/users/${u.id}`, { method: 'PATCH', body: { password } });
      } catch (e) {
        err.textContent = e.message;
        return;
      }
      m.close();
      showCredentials('Parol yangilandi', u.login, password, self
        ? 'Boshqa qurilmalardagi sessiyalaringiz yopildi.'
        : `${u.login} barcha qurilmalardan chiqarildi — endi yangi parol bilan kiradi.`);
    };
    openModal({
      title: `${u.login} — yangi parol`,
      body: h('label.field', h('span.field-label', 'Yangi parol'), pass.el,
        h('span.field-hint', 'Tasodifiy parol tayyorlab qoʻyildi — xohlasangiz oʻzgartiring.'), err),
      actions: [{ text: 'Bekor qilish' }, { text: 'Saqlash', kind: 'primary', icon: 'key', onClick: submit }],
    });
    setTimeout(() => pass.input.select(), 60);
  }

  async function remove(u) {
    const ok = await confirmDialog({
      title: 'Foydalanuvchini oʻchirish',
      message: `${u.login} akkaunti butunlay oʻchiriladi: oʻrganish natijalari va Balloon Pop oʻyinlari ham oʻchadi (duel tarixi raqiblarida saqlanadi). Vaqtincha cheklash uchun «Bloklash»dan foydalaning. Bu amalni qaytarib boʻlmaydi.`,
      okText: 'Oʻchirish',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'DELETE' });
      toast(`${u.login} oʻchirildi`, 'success');
      load();
      state.loadOverview();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  function createUser() {
    const login = h('input', { type: 'text', maxlength: 32, autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', placeholder: 'masalan: ali_valiyev' });
    const pass = passwordField(genPassword());
    const group = `role-${Math.random().toString(36).slice(2)}`;
    const roles = [
      ['user', 'Foydalanuvchi', 'duel, oʻrganish, reyting'],
      ['teacher', 'Oʻqituvchi', '+ «Oʻyinlar»: Balloon Pop va Octagon oʻyinlarini oʻtkazish'],
      ['admin', 'Administrator', '+ test mavzulari va savollar banki (oʻqituvchi huquqlari bilan)'],
    ].map(([value, title, hint]) => ({ value, input: h('input', { type: 'radio', name: group, value, checked: value === 'user' }), title, hint }));
    const roleOf = () => roles.find((r) => r.input.checked).value;
    const err = h('div.field-error');
    const submit = async (m) => {
      err.textContent = '';
      const role = roleOf();
      const body = { login: login.value.trim(), password: pass.input.value.trim(), isAdmin: role === 'admin', isTeacher: role === 'teacher' };
      if (!/^[\p{L}\p{N}_.-]{3,32}$/u.test(body.login)) {
        err.textContent = 'Login 3–32 ta harf, raqam yoki . _ - belgilaridan iborat boʻlishi kerak';
        login.focus();
        return;
      }
      if (body.password.length < 4) {
        err.textContent = 'Parol kamida 4 ta belgidan iborat boʻlsin';
        pass.input.focus();
        return;
      }
      try {
        await api('/api/admin/users', { method: 'POST', body });
      } catch (e) {
        err.textContent = e.message;
        return;
      }
      m.close();
      load();
      state.loadOverview();
      showCredentials('Akkaunt yaratildi', body.login, body.password, 'Ushbu maʼlumotlarni foydalanuvchiga bering. Parolni keyin ham oʻzgartirish mumkin.');
    };
    const m = openModal({
      title: 'Yangi foydalanuvchi',
      body: [
        h('label.field', h('span.field-label', 'Login'), login),
        h('label.field', h('span.field-label', 'Parol'), pass.el, h('span.field-hint', 'Tasodifiy parol tayyorlab qoʻyildi — xohlasangiz oʻzgartiring.')),
        h('div.field', h('span.field-label', 'Rol'), ...roles.map((r) => h('label.check.adm-role', r.input, h('span', h('b', r.title), h('span.muted', ` — ${r.hint}`))))),
        err,
      ],
      actions: [{ text: 'Bekor qilish' }, { text: 'Yaratish', kind: 'primary', icon: 'userPlus', onClick: submit }],
    });
    [login, pass.input].forEach((el) => el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submit(m);
      }
    }));
    setTimeout(() => login.focus(), 60);
  }

  load();
  if (manage && query.get('new')) createUser();
  live.subscribePresence();
  state.cleanups.push(live.on('presence', () => users && paint()));
  state.cleanups.push(() => live.unsubscribePresence());
}

// ============================================================ yordamchilar
const PER_PAGE = 50; // mijoz tomonida sahifalanadigan ro'yxatlar (mavzular, savollar, foydalanuvchilar)

function scrollToTop(el) {
  const top = el.getBoundingClientRect().top;
  if (top < 80) window.scrollBy({ top: top - 140, behavior: 'smooth' });
}

function clip(text, n) {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

/** Mavzu tanlash ro'yxati; empty — "tanlanmagan" varianti matni (null — variant yo'q). */
function topicSelect(topics, preset, empty) {
  const select = h('select.adm-select', { 'aria-label': 'Mavzu' },
    empty ? h('option', { value: '' }, empty) : null,
    topics.map((t) => h('option', { value: String(t.id) }, `${t.name} — ${t.questionCount} ta savol${t.active ? '' : ' (yopiq)'}`)));
  if (preset && topics.some((t) => t.id === preset)) select.value = String(preset);
  return select;
}

function searchBox(placeholder, onInput) {
  const input = h('input', { type: 'search', placeholder, 'aria-label': placeholder });
  input.addEventListener('input', onInput);
  return { el: h('label.adm-search', icon('search', 16), input), value: () => input.value.trim() };
}

const PASS_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789';

function genPassword(len = 8) {
  const bytes = new Uint8Array(len);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => PASS_ALPHABET[b % PASS_ALPHABET.length]).join('');
}

function passwordField(value) {
  const input = h('input.mono', { type: 'text', value, maxlength: 128, autocomplete: 'new-password', spellcheck: 'false' });
  const gen = h('button.input-addon', { type: 'button', title: 'Yangi tasodifiy parol', 'aria-label': 'Yangi tasodifiy parol' }, icon('refresh', 16));
  gen.addEventListener('click', () => {
    input.value = genPassword();
    input.focus();
  });
  return { el: h('div.input-wrap', input, gen), input };
}

function showCredentials(title, login, password, note) {
  const text = `Login: ${login}\nParol: ${password}`;
  openModal({
    title,
    body: [
      h('div.alert.success', icon('check', 18), h('span', note)),
      h('div.cred-box', h('span.muted', 'Login'), h('b', login), h('span.muted', 'Parol'), h('b', password)),
    ],
    actions: [
      {
        text: 'Nusxalash',
        icon: 'copy',
        onClick: async () => {
          const copied = await copyText(text);
          toast(copied ? 'Login va parol nusxalandi' : 'Nusxalab boʻlmadi — qoʻlda yozib oling', copied ? 'success' : 'warning');
        },
      },
      { text: 'Tayyor', kind: 'primary' },
    ],
  });
}
