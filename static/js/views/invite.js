// Taklif havolasi orqali kelgan foydalanuvchi uchun sahifa: /invite/KOD
import { h, icon, avatar, spinner } from '../lib.js';
import { api } from '../api.js';
import { live } from '../live.js';

const REASONS = {
  notfound: 'Taklif havolasi notoʻgʻri yoki muddati oʻtgan.',
  busy: (host) => `${host} hozir boshqa duelda. Birozdan keyin qayta urinib koʻring.`,
  idle: (host) => `${host} hozir duel kutmayapti — taklif bekor qilingan. Undan yangi havola soʻrang.`,
};

export function inviteView(root, params, ctx) {
  const box = h('section.screen.invite-landing', h('div.card', spinner('Taklif tekshirilmoqda…')));
  root.append(box);
  let alive = true;

  async function load() {
    let info;
    try {
      info = await api(`/api/invite/${encodeURIComponent(params.code)}`);
    } catch (e) {
      info = { valid: false, reason: 'error', message: e.message };
    }
    if (alive) paint(info);
  }

  function paint(info) {
    if (live.duel) {
      box.replaceChildren(card('swords', 'Siz hozir duelda qatnashyapsiz', 'Avval joriy duelni yakunlang.',
        h('a.btn.primary', { href: '#/duel' }, 'Duelga qaytish')));
      return;
    }
    if (info.hostId === ctx.user.id) {
      box.replaceChildren(card('link', 'Bu sizning taklif havolangiz', 'Uni doʻstingizga yuboring — u havolani ochishi bilan duel boshlanadi.',
        h('a.btn.primary', { href: '#/duel' }, 'Duel sahifasiga')));
      return;
    }
    if (!info.valid) {
      const reason = REASONS[info.reason];
      const text = typeof reason === 'function' ? reason(info.host) : reason || info.message || 'Taklif amal qilmaydi.';
      box.replaceChildren(card('alert', 'Taklif amal qilmaydi', text,
        h('a.btn.primary', { href: '#/duel' }, icon('swords', 16), 'Boshqa raqib bilan oʻynash')));
      return;
    }
    const accept = h('button.btn.primary.lg', { type: 'button' }, icon('swords', 18), 'Duelni qabul qilish');
    accept.addEventListener('click', () => {
      if (live.acceptInvite(params.code)) ctx.navigate('/duel');
    });
    box.replaceChildren(h('div.card.invite-hero.anim-in',
      h('div.invite-avatars', avatar(info.host, 'xl'), h('span.vs-text', 'VS'), avatar(ctx.user.login, 'xl')),
      h('h1', h('span.grad', info.host), ' sizni duelga chaqirmoqda!'),
      h('span.topic-pill', icon('file', 15), info.topicName),
      h('ul.invite-rules',
        h('li', icon('file', 16), `${info.questionCount} ta savol — ikkalangizga bir xil`),
        h('li', icon('clock', 16), `har bir savolga ${live.rules.questionTime} soniya`),
        h('li', icon('trophy', 16), 'koʻp toʻgʻri javob bergan gʻolib, teng boʻlsa — tezroq bajargan'),
        h('li', icon('flag', 16), `chiqib ketish yoki ${live.rules.afkSeconds} s javobsizlik — magʻlubiyat`)),
      info.hostOnline ? null : h('div.alert.warning', icon('wifiOff', 18), h('span', `${info.host} hozir aloqada emas — qabul qilsangiz, u qaytishi bilan duel boshlanadi.`)),
      h('div.result-actions', accept, h('a.btn.ghost.lg', { href: '#/duel' }, 'Rad etish'))));
  }

  load();
  return () => {
    alive = false;
  };
}

function card(ic, title, text, action) {
  return h('div.card.center.invite-msg.anim-in', h('div.empty-ic', icon(ic, 28)), h('h2', title), h('p.muted', text), action);
}
