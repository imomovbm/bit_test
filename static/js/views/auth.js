// Kirish va ro'yxatdan o'tish sahifasi.
import { h, icon, logoMark } from '../lib.js';
import { api } from '../api.js';

const LOGIN_RE = /^[\p{L}\p{N}_.-]{3,32}$/u;

export function authView(mode) {
  return function view(root, params, ctx) {
    const isLogin = mode === 'login';
    const invited = !!sessionStorage.getItem('td-invite');

    const loginInput = h('input', {
      type: 'text', name: 'login', autocomplete: 'username', autocapitalize: 'none', spellcheck: 'false',
      maxlength: 32, placeholder: 'masalan: ali_valiyev', required: true,
    });
    const passInput = h('input', {
      type: 'password', name: 'password', autocomplete: isLogin ? 'current-password' : 'new-password',
      maxlength: 128, placeholder: isLogin ? 'Parolingiz' : 'Kamida 4 ta belgi', required: true,
    });
    const eyeBtn = h('button.input-addon', { type: 'button', 'aria-label': 'Parolni koʻrsatish', title: 'Parolni koʻrsatish' }, icon('eye', 18));
    eyeBtn.addEventListener('click', () => {
      const show = passInput.type === 'password';
      passInput.type = show ? 'text' : 'password';
      eyeBtn.replaceChildren(icon(show ? 'eyeOff' : 'eye', 18));
      passInput.focus();
    });
    const errorBox = h('div.alert.error', { hidden: true, role: 'alert' });
    const closedBox = h('div.alert.warning.auth-closed', { hidden: true }, icon('lock', 18),
      h('span', 'Roʻyxatdan oʻtish yopilgan. Akkaunt olish uchun administrator (oʻqituvchi)ga murojaat qiling.'));
    const switchLine = h('p.auth-switch');
    const submitBtn = h('button.btn.primary.lg.block', { type: 'submit' }, isLogin ? 'Kirish' : 'Roʻyxatdan oʻtish', icon('right', 18));

    const form = h('form.auth-card', { novalidate: true },
      h('div.auth-card-head',
        h('h2', isLogin ? 'Tizimga kirish' : 'Roʻyxatdan oʻtish'),
        h('p.muted', isLogin ? 'Login va parolingizni kiriting' : 'Faqat login va parol — boshqa hech narsa kerak emas')),
      invited ? h('div.alert.info', icon('swords', 18), h('span', 'Sizni duelga taklif qilishdi! Davom etish uchun ', isLogin ? 'tizimga kiring.' : 'roʻyxatdan oʻting.')) : null,
      isLogin ? null : closedBox,
      h('label.field', h('span.field-label', 'Login'), loginInput),
      h('label.field', h('span.field-label', 'Parol'), h('div.input-wrap', passInput, eyeBtn)),
      errorBox,
      submitBtn,
      switchLine);

    // Administrator ro'yxatdan o'tishni yopgan bo'lishi mumkin — bunda faqat kirish mumkin.
    function applyRegistration(open) {
      if (isLogin) {
        switchLine.replaceChildren(...(open
          ? ['Akkauntingiz yoʻqmi? ', h('a', { href: '#/register' }, 'Roʻyxatdan oʻting')]
          : ['Akkaunt olish uchun administratorga murojaat qiling.']));
        return;
      }
      closedBox.hidden = open;
      [loginInput, passInput, submitBtn].forEach((el) => {
        el.disabled = !open;
      });
      switchLine.replaceChildren('Akkauntingiz bormi? ', h('a', { href: '#/login' }, 'Tizimga kiring'));
    }
    applyRegistration(ctx.registrationOpen);
    api('/api/auth/me').then((r) => applyRegistration(r.registrationOpen !== false)).catch(() => {});

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const login = loginInput.value.trim();
      const password = passInput.value;
      const problem = !login
        ? 'Loginni kiriting'
        : !LOGIN_RE.test(login)
          ? 'Login 3–32 ta harf, raqam yoki . _ - belgilaridan iborat boʻlishi kerak'
          : password.length < 4
            ? 'Parol kamida 4 ta belgidan iborat boʻlishi kerak'
            : '';
      if (problem) return showError(problem);
      submitBtn.disabled = true;
      errorBox.hidden = true;
      try {
        const res = await api(`/api/auth/${isLogin ? 'login' : 'register'}`, { method: 'POST', body: { login, password } });
        ctx.onLogin(res.user);
      } catch (err) {
        showError(err.message);
      } finally {
        submitBtn.disabled = false;
      }
    });

    function showError(msg) {
      errorBox.textContent = msg;
      errorBox.hidden = false;
    }

    root.append(h('div.auth-wrap',
      h('section.auth-hero',
        h('div.brand.big', logoMark(44), h('span.brand-text', 'Test', h('b', 'Duel'))),
        h('h1', 'Bilimingizni ', h('span.grad', 'duelda'), ' sinang!'),
        h('p.lead', 'Testlar boʻyicha doʻstlaringiz bilan bellashing yoki mustaqil mashq qiling.'),
        h('ul.feature-list',
          feature('swords', 'Duel', '15 ta savol, har biriga 15 soniya. Koʻp toʻgʻri javob bergan gʻolib.'),
          feature('book', 'Oʻrganish rejimi', '10, 30, 50 yoki barcha savollar — vaqt chegarasisiz.'),
          feature('balloon', 'Balloon Pop', 'Sinf uchun jamoaviy oʻyin: zar tashlang, raqib sharlarini portlating.'),
          feature('trophy', 'Reyting', 'Gʻalabalaringiz va natijalaringiz saqlanib boradi.'))),
      form));
    setTimeout(() => loginInput.focus(), 50);
  };
}

function feature(ic, title, text) {
  return h('li', h('span.feature-ic', icon(ic, 18)), h('div', h('b', title), h('span', text)));
}
