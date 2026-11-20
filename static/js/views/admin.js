// Boshqaruv paneli (faqat administratorlar uchun): umumiy ko'rinish, test mavzulari va foydalanuvchilar.
import { h, icon, avatar, toast, openModal, confirmDialog, promptDialog, readTextFile, copyText, spinner, emptyState, fmtDate, fmtAgo, LETTERS } from '../lib.js';
import { api } from '../api.js';
import { live } from '../live.js';
import { teamStyle } from '../balloon-scene.js';

const SECTIONS = [
  { id: 'overview', path: '/admin', icon: 'grid', label: 'Umumiy koʻrinish' },
  { id: 'topics', path: '/admin/topics', icon: 'file', label: 'Test mavzulari' },
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
  if (!section) {
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
          counts.users.textContent = String(data.stats.users.total);
        }
        return data;
      });
      state.overview.catch(() => {});
      return state.overview;
    },
  };
  state.loadOverview();
  ({ overview: overviewSection, topics: topicsSection, users: usersSection })[section.id](body, ctx, state, query);
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
        card('file', 'test mavzusi', s.topics.total, `${s.topics.questions} ta savol`),
        card('swords', 'duel', s.duels.total, `${s.duels.week} ta bu hafta`, 'accent'),
        card('book', 'mashgʻulot', s.practice.total, `${s.practice.week} ta bu hafta`, 'green'),
        card('balloon', 'Balloon Pop oʻyini', s.balloon.total, s.balloon.active ? `${s.balloon.active} tasi davom etmoqda` : `${s.balloon.week} ta bu hafta`, 'accent')),
      h('div.card.adm-quick',
        h('div.adm-quick-actions',
          h('a.btn.primary', { href: '#/admin/topics' }, icon('upload', 16), 'Test yuklash'),
          h('a.btn.ghost', { href: '#/admin/users?new=1' }, icon('userPlus', 16), 'Foydalanuvchi qoʻshish')),
        registrationSwitch(data.settings.registrationOpen)),
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
  return u.isAdmin ? h('span.badge.admin', 'admin') : null;
}

