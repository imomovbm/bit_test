// Real vaqtdagi aloqa (WebSocket) va umumiy holat: onlayn foydalanuvchilar, navbat, duel.
import { toast } from './lib.js';

const listeners = new Map();
let ws = null;
let wanted = false;
let retry = 0;
let retryTimer = null;
let lastMessageAt = 0;

const emptyPresence = () => ({ online: 0, users: [], waiting: {} });

export const live = {
  status: 'offline', // offline | connecting | online
  rules: { duelQuestions: 15, questionTime: 15, afkSeconds: 30, afkTimeouts: 2, disconnectGrace: 10, lanUrl: null },
  presence: emptyPresence(),
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
    return this.send('queue:join', { topicId });
  },

  leaveQueue() {
    return this.send('queue:leave');
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
      wanted = false;
      live.emit('unauthorized');
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
  if (q) q.localSince = prev && prev.topicId === q.topicId ? prev.localSince : Date.now();
  live.queue = q || null;
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
      live.presence = d.presence || emptyPresence();
      setQueue(d.queue);
      setDuel(d.duel);
      break;
    case 'presence':
      live.presence = d || emptyPresence();
      break;
    case 'queue':
      setQueue(d);
      if (d) live.result = null;
      break;
    case 'notice':
      toast(d.message, d.kind || 'info', 5500);
      break;
    case 'error':
      toast(d.message, 'error', 5000);
      break;
    case 'topics':
      live.emit('topics');
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
    default:
      break;
  }
  live.changed(t);
}
