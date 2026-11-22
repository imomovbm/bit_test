// O'rganish (bir kishilik mashq) rejimi: 10, 30, 50 yoki barcha savollar, vaqt chegarasisiz.
import { h, icon, toast, openModal, confirmDialog, spinner, emptyState, progressRing, shuffleArray, beep, LETTERS } from '../lib.js';
import { api } from '../api.js';
import { topicBrowser } from '../topic-browser.js';

const STORE_KEY = 'td-practice';
let session = restore();

function restore() {
  try {
    const s = JSON.parse(sessionStorage.getItem(STORE_KEY) || 'null');
    return s && Array.isArray(s.questions) && s.questions.length ? s : null;
  } catch {
    return null;
  }
}

function persist() {
  try {
    if (session) sessionStorage.setItem(STORE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORE_KEY);
  } catch {
    /* sessionStorage to'lgan bo'lishi mumkin — e'tiborsiz */
  }
}

export function practiceView(root, params, ctx, query) {
  if (session && session.userId !== ctx.user.id) {
    // shu brauzer oynasida avval boshqa foydalanuvchi mashq qilgan — uning sessiyasini ko'rsatmaymiz
    session = null;
    persist();
  }
  if (params.id) return sessionView(root, Number(params.id), ctx, query);
  return listView(root, ctx);
}

// ============================================================ mavzular
function listView(root, ctx) {
  const resume = h('div');
  // katalog serverdan sahifalab olinadi (qidiruv, davr bo'yicha tartib) — barcha mavzular birdaniga yuklanmaydi
  const browser = topicBrowser({ user: ctx.user, variant: 'practice', onPick: (t) => openSetup(t, ctx), storageKey: 'td-practice-tab', title: 'Mavzuni tanlang' });
  root.append(h('section.screen.practice-list',
    h('div.page-head', h('div',
      h('h1', 'Oʻrganish'),
      h('p.muted', 'Bir kishilik mashq: vaqt chegarasi yoʻq, har bir javobdan keyin toʻgʻri javob koʻrsatiladi.'))),
    resume,
    browser.el));

  if (session && !session.finished) {
    const answered = session.answers.filter(Boolean).length;
    resume.replaceChildren(h('div.card.resume-card',
      h('span.resume-ic', icon('book', 20)),
      h('div.resume-text', h('b', 'Tugallanmagan mashq'), h('span.muted', `${session.topicName} — ${answered}/${session.questions.length} ta javob berilgan`)),
      h('a.btn.primary.sm', { href: `#/practice/${session.topicId}?n=${encodeURIComponent(session.n)}&order=${session.order}` }, 'Davom ettirish'),
      h('button.btn.ghost.sm', { type: 'button', onclick: () => { session = null; persist(); resume.replaceChildren(); } }, 'Bekor qilish')));
  }

  return () => browser.destroy();
}

function openSetup(topic, ctx) {
  const total = topic.questionCount;
  let selected = total >= 10 ? '10' : 'all';
  const shuffle = h('input', { type: 'checkbox', checked: true });
  const choice = (value, label, sub, disabled) => {
    const btn = h('button', { type: 'button', class: 'choice', disabled, title: disabled ? `Bu mavzuda faqat ${total} ta savol bor` : '' },
      h('b', label), h('span', sub));
    btn.dataset.value = value;
    btn.addEventListener('click', () => {
      selected = value;
      paint();
    });
    return btn;
  };
  const buttons = [
    choice('10', '10 ta', 'qisqa mashq', total < 10),
    choice('30', '30 ta', 'oʻrtacha', total < 30),
    choice('50', '50 ta', 'chuqur', total < 50),
    choice('all', 'Barchasi', `${total} ta savol`, false),
  ];
  const paint = () => buttons.forEach((b) => b.classList.toggle('selected', b.dataset.value === selected));
  paint();
  openModal({
    title: 'Nechta savol yechasiz?',
    body: [
      h('p.modal-sub', icon('book', 16), topic.name),
      h('div.choice-grid', buttons),
      h('label.check', shuffle, h('span', 'Savollarni aralash (tasodifiy) tartibda berish')),
      h('p.small.muted', 'Vaqt chegarasi yoʻq. Har bir javobdan keyin toʻgʻri javob koʻrsatiladi.'),
    ],
    actions: [
      { text: 'Bekor qilish' },
      {
        text: 'Boshlash',
        kind: 'primary',
        icon: 'right',
        onClick: (m) => {
          m.close();
          session = null;
          persist();
          ctx.navigate(`/practice/${topic.id}?n=${selected}&order=${shuffle.checked ? 'random' : 'seq'}`);
        },
      },
    ],
  });
}