function registrationSwitch(open) {
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
function topicsSection(body, ctx, state) {
  const input = h('input', { type: 'file', accept: '.txt,text/plain', multiple: true, hidden: true });
  const drop = h('label.dropzone',
    input,
    h('span.drop-ic', icon('upload', 28)),
    h('b', '.txt test faylini shu yerga tashlang yoki tanlash uchun bosing'),
    h('span.muted.small', 'Bir nechta faylni birdaniga tanlash mumkin — har biri alohida mavzu boʻladi.'));
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

  const search = searchBox('Mavzu nomi boʻyicha qidirish', () => paint());
  const list = h('div', spinner());
  body.append(
    h('div.upload-grid',
      h('div.card', h('h2.card-title', icon('upload', 18), 'Yangi test yuklash'), drop),
      h('div.card.format-card',
        h('h2.card-title', icon('file', 18), 'Fayl formati'),
        h('ul.format-rules',
          h('li', 'Savollar ', h('code', '++++'), ' bilan ajratiladi'),
          h('li', 'Savol va variantlar ', h('code', '===='), ' bilan ajratiladi'),
          h('li', 'Toʻgʻri javob oldiga ', h('code', '#'), ' qoʻyiladi')),
        h('pre.format-example', FORMAT_EXAMPLE))),
    h('div.adm-toolbar', search.el, h('button.btn.ghost.sm', { type: 'button', onclick: () => load() }, icon('refresh', 16), 'Yangilash')),
    list);

  let topics = null;

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
      load();
      state.loadOverview();
    }
  }

  async function load() {
    try {
      topics = (await api('/api/admin/topics')).topics;
    } catch (e) {
      if (state.alive) list.replaceChildren(emptyState('wifiOff', 'Roʻyxatni yuklab boʻlmadi', e.message));
      return;
    }
    if (state.alive) paint();
  }

  function paint() {
    if (!topics) return;
    if (!topics.length) {
      list.replaceChildren(emptyState('file', 'Hali mavzu yoʻq', 'Yuqoridagi maydon orqali birinchi test faylini yuklang.'));
      return;
    }
    const q = search.value().toLocaleLowerCase();
    const shown = q ? topics.filter((t) => t.name.toLocaleLowerCase().includes(q) || (t.sourceFile || '').toLocaleLowerCase().includes(q)) : topics;
    const total = topics.reduce((sum, t) => sum + t.questionCount, 0);
    list.replaceChildren(
      h('p.small.muted.adm-summary', `${topics.length} ta mavzu · ${total} ta savol${q ? ` · topildi: ${shown.length}` : ''}`),
      shown.length
        ? h('div.card.table-card', h('div.table-wrap', h('table.table.adm-table.adm-topics',
          h('thead', h('tr', h('th', 'Mavzu'), h('th.num', 'Savollar'), h('th.hide-sm', 'Variantlar'), h('th.hide-sm', 'Yuklangan'), h('th.right', 'Amallar'))),
          h('tbody', shown.map(topicRow)))))
        : h('div.card.muted.center', 'Hech narsa topilmadi.'));
  }

  function topicRow(t) {
    const sw = h('input', { type: 'checkbox', checked: t.shuffle, 'aria-label': 'Variantlarni aralashtirish' });
    sw.addEventListener('change', async () => {
      try {
        await api(`/api/admin/topics/${t.id}`, { method: 'PATCH', body: { shuffle: sw.checked } });
        t.shuffle = sw.checked;
        toast(sw.checked ? 'Variantlar endi aralashtiriladi' : 'Variantlar fayldagi tartibda beriladi', 'success');
      } catch (e) {
        sw.checked = !sw.checked;
        toast(e.message, 'error');
      }
    });
    const replaceInput = h('input', { type: 'file', accept: '.txt,text/plain', hidden: true });
    replaceInput.addEventListener('change', async () => {
      const file = replaceInput.files[0];
      replaceInput.value = '';
      if (file && (await reviewFile(file, { replace: t })) === 'saved' && state.alive) {
        load();
        state.loadOverview();
      }
    });
    const btn = (ic, title, onclick, cls = '') => h(`button.icon-btn${cls}`, { type: 'button', title, 'aria-label': title, onclick }, icon(ic, 17));
    return h('tr',
      h('td.adm-td-main', h('div.topic-cell', h('b', t.name), h('span.small.muted', t.sourceFile || ''))),
      h('td.num.adm-td-count', String(t.questionCount), h('span.adm-sm-only', ' ta savol')),
      h('td.hide-sm', h('label.switch', { title: 'Javob variantlarini har safar aralashtirish' }, sw, h('span.slider'), h('span.small', 'aralash'))),
      h('td.hide-sm.small.nowrap', fmtDate(t.createdAt), t.createdBy ? h('div.muted', t.createdBy) : null),
      h('td.right.nowrap',
        replaceInput,
        btn('eye', 'Savollarni koʻrish', () => viewQuestions(t)),
        h('a.icon-btn', { href: `/api/admin/topics/${t.id}/export`, download: `${t.name}.txt`, title: '.txt fayl sifatida yuklab olish', 'aria-label': 'Yuklab olish' }, icon('download', 17)),
        btn('upload', 'Yangi fayl bilan almashtirish', () => replaceInput.click()),
        btn('edit', 'Nomini oʻzgartirish', () => rename(t)),
        btn('trash', 'Oʻchirish', () => remove(t), '.danger')));
  }

  async function rename(t) {
    const name = await promptDialog({ title: 'Mavzu nomini oʻzgartirish', label: 'Yangi nom', value: t.name, validate: (v) => (v ? '' : 'Nomni kiriting') });
    if (!name || name === t.name) return;
    try {
      await api(`/api/admin/topics/${t.id}`, { method: 'PATCH', body: { name } });
      toast('Mavzu nomi oʻzgartirildi', 'success');
      load();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function remove(t) {
    const ok = await confirmDialog({
      title: 'Mavzuni oʻchirish',
      message: `«${t.name}» mavzusi va undagi ${t.questionCount} ta savol butunlay oʻchiriladi. Duel va oʻyinlar tarixi saqlanib qoladi. Davom etasizmi?`,
      okText: 'Oʻchirish',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/admin/topics/${t.id}`, { method: 'DELETE' });
      toast('Mavzu oʻchirildi', 'success');
      load();
      state.loadOverview();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  load();
  state.cleanups.push(live.on('topics', load));
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
async function reviewFile(file, { k = 1, n = 1, replace = null } = {}) {
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
        ? h('div.alert.warning', icon('refresh', 18), h('span', `«${replace.name}» mavzusidagi ${replace.questionCount} ta savol shu fayldagi ${parsed.count} ta savol bilan almashtiriladi. Mavzu nomi, sozlamalari va oʻyinlar tarixi saqlanib qoladi.`))
        : null,
      errorsBlock,
      parsed.preview.length
        ? h('details.preview', h('summary', icon('eye', 16), `Dastlabki ${parsed.preview.length} ta savolni koʻrish`), h('ol.preview-list', parsed.preview.map(questionPreview)))
        : null,
      !replace && parsed.count ? h('label.field', h('span.field-label', 'Mavzu nomi'), nameInput, h('span.field-hint', 'Bu nom duel, oʻrganish va Balloon Pop boʻlimlarida koʻrinadi.')) : null,
      !replace && parsed.count ? h('label.check', shuffle, h('span', 'Javob variantlari tartibini har safar aralashtirish')) : null,
      err,
    ];
    const save = async (m) => {
      err.hidden = true;
      try {
        if (replace) {
          const res = await api(`/api/admin/topics/${replace.id}/content`, { method: 'PUT', body: { content: text, fileName: file.name } });
          toast(`«${res.topic.name}» yangilandi — ${res.topic.questionCount} ta savol`, 'success', 5000);
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
        if (!replace) nameInput.focus();
      }
    };
    const many = n > 1 && k < n;
    const modal = openModal({
      title: replace ? `Mavzuni yangilash: ${replace.name}` : n > 1 ? `Yangi mavzu (${k}/${n})` : 'Yangi mavzu',
      body,
      wide: true,
      onClose: () => resolve(result),
      actions: [
        many ? { text: 'Hammasini bekor qilish', onClick: (m) => { result = 'stop'; m.close(); } } : null,
        { text: many ? 'Bu faylni oʻtkazish' : 'Bekor qilish' },
        parsed.count ? { text: replace ? 'Almashtirish' : 'Saqlash', kind: 'primary', icon: 'check', onClick: save } : null,
      ],
    });
    nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        save(modal);
      }
    });
    if (!replace) setTimeout(() => nameInput.select(), 60);
  });
}

async function viewQuestions(t) {
  const listEl = h('div', spinner());
  openModal({ title: t.name, body: listEl, wide: true, actions: [{ text: 'Yopish' }] });
  try {
    const { questions } = await api(`/api/admin/topics/${t.id}/questions`);
    listEl.replaceChildren(h('p.muted.small', `${questions.length} ta savol (fayldagi tartibda). Toʻgʻri javoblar yashil rangda.`), h('ol.preview-list', questions.map(questionPreview)));
  } catch (e) {
    listEl.replaceChildren(h('div.alert.error', e.message));
  }
}

// ======================================================= foydalanuvchilar
const FILTERS = [
  ['all', 'Hammasi'],
  ['admins', 'Adminlar'],
  ['members', 'Foydalanuvchilar'],
  ['online', 'Onlayn'],
  ['blocked', 'Bloklangan'],
];

function usersSection(body, ctx, state, query) {
  let users = null;
  let filter = 'all';
  const search = searchBox('Login boʻyicha qidirish', () => paint());
  const filters = h('div.adm-filters', { role: 'tablist' });
  const list = h('div', spinner());
  const regBox = h('div.adm-reg-slot');
  body.append(
    h('div.card.adm-quick',
      h('div.adm-quick-actions', h('button.btn.primary', { type: 'button', onclick: () => createUser() }, icon('userPlus', 16), 'Foydalanuvchi qoʻshish')),
      regBox),
    h('div.adm-toolbar', search.el, filters),
    list);

  state.overview.then((data) => {
    if (state.alive) regBox.replaceChildren(registrationSwitch(data.settings.registrationOpen));
  }).catch(() => {});

  const isOnline = (u) => (live.presence.users || []).some((p) => p.id === u.id) || (live.status !== 'online' && u.online);
  const match = {
    all: () => true,
    admins: (u) => u.isAdmin,
    members: (u) => !u.isAdmin,
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
        paint();
      },
    }, label, h('span.adm-filter-n', String(users.filter(match[id]).length)))));
    const q = search.value().toLocaleLowerCase();
    const shown = users.filter((u) => match[filter](u) && (!q || u.login.toLocaleLowerCase().includes(q)));
    list.replaceChildren(shown.length
      ? h('div.card.table-card', h('div.table-wrap', h('table.table.adm-table.adm-users',
        h('thead', h('tr',
          h('th', 'Foydalanuvchi'), h('th', 'Rol'), h('th.hide-sm', 'Faollik'), h('th.hide-sm', 'Oxirgi kirish'), h('th.right', 'Amallar'))),
        h('tbody', shown.map(row)))))
      : h('div.card.muted.center', 'Hech kim topilmadi.'));
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
        u.isAdmin ? h('span.badge.admin', icon('shield', 11), 'admin') : h('span.badge.neutral', 'foydalanuvchi'),
        u.blocked ? h('span.badge.bad', icon('lock', 11), 'bloklangan') : null)),
      h('td.hide-sm.small', h('span.adm-activity', { title: 'duel · mashgʻulot · Balloon Pop' },
        h('span', icon('swords', 13), String(u.duels)), h('span', icon('book', 13), String(u.practices)), h('span', icon('balloon', 13), String(u.balloonGames)))),
      h('td.hide-sm.small.nowrap', online ? h('span.adm-online', 'hozir onlayn') : fmtAgo(u.lastSeenAt)),
      h('td.right.nowrap',
        self ? null : btn('shield', u.isAdmin ? 'Admin huquqini olish' : 'Admin qilish', () => toggleAdmin(u), u.isAdmin ? '.on' : ''),
        btn('key', 'Parolni yangilash', () => resetPassword(u)),
        self ? null : btn(u.blocked ? 'unlock' : 'lock', u.blocked ? 'Blokdan chiqarish' : 'Bloklash', () => toggleBlock(u), u.blocked ? '.on' : ''),
        self ? null : btn('trash', 'Oʻchirish', () => remove(u), '.danger')));
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
    const admin = h('input', { type: 'checkbox' });
    const err = h('div.field-error');
    const submit = async (m) => {
      err.textContent = '';
      const body = { login: login.value.trim(), password: pass.input.value.trim(), isAdmin: admin.checked };
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
        h('label.check', admin, h('span', 'Administrator (test yuklash va foydalanuvchilarni boshqarish huquqi)')),
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
  if (query.get('new')) createUser();
  state.cleanups.push(live.on('change', (kind) => {
    if (kind === 'presence' && users) paint();
  }));
}

// ============================================================ yordamchilar
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
