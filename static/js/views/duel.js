// Duel bo'limi: mavzu tanlash -> raqib kutish (taklif havolasi) -> sanoq -> savollar -> natija.
import { h, icon, avatar, toast, copyText, fmtMs, fmtClock, confirmDialog, spinner, emptyState, LETTERS } from '../lib.js';
import { api } from '../api.js';
import { live } from '../live.js';

const STATUS_TEXT = { idle: 'boʻsh', waiting: 'kutmoqda', duel: 'duelda' };

export function duelView(root, params, ctx) {
  let screen = null;
  let key = null;

  function pick() {
    const d = live.duel;
    if (d) return d.status === 'countdown' ? [`countdown:${d.duelId}`, countdownScreen] : [`play:${d.duelId}`, playScreen];
    if (live.result) return [`result:${live.result.duelId}`, resultScreen];
    const q = live.queue;
    if (q) return [`waiting:${q.topicId}:${q.inviteFor ? q.inviteFor.id : ''}`, waitingScreen];
    return ['lobby', lobbyScreen];
  }

  function sync() {
    const [k, make] = pick();
    if (k === key && screen) {
      if (screen.update) screen.update();
      return;
    }
    if (screen && screen.destroy) screen.destroy();
    key = k;
    screen = make(ctx);
    root.replaceChildren(screen.el);
    window.scrollTo({ top: 0 });
  }

  sync();
  const offChange = live.on('change', sync);
  const offTopics = live.on('topics', () => screen && screen.reload && screen.reload());
  return () => {
    offChange();
    offTopics();
    if (screen && screen.destroy) screen.destroy();
    screen = null;
    // Natija ko'rib bo'lingan bo'lsa, boshqa bo'limga o'tganda uni yopamiz.
    if (key && key.startsWith('result:') && live.result) live.result = null;
  };
}

function rulesStrip() {
  const r = live.rules;
  const item = (ic, text) => h('div.rule', icon(ic, 16), h('span', text));
  return h('div.rules-strip',
    item('file', `${r.duelQuestions} ta savol`),
    item('clock', `har biriga ${r.questionTime} soniya`),
    item('trophy', 'koʻp toʻgʻri javob — gʻolib'),
    item('zap', 'teng boʻlsa — tezroq bajargan'),
    item('flag', `chiqib ketish yoki ${r.afkSeconds} s javobsizlik — magʻlubiyat`));
}

// ================================================================== lobby
function lobbyScreen(ctx) {
  const grid = h('div.topic-grid', spinner('Mavzular yuklanmoqda…'));
  const online = h('div.card.online-card');
  const el = h('section.screen.lobby',
    h('div.page-head',
      h('div',
        h('h1', 'Duel'),
        h('p.muted', 'Mavzuni tanlang — shu mavzuni tanlagan boshqa ishtirokchi bilan duel avtomatik boshlanadi.'))),
    rulesStrip(),
    online,
    h('div.section-head',
      h('h2', 'Mavzular'),
      h('button.btn.ghost.sm', { type: 'button', onclick: () => load() }, icon('refresh', 16), 'Yangilash')),
    grid);

  let topics = null;
  let error = null;

  async function load() {
    try {
      topics = (await api('/api/topics')).topics;
      error = null;
    } catch (e) {
      error = e.message;
    }
    paintGrid();
    paintOnline();
  }

  function paintGrid() {
    if (error) {
      grid.replaceChildren(emptyState('wifiOff', 'Mavzularni yuklab boʻlmadi', error));
      return;
    }
    if (!topics) return;
    if (!topics.length) {
      grid.replaceChildren(emptyState('file', 'Hozircha test mavzulari yoʻq',
        ctx.user.isAdmin ? 'Test faylini yuklang — u shu yerda paydo boʻladi.' : 'Administrator test faylini yuklaganidan keyin mavzular shu yerda paydo boʻladi.',
        ctx.user.isAdmin ? h('a.btn.primary', { href: '#/admin' }, icon('upload', 16), 'Test yuklash') : null));
      return;
    }
    const waiting = live.presence.waiting || {};
    grid.replaceChildren(...topics.map((t) => topicCard(t, waiting[String(t.id)] || 0)));
  }

  function topicCard(t, waitingCount) {
    const n = Math.min(t.questionCount, live.rules.duelQuestions);
    return h('button', { type: 'button', class: `topic-card${waitingCount ? ' hot' : ''}`, onclick: () => live.joinQueue(t.id) },
      h('div.topic-top',
        h('span.topic-icon', icon('swords', 22)),
        waitingCount ? h('span.topic-wait', h('span.pulse-dot'), `${waitingCount} kishi kutmoqda`) : null),
      h('div.topic-name', t.name),
      h('div.topic-meta', `${t.questionCount} ta savol bazada · duelda ${n} ta`),
      h('div.topic-cta', waitingCount ? 'Hoziroq bellashish' : 'Duelga kirish', icon('right', 16)));
  }

  function paintOnline() {
    const p = live.presence;
    const others = (p.users || []).filter((u) => u.id !== ctx.user.id);
    const topicName = (id) => (topics || []).find((t) => t.id === id)?.name;
    online.replaceChildren(
      h('div.online-head',
        h('span.live-dot'),
        h('b', `${Math.max(p.online || 0, live.status === 'online' ? 1 : 0)} kishi onlayn`),
        live.status !== 'online' ? h('span.badge.warn', 'serverga ulanmoqda…') : null),
      others.length
        ? h('div.chips', others.map((u) => h('span.chip', { title: u.status === 'waiting' && topicName(u.topicId) ? `Kutmoqda: ${topicName(u.topicId)}` : u.login },
          avatar(u.login, 'xs'), h('span.chip-name', u.login), h(`span.chip-status.${u.status}`, STATUS_TEXT[u.status] || ''))))
        : h('p.muted.small', 'Hozircha sizdan boshqa hech kim onlayn emas. Mavzuni tanlang — kutish oynasida doʻstingizni chaqirish uchun havola paydo boʻladi.'));
  }

  load();
  paintOnline();
  return {
    el,
    update() {
      paintGrid();
      paintOnline();
    },
    reload: load,
  };
}

