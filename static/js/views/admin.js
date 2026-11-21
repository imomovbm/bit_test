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
  else ({ overview: overviewSection, topics: topicsSection, users: usersSection })[section.id](body, ctx, state, query);
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
  return u.isAdmin ? h('span.badge.admin', 'admin') : null;
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
function topicsSection(body, ctx, state) {
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

  const search = searchBox('Mavzu nomi boʻyicha qidirish', () => paint());
  const list = h('div', spinner());
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
          h('thead', h('tr', h('th', 'Mavzu'), h('th', 'Holat'), h('th.num', 'Savollar'), h('th.hide-sm', 'Variantlar'), h('th.hide-sm', 'Yaratilgan'), h('th.right', 'Amallar'))),
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
    const btn = (ic, title, onclick, cls = '') => h(`button.icon-btn${cls}`, { type: 'button', title, 'aria-label': title, onclick }, icon(ic, 17));
    const href = `#/admin/topics/${t.id}`;
    return h(`tr${t.active ? '' : '.is-inactive'}`,
      h('td.adm-td-main', h('div.topic-cell', h('a.adm-topic-link', { href }, t.name), h('span.small.muted', t.sourceFile || (t.questionCount ? 'qoʻlda kiritilgan' : 'savol qoʻshilmagan')))),
      h('td.adm-td-role', activeSwitch(t, () => paint())),
      h('td.num.adm-td-count', String(t.questionCount), h('span.adm-sm-only', ' ta savol')),
      h('td.hide-sm', h('label.switch', { title: 'Javob variantlarini har safar aralashtirish' }, sw, h('span.slider'), h('span.small', 'aralash'))),
      h('td.hide-sm.small.nowrap', fmtDate(t.createdAt), t.createdBy ? h('div.muted', t.createdBy) : null),
      h('td.right.nowrap',
        h('a.icon-btn', { href, title: 'Savollarni boshqarish', 'aria-label': `Savollarni boshqarish: ${t.name}` }, icon('edit', 17)),
        h('a.icon-btn', { href: `/api/admin/topics/${t.id}/export`, download: `${t.name}.txt`, title: '.txt fayl sifatida yuklab olish', 'aria-label': 'Yuklab olish' }, icon('download', 17)),
        btn('trash', 'Oʻchirish', () => remove(t), '.danger')));
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
async function reviewFile(file, { k = 1, n = 1, replace = null, append = null } = {}) {
  const target = replace || append; // mavjud mavzu bilan ishlash (yangi mavzu emas)
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
      append && parsed.count
        ? h('div.alert.info', icon('plus', 18), h('span', `${parsed.count} ta savol «${append.name}» mavzusi oxiriga qoʻshiladi (hozir ${append.questionCount} ta).`))
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
          toast(`${res.added} ta savol qoʻshildi — jami ${res.topic.questionCount} ta`, 'success', 5000);
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
      title: replace ? `Mavzuni yangilash: ${replace.name}` : append ? `Savollar qoʻshish: ${append.name}` : n > 1 ? `Yangi mavzu (${k}/${n})` : 'Yangi mavzu',
      body,
      wide: true,
      onClose: () => resolve(result),
      actions: [
        many ? { text: 'Hammasini bekor qilish', onClick: (m) => { result = 'stop'; m.close(); } } : null,
        { text: many ? 'Bu faylni oʻtkazish' : 'Bekor qilish' },
        parsed.count ? { text: replace ? 'Almashtirish' : append ? 'Qoʻshish' : 'Saqlash', kind: 'primary', icon: 'check', onClick: save } : null,
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
  const head = h('div');
  const search = searchBox('Savol yoki variant matni boʻyicha qidirish', () => paint());
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
        h('button.btn.primary', { type: 'button', onclick: () => questionDialog(tid, null, reload) }, icon('plus', 16), 'Savol qoʻshish'),
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
        h('button.btn.primary', { type: 'button', onclick: () => questionDialog(tid, null, reload) }, icon('plus', 16), 'Birinchi savolni qoʻshish')));
      return;
    }
    list.replaceChildren(shown.length
      ? h('ol.preview-list.adm-qlist', shown.map(({ item, n }) => h('li.preview-q',
        h('div.preview-text', h('span.review-n', String(n)), h('span', item.text),
          h('span.adm-q-tools',
            h('button.icon-btn', { type: 'button', title: 'Tahrirlash', 'aria-label': `${n}-savolni tahrirlash`, onclick: () => questionDialog(tid, item, reload) }, icon('edit', 16)),
            h('button.icon-btn.danger', { type: 'button', title: 'Oʻchirish', 'aria-label': `${n}-savolni oʻchirish`, onclick: () => removeQuestion(item, n) }, icon('trash', 16)))),
        h('ul.review-opts', item.options.map((o, j) => h('li', { class: j === item.correct ? 'is-correct' : '' }, h('span.opt-key.sm', LETTERS[j]), h('span.review-opt', o)))))))
      : h('div.card.muted.center', 'Hech narsa topilmadi.'));
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
    const ok = await confirmDialog({ title: `${n}-savolni oʻchirish`, message: `«${item.text.slice(0, 120)}» savoli oʻchiriladi.`, okText: 'Oʻchirish', danger: true });
    if (!ok) return;
    try {
      await api(`/api/admin/topics/${tid}/questions/${item.id}`, { method: 'DELETE' });
      toast('Savol oʻchirildi', 'success');
      reload();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  reload();
}

/** Ko'p variantli savolni qo'lda qo'shish yoki tahrirlash (2–10 variant, bitta to'g'ri javob). */
function questionDialog(tid, item, onSaved) {
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
      await api(item ? `/api/admin/topics/${tid}/questions/${item.id}` : `/api/admin/topics/${tid}/questions`, { method: item ? 'PUT' : 'POST', body });
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
  setTimeout(() => text.focus(), 60);
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
  const manage = !!ctx.user.isSuperadmin; // foydalanuvchilarni faqat bosh administrator boshqaradi
  const search = searchBox('Login boʻyicha qidirish', () => paint());
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
          'Foydalanuvchilarni (bloklash, parolni tiklash, admin qilish) faqat bosh administrator boshqaradi. Siz roʻyxatni koʻrishingiz mumkin.')),
        regBox),
    h('div.adm-toolbar', search.el, filters),
    list);

  state.overview.then((data) => {
    if (state.alive) regBox.replaceChildren(registrationSwitch(data.settings.registrationOpen, manage));
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
          h('th', 'Foydalanuvchi'), h('th', 'Rol'), h('th.hide-sm', 'Faollik'), h('th.hide-sm', 'Oxirgi kirish'), manage ? h('th.right', 'Amallar') : null)),
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
        u.isSuperadmin
          ? h('span.badge.owner', icon('crown', 11), 'bosh admin')
          : u.isAdmin ? h('span.badge.admin', icon('shield', 11), 'admin') : h('span.badge.neutral', 'foydalanuvchi'),
        u.blocked ? h('span.badge.bad', icon('lock', 11), 'bloklangan') : null)),
      h('td.hide-sm.small', h('span.adm-activity', { title: 'duel · mashgʻulot · Balloon Pop' },
        h('span', icon('swords', 13), String(u.duels)), h('span', icon('book', 13), String(u.practices)), h('span', icon('balloon', 13), String(u.balloonGames)))),
      h('td.hide-sm.small.nowrap', online ? h('span.adm-online', 'hozir onlayn') : fmtAgo(u.lastSeenAt)),
      manage ? h('td.right.nowrap',
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
  if (manage && query.get('new')) createUser();
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
