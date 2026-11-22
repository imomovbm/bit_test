// Real vaqtdagi aloqa (WebSocket) va umumiy holat: onlayn foydalanuvchilar soni, lobbi (raqib kutayotganlar),
// o'z seekimiz (navbat), duel. Lobbi ma'lumotlari faqat lobbi ochiq bo'lganda (obuna) va farqlar ko'rinishida keladi.
import { toast } from './lib.js';

const listeners = new Map();
let ws = null;
let wanted = false;
let retry = 0;
let retryTimer = null;
let lastMessageAt = 0;

const emptyPresence = () => ({ online: 0 });
const emptyLobby = () => ({ seeks: [], counts: {}, live: [], online: 0, waiting: 0, limit: 50, ready: false });
let lobbySub = null; // joriy obuna {topicId, watch} — qayta ulanganda tiklanadi

export const live = {
  status: 'offline', // offline | connecting | online
  rules: { duelQuestions: 15, questionTime: 15, afkSeconds: 30, afkTimeouts: 2, disconnectGrace: 10, seekSeconds: 120, lanUrl: null },
  presence: emptyPresence(),
  lobby: emptyLobby(),
  queue: null,
  duel: null,
  result: null,

  on(event, fn) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(fn);
    return () => listeners.get(event)?.delete(fn);
  },

  emit(event, data) {
    for (const fn of [...(listeners.get(event) || [])]) {
      try {
        fn(data);
      } catch (e) {
        console.error(e);
      }
    }
  },

  changed(kind) {
    this.emit('change', kind);
  },

  send(t, d = {}) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ t, d }));
      return true;
    }
    toast("Server bilan aloqa yo'q. Qayta ulanmoqda…", 'warning');
    return false;
  },

  joinQueue(topicId) {
    return this.send('seek:create', { topicId });
  },

  /** Tezkor juftlash: mavzu bo'yicha (topicId) yoki istalgan mavzu (null). */
  seek(topicId = null) {
    return this.send('seek:create', { topicId });
  },

  joinSeek(seekId) {
    return this.send('seek:join', { seekId });
  },

  leaveQueue() {
    return this.send('seek:cancel');
  },

  /** Lobbi ko'rinishiga obuna: topicId — faqat shu mavzu kutuvchilari, watch — ekrandagi mavzular (sonlar uchun). */
  subscribeLobby({ topicId = null, watch = [] } = {}) {
    lobbySub = { topicId, watch: watch.slice(0, 60) };
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: 'lobby:sub', d: lobbySub }));
  },

  unsubscribeLobby() {
    lobbySub = null;
    this.lobby = emptyLobby();
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: 'lobby:unsub', d: {} }));
  },

  acceptInvite(code) {
    return this.send('invite:accept', { code });
  },

  answer(choice) {
    const d = this.duel;
    if (!d || d.phase !== 'question' || !d.question || d.picked != null) return;
    if (performance.now() > d.question.deadline + 400) return;
    if (!this.send('duel:answer', { duelId: d.duelId, index: d.question.index, choice })) return;
    d.picked = choice;
    this.changed('duel:picked');
  },

  leaveDuel() {
    if (this.duel) this.send('duel:leave');
  },

  clearResult() {
    this.result = null;
    this.changed('result');
  },

  connect() {
    wanted = true;
    retry = 0;
    open();
  },

  disconnect() {
    wanted = false;
    clearTimeout(retryTimer);
    if (ws) {
      const s = ws;
      ws = null;
      s.close(1000);
    }
    this.queue = null;
    this.duel = null;
    this.result = null;
    this.presence = emptyPresence();
    this.lobby = emptyLobby();
    lobbySub = null;
    setStatus('offline');
  },
};

function setStatus(s) {
  if (live.status === s) return;
  live.status = s;
  live.changed('status');
}

function open() {
  clearTimeout(retryTimer);
  if (ws) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const sock = new WebSocket(`${proto}//${location.host}/ws`);
  ws = sock;
  setStatus('connecting');
  sock.onopen = () => {
    retry = 0;
    lastMessageAt = Date.now();
    setStatus('online');
  };
  sock.onmessage = (ev) => {
    lastMessageAt = Date.now();
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg && typeof msg.t === 'string') handle(msg.t, msg.d === undefined ? null : msg.d);
  };
  sock.onclose = (ev) => {
    if (ws !== sock) return;
    ws = null;
    setStatus('offline');
    if (ev.code === 4401) {
      // server ulanishni yopdi: sessiya tugagan, akkaunt bloklangan/o'chirilgan yoki paroli almashtirilgan
      wanted = false;
      live.emit('unauthorized', ev.reason);
      return;
    }
    if (wanted) schedule();
  };
}

function schedule() {
  clearTimeout(retryTimer);
  const delay = Math.min(5000, 400 * 2 ** retry) + Math.random() * 300;
  retry = Math.min(retry + 1, 6);
  retryTimer = setTimeout(open, delay);
}

function reconnectNow() {
  if (wanted && !ws) {
    retry = 0;
    open();
  }
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) reconnectNow();
});
window.addEventListener('online', reconnectNow);

// Ulanish "jim" o'lib qolmasligi uchun vaqti-vaqti bilan ping yuboramiz.
setInterval(() => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const idle = Date.now() - lastMessageAt;
  if (idle > 50000) {
    ws.close();
  } else if (idle > 20000) {
    ws.send(JSON.stringify({ t: 'ping', d: {} }));
  }
}, 10000);