// ================================================================ waiting
function inviteUrl(code) {
  const local = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname);
  const base = local && live.rules.lanUrl ? live.rules.lanUrl : location.origin;
  return `${base}/d/${code}`;
}

function inviteCard(q) {
  const url = inviteUrl(q.code);
  const text = `⚔ Sizni «${q.topicName}» mavzusi boʻyicha test duelga chaqiraman! Havolani oching:`;
  const input = h('input.mono', { type: 'text', readonly: true, value: url, 'aria-label': 'Taklif havolasi' });
  input.addEventListener('focus', () => input.select());
  const local = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname);
  return h('div.card.invite-card',
    h('div.invite-head', h('span.invite-ic', icon('link', 18)), h('div', h('b', 'Doʻstingizni duelga chaqiring'), h('p.muted.small', 'Havolani yuboring — doʻstingiz uni ochib, kirishi bilan duel boshlanadi.'))),
    h('div.input-row', input,
      h('button.btn.primary', {
        type: 'button',
        onclick: async () => {
          const copied = await copyText(url);
          toast(copied ? 'Havola nusxalandi' : 'Nusxalab boʻlmadi — havolani qoʻlda belgilang', copied ? 'success' : 'warning');
        },
      }, icon('copy', 16), 'Nusxalash')),
    h('div.share-row',
      h('a.btn.share.tg', { href: `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`, target: '_blank', rel: 'noopener' }, icon('send', 16), 'Telegram'),
      h('a.btn.share.wa', { href: `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`, target: '_blank', rel: 'noopener' }, icon('message', 16), 'WhatsApp'),
      navigator.share
        ? h('button.btn.share', { type: 'button', onclick: () => navigator.share({ title: 'TestDuel', text, url }).catch(() => {}) }, icon('share', 16), 'Boshqa…')
        : null),
    local
      ? h('p.small.muted.invite-note', icon('alert', 14), live.rules.lanUrl
        ? ` Havola tarmoqdagi manzil (${live.rules.lanUrl.replace(/^https?:\/\//, '')}) bilan yaratildi — doʻstingiz shu tarmoqqa (Wi-Fi) ulangan boʻlishi kerak.`
        : ' Sayt localhost orqali ochilgan — bu havola faqat shu kompyuterda ishlaydi.')
      : null);
}

