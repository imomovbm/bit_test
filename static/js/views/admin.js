// Boshqaruv: test fayllarini yuklash, mavzular va foydalanuvchilar.
import { h, icon, avatar, toast, openModal, confirmDialog, promptDialog, readTextFile, spinner, emptyState, fmtDate, LETTERS } from '../lib.js';
import { api } from '../api.js';

const FORMAT_EXAMPLE = `Savol matni
====
Notoʻgʻri javob
====
#Toʻgʻri javob
====
Notoʻgʻri javob
====
Notoʻgʻri javob
++++
Keyingi savol matni
====
#Toʻgʻri javob
====
Notoʻgʻri javob
++++`;

export function adminView(root, params, ctx, query) {
  const tab = query.get('tab') === 'users' ? 'users' : 'topics';
  const body = h('div');
  const tabBtn = (id, label, ic) => h(`a.tab${tab === id ? '.active' : ''}`, { href: id === 'users' ? '#/admin?tab=users' : '#/admin' }, icon(ic, 16), label);
  root.append(h('section.screen.admin',
    h('div.page-head', h('div', h('h1', 'Boshqaruv'), h('p.muted', 'Test fayllarini yuklash, mavzular va foydalanuvchilarni boshqarish.'))),
    h('div.tabs', tabBtn('topics', 'Testlar', 'file'), tabBtn('users', 'Foydalanuvchilar', 'users')),
    body));
  const state = { alive: true };
  if (tab === 'users') usersTab(body, ctx, state);
  else topicsTab(body, state);
  return () => {
    state.alive = false;
  };
}