function withDeadline(q) {
  return { ...q, deadline: performance.now() + (q.remaining ?? q.timeLimit) * 1000 };
}

function setQueue(q) {
  const prev = live.queue;
  if (q) {
    // expiresAt — server aytgan qolgan vaqtdan (sahifa qayta yuklansa ham to'g'ri); uzaytirilganda kutish vaqti davom etadi
    const ttl = (live.rules.seekSeconds || 120) * 1000;
    q.expiresAt = Date.now() + (q.expiresIn ?? ttl / 1000) * 1000;
    q.localSince = prev && (prev.seekId === q.seekId || prev.topicId === q.topicId) ? prev.localSince : q.expiresAt - ttl;
  }
  live.queue = q || null;
}

function applyLobbyDiff(d) {
  const lobby = live.lobby;
  if (d.del && d.del.length) {
    const gone = new Set(d.del);
    lobby.seeks = lobby.seeks.filter((x) => !gone.has(x.id));
  }
  if (d.add && d.add.length) {
    const known = new Set(lobby.seeks.map((x) => x.id));
    lobby.seeks = [...d.add.filter((x) => !known.has(x.id)), ...lobby.seeks]
      .sort((a, b) => b.since - a.since)
      .slice(0, lobby.limit || 50);
  }
  if (d.counts) Object.assign(lobby.counts, d.counts);
  if (d.live) lobby.live = d.live;
  if (typeof d.online === 'number') {
    lobby.online = d.online;
    live.presence.online = d.online;
  }
  if (typeof d.waiting === 'number') lobby.waiting = d.waiting;
}

function setDuel(s) {
  if (!s) {
    live.duel = null;
    return;
  }
  const now = performance.now();
  live.duel = {
    ...s,
    countdownUntil: now + (s.countdown || 0) * 1000,
    question: s.question ? withDeadline(s.question) : null,
    picked: null,
    feedback: null,
    answers: s.answers || [],
    opp: { ...s.opp, graceUntil: s.opp.connected ? null : now + (s.opp.grace || 0) * 1000 },
  };
}

function handle(t, d) {
  const duel = live.duel;
  const mine = (x) => duel && x && x.duelId === duel.duelId;
  switch (t) {
    case 'hello':
      Object.assign(live.rules, d.rules || {});
      live.presence = { online: d.online || 0 };
      setQueue(d.queue);
      setDuel(d.duel);
      if (lobbySub) live.send('lobby:sub', lobbySub); // qayta ulanish: lobbi holati qayta so'raladi
      break;
    case 'stats':
      live.presence.online = d.online || 0;
      break;
    case 'lobby':
      live.lobby = { ...emptyLobby(), ...d, ready: true };
      live.presence.online = d.online || live.presence.online;
      live.emit('lobby');
      break;
    case 'lobby:diff':
      applyLobbyDiff(d);
      live.emit('lobby');
      break;
    case 'queue':
      setQueue(d);
      if (d) live.result = null;
      break;
    case 'notice':
      toast(d.message, d.kind || 'info', 5500);
      break;
    case 'error':
      if (d.code === 'taken') { // boshqa o'yinchi oldinroq qo'shildi — ro'yxatdan olib tashlab, lobbini yangilaymiz
        if (d.seekId) applyLobbyDiff({ del: [d.seekId] });
        live.emit('lobby');
        if (lobbySub) live.send('lobby:sub', lobbySub);
        toast(d.message, 'warning', 5000);
      } else {
        toast(d.message, 'error', 5000);
      }
      break;
    case 'topics':
      live.emit('topics');
      break;
    case 'account':
      live.emit('account', d);
      break;
    case 'duel:start':
      live.result = null;
      live.queue = null;
      setDuel(d);
      live.emit('duel:start', d);
      break;
    case 'duel:question':
      if (mine(d)) Object.assign(duel, { status: 'active', phase: 'question', question: withDeadline(d), picked: null, feedback: null });
      break;
    case 'duel:feedback':
      if (mine(d)) {
        duel.phase = 'feedback';
        duel.feedback = d;
        duel.answers[d.index] = { correct: d.correct, timedOut: d.timedOut };
        live.emit('duel:feedback', d);
      }
      break;
    case 'duel:progress':
      if (mine(d)) {
        Object.assign(duel.me, d.me);
        Object.assign(duel.opp, d.opp);
      }
      break;
    case 'duel:done':
      if (mine(d)) {
        duel.phase = 'done';
        duel.question = null;
      }
      break;
    case 'duel:opp':
      if (mine(d)) {
        duel.opp.connected = d.connected;
        duel.opp.graceUntil = d.connected ? null : performance.now() + (d.grace || 0) * 1000;
      }
      break;
    case 'duel:end':
      live.duel = null;
      live.result = d;
      live.emit('duel:end', d);
      break;
    case 'duel:cancel': // boshlanish sanog'ida raqib chiqib ketdi — duel bekor (natija yozilmaydi)
      if (mine(d)) live.duel = null;
      toast(d.message, 'warning', 6000);
      live.emit('duel:cancel', d);
      break;
    default:
      break;
  }
  live.changed(t);
}