function waitingScreen() {
  const q = live.queue;
  const elapsed = h('span.mono', '0:00');
  const notice = h('div.wait-notice');
  const el = h('section.screen.waiting',
    h('div.radar', h('span.radar-ring'), h('span.radar-ring.r2'), h('span.radar-ring.r3'), h('span.radar-core', icon('swords', 36))),
    h('h1.center', q.inviteFor ? `${q.inviteFor.login} bilan duel` : 'Raqib qidirilmoqda…'),
    h('div.center', h('span.topic-pill', icon('file', 15), q.topicName)),
    h('p.center.muted', `${q.questionCount} ta savol · har biriga ${live.rules.questionTime} soniya · kutish: `, elapsed),
    notice,
    q.inviteFor ? null : inviteCard(q),
    h('div.center', h('button.btn.ghost', { type: 'button', onclick: () => live.leaveQueue() }, icon('x', 16), 'Bekor qilish')));

  const tick = () => {
    elapsed.textContent = fmtClock((Date.now() - (live.queue?.localSince || Date.now())) / 1000);
  };
  tick();
  const timer = setInterval(tick, 1000);

  function paintNotice() {
    const cur = live.queue;
    if (!cur) return;
    if (cur.inviteFor) {
      notice.replaceChildren(cur.inviteFor.online
        ? h('div.alert.info', h('span.spinner.sm'), h('span', `${cur.inviteFor.login} bilan ulanmoqda…`))
        : h('div.alert.warning', icon('wifiOff', 18), h('span', `${cur.inviteFor.login} hozir aloqada emas. U saytga qaytishi bilan duel boshlanadi.`)));
      return;
    }
    const others = Math.max(0, (live.presence.online || 1) - 1);
    notice.replaceChildren(others === 0
      ? h('div.alert.warning', icon('users', 18), h('div', h('b', 'Hozir sizdan boshqa hech kim onlayn emas.'), h('br'), 'Quyidagi havolani doʻstingizga yuboring — u havolani ochishi bilan duel boshlanadi.'))
      : h('div.alert.info', icon('users', 18), h('span', `Hozir yana ${others} kishi onlayn. Ulardan biri shu mavzuni tanlashi bilan duel boshlanadi. Doʻstingizni havola orqali ham chaqirishingiz mumkin.`)));
  }
  paintNotice();
  return { el, update: paintNotice, destroy: () => clearInterval(timer) };
}

// ============================================================== countdown
function countdownScreen() {
  const d = live.duel;
  const num = h('div.countdown-num', '3');
  const el = h('section.screen.vs-screen',
    h('div.center', h('span.topic-pill', icon('file', 15), d.topicName)),
    h('div.vs-row',
      h('div.vs-player.left', avatar(d.me.login, 'xl'), h('b', d.me.login), h('span.muted.small', 'siz')),
      h('div.vs-text', 'VS'),
      h('div.vs-player.right', avatar(d.opp.login, 'xl'), h('b', d.opp.login), h('span.muted.small', 'raqib'))),
    num,
    h('p.center.muted', `${d.total} ta savol · har biriga ${d.questionTime} soniya · tayyorlaning!`));
  let raf = 0;
  let last = null;
  const loop = () => {
    const cur = live.duel;
    const left = Math.max(0, (cur ? cur.countdownUntil : 0) - performance.now());
    const n = Math.ceil(left / 1000);
    if (n !== last) {
      last = n;
      num.textContent = n > 0 ? String(n) : 'Boshladik!';
      num.classList.remove('pop');
      void num.offsetWidth;
      num.classList.add('pop');
    }
    raf = requestAnimationFrame(loop);
  };
  loop();
  return { el, destroy: () => cancelAnimationFrame(raf) };
}

// ================================================================== o'yin
function scorePlayer(login, isMe) {
  const score = h('div.sb-score', '0');
  const fill = h('div.bar-fill');
  const meta = h('div.sb-meta');
  const status = h('span.sb-status');
  const el = h(`div.sb-player.${isMe ? 'me' : 'opp'}`,
    avatar(login, 'md'),
    h('div.sb-info', h('div.sb-name', h('span.ellipsis', login), isMe ? h('span.tag', 'siz') : status), h('div.bar', fill), meta),
    score);
  return {
    el,
    set(p, total) {
      score.textContent = String(p.correct);
      fill.style.width = `${Math.round((p.answered / total) * 100)}%`;
      meta.textContent = p.done ? `tugatdi · ${fmtMs(p.timeMs)}` : `${p.answered}/${total} javob`;
      if (!isMe) status.textContent = p.connected === false && !p.done ? 'aloqa uzildi' : '';
    },
  };
}