// ================================================================ testlar
function topicsTab(body, state) {
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
    h('div.section-head', h('h2', 'Mavzular'), h('button.btn.ghost.sm', { type: 'button', onclick: () => loadList() }, icon('refresh', 16), 'Yangilash')),
    list);

  async function handleFiles(files) {
    const txt = files.filter((f) => /\.txt$/i.test(f.name) || f.type === 'text/plain');
    if (!txt.length) {
      if (files.length) toast('Faqat .txt formatidagi fayllarni yuklash mumkin', 'error');
      return;
    }
    if (txt.length < files.length) toast('.txt boʻlmagan fayllar oʻtkazib yuborildi', 'warning');
    for (let i = 0; i < txt.length; i++) {
      const res = await reviewFile(txt[i], i + 1, txt.length);
      if (res === 'saved' && state.alive) loadList();
      if (res === 'stop') break;
    }
  }

  async function loadList() {
    try {
      const { topics } = await api('/api/admin/topics');
      if (!state.alive) return;
      if (!topics.length) {
        list.replaceChildren(emptyState('file', 'Hali mavzu yoʻq', 'Yuqoridagi maydon orqali birinchi test faylini yuklang.'));
        return;
      }
      list.replaceChildren(h('div.card.table-card', h('div.table-wrap', h('table.table',
        h('thead', h('tr', h('th', 'Mavzu'), h('th.num', 'Savollar'), h('th.hide-sm', 'Variantlar'), h('th.hide-sm', 'Yuklangan'), h('th.right', 'Amallar'))),
        h('tbody', topics.map((t) => topicRow(t)))))));
    } catch (e) {
      if (state.alive) list.replaceChildren(emptyState('wifiOff', 'Roʻyxatni yuklab boʻlmadi', e.message));
    }
  }

  function topicRow(t) {
    const sw = h('input', { type: 'checkbox', checked: t.shuffle, 'aria-label': 'Variantlarni aralashtirish' });
    sw.addEventListener('change', async () => {
      try {
        await api(`/api/admin/topics/${t.id}`, { method: 'PATCH', body: { shuffle: sw.checked } });
        toast(sw.checked ? 'Variantlar endi aralashtiriladi' : 'Variantlar fayldagi tartibda beriladi', 'success');
      } catch (e) {
        sw.checked = !sw.checked;
        toast(e.message, 'error');
      }
    });
    return h('tr',
      h('td', h('div.topic-cell', h('b', t.name), h('span.small.muted', t.sourceFile || ''))),
      h('td.num', String(t.questionCount)),
      h('td.hide-sm', h('label.switch', { title: 'Javob variantlarini har safar aralashtirish' }, sw, h('span.slider'), h('span.small', 'aralash'))),
      h('td.hide-sm.small.nowrap', fmtDate(t.createdAt), t.createdBy ? h('div.muted', t.createdBy) : null),
      h('td.right.nowrap',
        h('button.icon-btn', { type: 'button', title: 'Savollarni koʻrish', 'aria-label': 'Savollarni koʻrish', onclick: () => viewQuestions(t) }, icon('eye', 17)),
        h('button.icon-btn', { type: 'button', title: 'Nomini oʻzgartirish', 'aria-label': 'Nomini oʻzgartirish', onclick: () => rename(t) }, icon('edit', 17)),
        h('button.icon-btn.danger', { type: 'button', title: 'Oʻchirish', 'aria-label': 'Oʻchirish', onclick: () => remove(t) }, icon('trash', 17))));
  }

  async function rename(t) {
    const name = await promptDialog({ title: 'Mavzu nomini oʻzgartirish', label: 'Yangi nom', value: t.name, validate: (v) => (v ? '' : 'Nomni kiriting') });
    if (!name || name === t.name) return;
    try {
      await api(`/api/admin/topics/${t.id}`, { method: 'PATCH', body: { name } });
      toast('Mavzu nomi oʻzgartirildi', 'success');
      loadList();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function remove(t) {
    const ok = await confirmDialog({
      title: 'Mavzuni oʻchirish',
      message: `«${t.name}» mavzusi va undagi ${t.questionCount} ta savol butunlay oʻchiriladi. Duel tarixi saqlanib qoladi. Davom etasizmi?`,
      okText: 'Oʻchirish',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/admin/topics/${t.id}`, { method: 'DELETE' });
      toast('Mavzu oʻchirildi', 'success');
      loadList();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  loadList();
}

function suggestName(fileName) {
  return fileName.replace(/\.txt$/i, '').replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120);
}

function questionPreview(q, i) {
  return h('li.preview-q',
    h('div.preview-text', h('span.review-n', String(i + 1)), h('span', q.text)),
    h('ul.review-opts', q.options.map((o, j) => h('li', { class: j === q.correct ? 'is-correct' : '' }, h('span.opt-key.sm', LETTERS[j]), h('span.review-opt', o)))));
}

/** Bitta faylni tekshirib, mavzu nomini so'raydi va saqlaydi. 'saved' | 'skip' | 'stop' qaytaradi. */
async function reviewFile(file, k, n) {
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
      errorsBlock,
      parsed.preview.length
        ? h('details.preview', h('summary', icon('eye', 16), `Dastlabki ${parsed.preview.length} ta savolni koʻrish`), h('ol.preview-list', parsed.preview.map(questionPreview)))
        : null,
      parsed.count ? h('label.field', h('span.field-label', 'Mavzu nomi'), nameInput, h('span.field-hint', 'Bu nom duel va oʻrganish boʻlimlarida koʻrinadi.')) : null,
      parsed.count ? h('label.check', shuffle, h('span', 'Javob variantlari tartibini har safar aralashtirish')) : null,
      err,
    ];
    const save = async (m) => {
      const name = nameInput.value.trim();
      if (!name) {
        err.textContent = 'Mavzu nomini kiriting';
        err.hidden = false;
        nameInput.focus();
        return;
      }
      err.hidden = true;
      try {
        const res = await api('/api/admin/topics', { method: 'POST', body: { name, content: text, shuffle: shuffle.checked, fileName: file.name } });
        toast(`«${res.topic.name}» saqlandi — ${res.topic.questionCount} ta savol`, 'success', 5000);
        result = 'saved';
        m.close();
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
        nameInput.focus();
      }
    };
    const modal = openModal({
      title: n > 1 ? `Yangi mavzu (${k}/${n})` : 'Yangi mavzu',
      body,
      wide: true,
      dismissible: true,
      onClose: () => resolve(result),
      actions: [
        n > 1 && k < n ? { text: 'Hammasini bekor qilish', onClick: (m) => { result = 'stop'; m.close(); } } : null,
        { text: n > 1 && k < n ? 'Bu faylni oʻtkazish' : 'Bekor qilish' },
        parsed.count ? { text: 'Saqlash', kind: 'primary', icon: 'check', onClick: save } : null,
      ],
    });
    nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        save(modal);
      }
    });
    setTimeout(() => nameInput.select(), 60);
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

// ========================================================== foydalanuvchilar
function usersTab(body, ctx, state) {
  const list = h('div', spinner());
  body.append(
    h('div.alert.info', icon('shield', 18), h('span', 'Birinchi roʻyxatdan oʻtgan foydalanuvchi avtomatik administrator boʻladi. Bu yerda boshqa foydalanuvchilarga ham admin huquqini berishingiz mumkin.')),
    list);

  async function load() {
    try {
      const { users } = await api('/api/admin/users');
      if (!state.alive) return;
      list.replaceChildren(h('div.card.table-card', h('div.table-wrap', h('table.table',
        h('thead', h('tr', h('th', 'Foydalanuvchi'), h('th', 'Rol'), h('th.num.hide-sm', 'Duellar'), h('th.num.hide-sm', 'Mashqlar'), h('th.hide-sm', 'Roʻyxatdan oʻtgan'), h('th.right', 'Amallar'))),
        h('tbody', users.map(row))))));
    } catch (e) {
      if (state.alive) list.replaceChildren(emptyState('wifiOff', 'Roʻyxatni yuklab boʻlmadi', e.message));
    }
  }

  function row(u) {
    const self = u.id === ctx.user.id;
    return h('tr',
      h('td', h('span.user-cell', avatar(u.login, 'xs'), h('b', u.login), u.online ? h('span.live-dot', { title: 'onlayn' }) : null, self ? h('span.tag', 'siz') : null)),
      h('td', u.isAdmin ? h('span.badge.admin', 'admin') : h('span.badge.neutral', 'talaba')),
      h('td.num.hide-sm', String(u.duels)),
      h('td.num.hide-sm', String(u.practices)),
      h('td.hide-sm.small.nowrap', fmtDate(u.createdAt)),
      h('td.right.nowrap',
        self ? null : h('button.icon-btn', { type: 'button', title: u.isAdmin ? 'Admin huquqini olish' : 'Admin qilish', 'aria-label': 'Admin huquqi', onclick: () => toggleAdmin(u) }, icon('shield', 17)),
        h('button.icon-btn', { type: 'button', title: 'Parolni yangilash', 'aria-label': 'Parolni yangilash', onclick: () => resetPassword(u) }, icon('key', 17)),
        self ? null : h('button.icon-btn.danger', { type: 'button', title: 'Oʻchirish', 'aria-label': 'Oʻchirish', onclick: () => remove(u) }, icon('trash', 17))));
  }

  async function toggleAdmin(u) {
    const ok = await confirmDialog({
      title: u.isAdmin ? 'Admin huquqini olish' : 'Admin qilish',
      message: u.isAdmin ? `${u.login} endi test yuklay olmaydi va boshqaruv boʻlimini koʻrmaydi.` : `${u.login} test yuklash va foydalanuvchilarni boshqarish huquqini oladi.`,
      okText: u.isAdmin ? 'Huquqni olish' : 'Admin qilish',
    });
    if (!ok) return;
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'PATCH', body: { isAdmin: !u.isAdmin } });
      toast('Saqlandi', 'success');
      load();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function resetPassword(u) {
    const password = await promptDialog({
      title: `${u.login} — yangi parol`,
      label: 'Yangi parol',
      type: 'text',
      hint: 'Foydalanuvchi barcha qurilmalardan chiqarib yuboriladi va yangi parol bilan kiradi.',
      validate: (v) => (v.length >= 4 ? '' : 'Parol kamida 4 ta belgidan iborat boʻlsin'),
    });
    if (!password) return;
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'PATCH', body: { password } });
      toast('Parol yangilandi', 'success');
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function remove(u) {
    const ok = await confirmDialog({
      title: 'Foydalanuvchini oʻchirish',
      message: `${u.login} akkaunti oʻchiriladi. Uning oʻrganish natijalari ham oʻchadi (duel tarixi raqiblarida saqlanadi). Bu amalni qaytarib boʻlmaydi.`,
      okText: 'Oʻchirish',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'DELETE' });
      toast('Foydalanuvchi oʻchirildi', 'success');
      load();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  load();
}