// ============================================================== mashq
function sessionView(root, topicId, ctx, query) {
  const n = query.get('n') || 'all';
  const order = query.get('order') === 'seq' ? 'seq' : 'random';
  const key = `${topicId}|${n}|${order}`;
  const wrap = h('section.screen.practice');
  root.append(wrap);
  let alive = true;

  if (session && session.key === key) {
    draw();
  } else if (n === 'retry') {
    setTimeout(() => ctx.navigate('/practice'), 0);
  } else {
    wrap.append(h('div.card', spinner('Savollar tayyorlanmoqda…')));
    api(`/api/topics/${topicId}/practice?count=${encodeURIComponent(n)}&order=${order}`)
      .then((res) => {
        if (!alive) return;
        if (!res.questions.length) throw new Error('Bu mavzuda savollar yoʻq');
        session = { userId: ctx.user.id, key, n, order, topicId, topicName: res.topic.name, questions: res.questions, idx: 0, answers: [], finished: false, saved: false };
        persist();
        draw();
      })
      .catch((e) => {
        if (alive) wrap.replaceChildren(emptyState('alert', 'Mashqni boshlab boʻlmadi', e.message, h('a.btn.primary', { href: '#/practice' }, 'Mavzularga qaytish')));
      });
  }

  function draw() {
    if (!alive || !session) return;
    if (session.finished) drawResult();
    else drawQuestion();
  }

  function stats() {
    const answered = session.answers.filter(Boolean).length;
    const correct = session.answers.filter((a) => a && a.correct).length;
    return { total: session.questions.length, answered, correct, wrong: answered - correct };
  }

  function drawQuestion() {
    const s = session;
    const i = s.idx;
    const q = s.questions[i];
    const a = s.answers[i];
    const st = stats();
    const isLast = i === st.total - 1;
    const buttons = q.options.map((text, j) => {
      let cls = 'option';
      if (a) cls += j === q.correct ? ' correct' : j === a.choice ? ' wrong' : ' dim';
      return h('button', { type: 'button', class: cls, disabled: !!a, onclick: () => answer(j) },
        h('span.opt-key', LETTERS[j] || String(j + 1)), h('span.opt-text', text), h('span.opt-mark'));
    });
    let feedback = null;
    if (a) {
      feedback = a.correct
        ? h('div.feedback.good', icon('check', 18), h('b', 'Toʻgʻri javob!'))
        : h('div.feedback.bad', icon('x', 18), h('div', h('b', 'Notoʻgʻri. '), 'Toʻgʻri javob: ', h('span.fb-correct', q.options[q.correct])));
    }
    const nextBtn = a
      ? h('button.btn.primary', { type: 'button', onclick: next }, isLast ? 'Natijani koʻrish' : 'Keyingi', icon('right', 16))
      : h('button.btn.ghost', { type: 'button', onclick: next }, isLast ? 'Yakunlash' : 'Oʻtkazib yuborish', icon('right', 16));
    wrap.replaceChildren(
      h('div.practice-top',
        h('a.back-link', { href: '#/practice' }, icon('left', 16), 'Mavzular'),
        h('div.practice-title', s.topicName),
        h('button.btn.ghost.sm', { type: 'button', onclick: finishEarly }, icon('flag', 14), 'Yakunlash')),
      h('div.practice-progress',
        h('div.bar.lg', h('div.bar-fill', { style: { width: `${(st.answered / st.total) * 100}%` } })),
        h('div.practice-stats',
          h('span', 'Savol ', h('b', String(i + 1)), ` / ${st.total}`),
          h('span.good', icon('check', 14), String(st.correct)),
          h('span.bad', icon('x', 14), String(st.wrong)))),
      h('div.qcard.anim-in', h('div.q-text', q.text), h('div.options', buttons), feedback),
      h('div.practice-nav',
        h('button.btn.ghost', { type: 'button', disabled: i === 0, onclick: prev }, icon('left', 16), 'Oldingi'),
        nextBtn),
      h('p.small.muted.center.kbd-hint', 'Klaviatura: 1–4 yoki A–D — javob, Enter / → — keyingi, ← — oldingi'));
    if (a) nextBtn.focus({ preventScroll: true });
  }

  function answer(j) {
    const s = session;
    if (!s || s.finished || s.answers[s.idx]) return;
    const q = s.questions[s.idx];
    s.answers[s.idx] = { choice: j, correct: j === q.correct };
    beep(j === q.correct ? 'correct' : 'wrong');
    persist();
    draw();
  }

  function next() {
    const s = session;
    if (s.idx < s.questions.length - 1) {
      s.idx += 1;
      persist();
      draw();
      window.scrollTo({ top: 0 });
    } else {
      finish();
    }
  }

  function prev() {
    if (session.idx > 0) {
      session.idx -= 1;
      persist();
      draw();
    }
  }

  async function finishEarly() {
    const st = stats();
    if (st.answered < st.total) {
      const ok = await confirmDialog({
        title: 'Mashqni yakunlaysizmi?',
        message: `${st.total - st.answered} ta savolga javob berilmagan. Ular natijada “oʻtkazilgan” deb hisoblanadi.`,
        okText: 'Yakunlash',
        cancelText: 'Davom etish',
      });
      if (!ok || !alive) return;
    }
    finish();
  }

  function finish() {
    session.finished = true;
    persist();
    draw();
    window.scrollTo({ top: 0 });
  }

  function drawResult() {
    const s = session;
    const st = stats();
    const skipped = st.total - st.answered;
    const percent = st.total ? Math.round((st.correct / st.total) * 100) : 0;
    const [grade, gradeCls] = percent >= 86 ? ['Aʼlo!', 'great'] : percent >= 71 ? ['Yaxshi', 'good'] : percent >= 55 ? ['Qoniqarli', 'ok'] : ['Yana mashq qiling', 'low'];
    if (!s.saved) {
      s.saved = true;
      persist();
      api('/api/practice/results', { method: 'POST', body: { topicId: s.topicId, total: st.total, answered: st.answered, correct: st.correct } })
        .catch(() => toast('Natijani saqlab boʻlmadi', 'warning'));
    }
    const mistakes = s.questions.map((q, i) => ({ q, a: s.answers[i], i })).filter((x) => !x.a || !x.a.correct);
    const stat = (label, value, cls = '') => h(`div.mini-stat${cls ? `.${cls}` : ''}`, h('b', String(value)), h('span', label));
    wrap.replaceChildren(
      h('div.card.practice-result.anim-in',
        progressRing(percent, gradeCls),
        h('h1', grade),
        h('p.muted', s.topicName),
        h('div.mini-stats', stat('toʻgʻri', st.correct, 'good'), stat('notoʻgʻri', st.wrong, 'bad'), stat('oʻtkazilgan', skipped), stat('jami', st.total)),
        h('div.result-actions',
          mistakes.length ? h('button.btn.accent', { type: 'button', onclick: () => retry(mistakes.map((x) => x.q)) }, icon('target', 16), `Xatolar ustida ishlash (${mistakes.length})`) : null,
          h('button.btn.primary', { type: 'button', onclick: restart }, icon('refresh', 16), 'Qaytadan'),
          h('a.btn.ghost', { href: '#/practice' }, 'Boshqa mavzu'))),
      mistakes.length
        ? h('div.card', h('h2.card-title', 'Xatolar va oʻtkazilgan savollar'), h('ol.review-list', mistakes.map(({ q, a, i }) => h(`li.review-item.${a ? 'bad' : 'skip'}`,
          h('div.review-q', h('span.review-n', String(i + 1)), h('span.review-text', q.text)),
          h('ul.review-opts', q.options.map((o, j) => h('li', { class: j === q.correct ? 'is-correct' : a && j === a.choice ? 'is-wrong' : '' },
            h('span.opt-key.sm', LETTERS[j]), h('span.review-opt', o), a && j === a.choice ? h('span.tag.me', 'siz') : null))),
          a ? null : h('div.review-note', 'Javob berilmagan')))))
        : h('div.card.center.all-correct', icon('trophy', 22), h('b', ' Barcha savollarga toʻgʻri javob berdingiz!')));
  }

  function retry(questions) {
    session = {
      userId: ctx.user.id, key: `${topicId}|retry|random`, n: 'retry', order: 'random', topicId, topicName: session.topicName,
      questions: shuffleArray(questions.slice()), idx: 0, answers: [], finished: false, saved: false,
    };
    persist();
    ctx.navigate(`/practice/${topicId}?n=retry&order=random`);
  }

  function restart() {
    if (session.n === 'retry') {
      Object.assign(session, { idx: 0, answers: [], finished: false, saved: false });
      shuffleArray(session.questions);
      persist();
      draw();
      return;
    }
    session = null;
    persist();
    ctx.navigate(`/practice/${topicId}?n=${encodeURIComponent(n)}&order=${order}`);
  }

  function onKey(e) {
    if (!session || session.finished || session.key !== key) return;
    if (document.querySelector('.modal-overlay.show') || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = e.target && e.target.tagName;
    const k = e.key.toLowerCase();
    const q = session.questions[session.idx];
    if (!session.answers[session.idx]) {
      let i = '123456789'.indexOf(k);
      if (i < 0) i = 'abcdefghij'.indexOf(k);
      if (i >= 0 && i < q.options.length) {
        e.preventDefault();
        answer(i);
        return;
      }
    }
    if ((k === 'enter' && tag !== 'BUTTON' && tag !== 'A') || k === 'arrowright') {
      if (session.answers[session.idx]) {
        e.preventDefault();
        next();
      }
    } else if (k === 'arrowleft') {
      e.preventDefault();
      prev();
    }
  }
  document.addEventListener('keydown', onKey);

  return () => {
    alive = false;
    document.removeEventListener('keydown', onKey);
  };
}