function timerRing() {
  const R = 23;
  const C = 2 * Math.PI * R;
  const wrap = h('div.timer');
  wrap.innerHTML = `<svg viewBox="0 0 56 56" width="56" height="56" aria-hidden="true"><circle class="timer-track" cx="28" cy="28" r="${R}"/><circle class="timer-arc" cx="28" cy="28" r="${R}" stroke-dasharray="${C}" stroke-dashoffset="0" transform="rotate(-90 28 28)"/></svg><span class="timer-num"></span>`;
  const arc = wrap.querySelector('.timer-arc');
  const num = wrap.querySelector('.timer-num');
  let lastSec = null;
  return {
    el: wrap,
    set(frac, secs) {
      arc.style.strokeDashoffset = String(C * (1 - Math.max(0, Math.min(1, frac))));
      const s = Math.ceil(secs);
      if (s !== lastSec) {
        lastSec = s;
        num.textContent = String(s);
        wrap.classList.toggle('warn', s <= 7 && s > 3);
        wrap.classList.toggle('danger', s <= 3);
      }
    },
  };
}

function playScreen() {
  const d0 = live.duel;
  const me = scorePlayer(d0.me.login, true);
  const opp = scorePlayer(d0.opp.login, false);
  const banner = h('div.alert.warning.opp-banner', { hidden: true });
  const stage = h('div.stage');
  const dots = h('div.dots', { 'aria-hidden': 'true' });
  const leaveBtn = h('button.btn.ghost.sm.text-danger', { type: 'button', onclick: leave }, icon('flag', 15), 'Duelni tark etish');
  const el = h('section.screen.play',
    h('div.play-topic', icon('swords', 15), h('span', d0.topicName)),
    h('div.scoreboard', me.el, h('div.sb-vs', 'VS'), opp.el),
    banner,
    stage,
    dots,
    h('div.play-foot', leaveBtn));

  let shownIndex = -1;
  let mode = null; // question | done | loading
  let q = null;
  let doneEls = null;
  let timeUp = false;
  let raf = 0;
  const bannerTimer = setInterval(paintBanner, 250);

  function onKey(e) {
    if (mode !== 'question' || !q || e.ctrlKey || e.metaKey || e.altKey) return;
    if (document.querySelector('.modal-overlay.show')) return;
    const k = e.key.toLowerCase();
    let i = '123456789'.indexOf(k);
    if (i < 0) i = 'abcdefghij'.indexOf(k);
    if (i >= 0 && i < q.buttons.length) {
      e.preventDefault();
      choose(i);
    }
  }
  document.addEventListener('keydown', onKey);

  function choose(i) {
    if (!timeUp) live.answer(i);
  }

  async function leave() {
    const ok = await confirmDialog({
      title: 'Duelni tark etasizmi?',
      message: 'Agar duelni tark etsangiz, raqibingiz gʻolib deb topiladi.',
      okText: 'Ha, chiqaman',
      cancelText: 'Davom etish',
      danger: true,
    });
    if (ok) live.leaveDuel();
  }

  function paintBanner() {
    const d = live.duel;
    if (!d || d.opp.connected !== false || d.opp.done) {
      banner.hidden = true;
      return;
    }
    const left = d.opp.graceUntil ? Math.max(0, Math.ceil((d.opp.graceUntil - performance.now()) / 1000)) : 0;
    banner.replaceChildren(icon('wifiOff', 18), h('span', `${d.opp.login} bilan aloqa uzildi. `,
      left > 0 ? h('b', `${left} soniya ichida qaytmasa, siz gʻolib boʻlasiz.`) : 'Natija hisoblanmoqda…'));
    banner.hidden = false;
  }

  function paintDots(d) {
    if (dots.childElementCount !== d.total) dots.replaceChildren(...Array.from({ length: d.total }, () => h('span.dot-q')));
    const cur = d.question ? d.question.index : d.answers.length;
    [...dots.children].forEach((dot, i) => {
      const a = d.answers[i];
      let cls = 'dot-q';
      if (a) cls += a.correct ? ' ok' : a.timedOut ? ' timeout' : ' bad';
      else if (i === cur && d.phase !== 'done') cls += ' current';
      dot.className = cls;
    });
  }

  function renderQuestion(question) {
    mode = 'question';
    shownIndex = question.index;
    timeUp = false;
    const ring = timerRing();
    const status = h('div.q-status', { role: 'status' });
    const buttons = question.options.map((text, i) => h('button.option', { type: 'button', onclick: () => choose(i) },
      h('span.opt-key', LETTERS[i] || String(i + 1)),
      h('span.opt-text', text),
      h('span.opt-mark')));
    const card = h('div.qcard.anim-in',
      h('div.q-head', h('div.q-count', 'Savol ', h('b', String(question.index + 1)), ` / ${question.total}`), ring.el),
      h('div.q-text', question.text),
      h('div.options', buttons),
      status);
    stage.replaceChildren(card);
    q = { card, buttons, ring, status };
    cancelAnimationFrame(raf);
    const tick = () => {
      const d = live.duel;
      if (!d || !d.question || d.question.index !== shownIndex || mode !== 'question') return;
      if (d.feedback && d.feedback.index === shownIndex) return; // taymer to'xtaydi
      const left = Math.max(0, d.question.deadline - performance.now());
      q.ring.set(left / (d.question.timeLimit * 1000), left / 1000);
      if (left <= 0 && !timeUp) {
        timeUp = true;
        applyState();
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
  }

  function applyState() {
    const d = live.duel;
    if (!q || mode !== 'question' || !d) return;
    const fb = d.feedback && d.feedback.index === shownIndex ? d.feedback : null;
    const locked = !!fb || d.picked != null || timeUp || d.phase !== 'question';
    q.buttons.forEach((b, i) => {
      b.disabled = locked;
      b.classList.toggle('picked', !fb && d.picked === i);
      b.classList.toggle('correct', !!fb && fb.correctIndex === i);
      b.classList.toggle('wrong', !!fb && fb.choice === i && !fb.correct);
      b.classList.toggle('dim', !!fb && fb.correctIndex !== i && fb.choice !== i);
    });
    let text = '';
    let cls = '';
    if (fb) {
      if (fb.timedOut) [text, cls] = ['⏱ Vaqt tugadi — javob berilmadi', 'bad'];
      else if (fb.correct) [text, cls] = [`✓ Toʻgʻri! (${(fb.ms / 1000).toFixed(1)} s)`, 'good'];
      else [text, cls] = ['✗ Notoʻgʻri javob', 'bad'];
    } else if (d.picked != null) {
      text = 'Javob yuborildi…';
    } else if (timeUp) {
      [text, cls] = ['Vaqt tugadi…', 'bad'];
    }
    q.status.textContent = text;
    q.status.className = `q-status ${cls}`;
    q.card.classList.toggle('flash-good', !!fb && fb.correct);
    q.card.classList.toggle('flash-bad', !!fb && !fb.correct);
  }

  function renderDone() {
    mode = 'done';
    cancelAnimationFrame(raf);
    q = null;
    const mine = h('p.done-score');
    const oppLine = h('span');
    stage.replaceChildren(h('div.card.done-card.anim-in',
      h('div.done-icon', icon('check', 30)),
      h('h2', 'Siz barcha savollarga javob berdingiz!'),
      mine,
      h('div.done-wait', h('span.spinner.sm'), oppLine)));
    doneEls = { mine, oppLine };
    leaveBtn.hidden = true;
    fillDone();
  }

  function fillDone() {
    const d = live.duel;
    if (!d || !doneEls) return;
    doneEls.mine.textContent = `Toʻgʻri javoblar: ${d.me.correct} / ${d.total} · sarflangan vaqt: ${fmtMs(d.me.timeMs)}`;
    doneEls.oppLine.textContent = d.opp.done
      ? 'Natija hisoblanmoqda…'
      : `${d.opp.login} hali javob bermoqda: ${d.opp.answered}/${d.total}. Natija ikkalangiz tugatganingizdan keyin chiqadi.`;
  }

  function renderLoading() {
    mode = 'loading';
    q = null;
    stage.replaceChildren(h('div.card.center', spinner('Keyingi savol…')));
  }

  function update() {
    const d = live.duel;
    if (!d) return;
    me.set(d.me, d.total);
    opp.set(d.opp, d.total);
    paintDots(d);
    paintBanner();
    if (d.phase === 'done') {
      if (mode !== 'done') renderDone();
      else fillDone();
      return;
    }
    if (d.question && d.question.index !== shownIndex) renderQuestion(d.question);
    else if (!d.question && mode !== 'question' && mode !== 'loading') renderLoading();
    applyState();
  }

  update();
  return {
    el,
    update,
    destroy() {
      cancelAnimationFrame(raf);
      clearInterval(bannerTimer);
      document.removeEventListener('keydown', onKey);
    },
  };
}

// ================================================================ natija
const RESULT_TITLE = { win: 'Gʻalaba!', lose: 'Magʻlubiyat', draw: 'Durang' };

function reasonText(r) {
  const opp = r.opp.login;
  const win = r.result === 'win';
  switch (r.reason) {
    case 'score':
      return win ? 'Siz koʻproq toʻgʻri javob berdingiz.' : `${opp} koʻproq toʻgʻri javob berdi.`;
    case 'time':
      return win ? 'Toʻgʻri javoblar soni teng, lekin siz testni tezroq bajardingiz.' : `Toʻgʻri javoblar soni teng, lekin ${opp} testni tezroq bajardi.`;
    case 'draw':
      return 'Toʻgʻri javoblar soni ham, sarflangan vaqt ham teng.';
    case 'left':
      return win ? `${opp} duelni tark etdi — gʻalaba sizga berildi.` : 'Siz duelni tark etdingiz.';
    case 'afk':
      return win
        ? `${opp} ${live.rules.afkSeconds} soniyadan ortiq javob bermadi — gʻalaba sizga berildi.`
        : `Siz ${live.rules.afkSeconds} soniyadan ortiq javob bermadingiz.`;
    case 'both_left':
      return 'Ikkala ishtirokchi ham duelni tark etdi.';
    default:
      return '';
  }
}

function statCol(title, login, s, total, winner) {
  return h(`div.stat-col${winner ? '.winner' : ''}`,
    winner ? h('span.crown', icon('trophy', 14), 'gʻolib') : null,
    avatar(login, 'lg'),
    h('div.stat-name', title),
    h('div.stat-big', String(s.correct), h('small', ` / ${total}`)),
    h('div.stat-label', 'toʻgʻri javob'),
    h('div.stat-time', icon('clock', 14), fmtMs(s.timeMs)),
    h('div.stat-label', 'sarflangan vaqt'));
}

function reviewBlock(r) {
  const items = r.review.map((q, i) => {
    const state = !q.mineAnswered ? 'skip' : q.mineTimedOut ? 'timeout' : q.mine === q.correct ? 'ok' : 'bad';
    return h(`li.review-item.${state}`,
      h('div.review-q', h('span.review-n', String(i + 1)), h('span.review-text', q.text)),
      h('ul.review-opts', q.options.map((o, j) => h('li', { class: j === q.correct ? 'is-correct' : j === q.mine ? 'is-wrong' : '' },
        h('span.opt-key.sm', LETTERS[j]),
        h('span.review-opt', o),
        j === q.mine ? h('span.tag.me', 'siz') : null,
        j === q.opp ? h('span.tag.opp', r.opp.login) : null))),
      state === 'skip' ? h('div.review-note', 'Bu savolga yetib kelinmadi') : null,
      state === 'timeout' ? h('div.review-note', 'Vaqt tugadi — javob berilmadi') : null);
  });
  return h('details.card.review',
    h('summary', icon('eye', 16), h('span', `Javoblarni koʻrish — ${r.me.correct}/${r.total} toʻgʻri`)),
    h('ol.review-list', items));
}

function resultScreen(ctx) {
  const r = live.result;
  const heroIcon = r.result === 'win' ? 'trophy' : r.result === 'draw' ? 'swords' : 'flag';
  const el = h(`section.screen.result.${r.result}`,
    h('div.result-hero',
      h('div.result-icon', icon(heroIcon, 44)),
      h('h1', RESULT_TITLE[r.result]),
      h('p.result-reason', reasonText(r)),
      h('span.topic-pill', icon('file', 15), r.topicName)),
    h('div.result-compare',
      statCol('Siz', ctx.user.login, r.me, r.total, r.result === 'win'),
      h('div.vs-badge', 'VS'),
      statCol(r.opp.login, r.opp.login, r.opp, r.total, r.result === 'lose')),
    h('div.result-actions',
      h('button.btn.primary.lg', { type: 'button', onclick: () => live.joinQueue(r.topicId) }, icon('refresh', 18), 'Yana oʻynash'),
      h('button.btn.ghost.lg', { type: 'button', onclick: () => live.clearResult() }, icon('swords', 18), 'Boshqa mavzu')),
    reviewBlock(r));
  return { el };
}
