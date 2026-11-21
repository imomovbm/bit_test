"""Duel markazi: onlayn foydalanuvchilar, navbat (raqib qidirish), taklif havolalari va duellar.

Hub to'liq sinxron ishlaydi va tashqi dunyo bilan faqat ikki narsa orqali bog'lanadi:
  * ``conn.send(type, data)`` — mijozga xabar yuborish (navbatga qo'yadi, kutmaydi);
  * ``clock.call_later(delay, fn, *args)`` — taymerlar.
Shu sababli uni soxta soat bilan oson testlash mumkin.

Duel qoidalari:
  * ikkala ishtirokchiga bir xil savollar (``config.DUEL_QUESTIONS`` ta) beriladi;
  * har bir savolga ``config.QUESTION_TIME`` soniya; vaqt tugasa — javob noto'g'ri hisoblanadi;
  * ko'proq to'g'ri javob bergan g'olib; teng bo'lsa — kamroq vaqt sarflagan g'olib;
  * duelni tark etgan (aloqa uzilib ``DISCONNECT_GRACE`` ichida qaytmagan) yoki
    ``AFK_LIMIT`` soniya (ketma-ket bir necha savol) javob bermagan ishtirokchi mag'lub bo'ladi.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from . import config

log = logging.getLogger("testduel.hub")

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def now_ms() -> int:
    return int(time.time() * 1000)


def afk_timeouts() -> int:
    """Necha marta ketma-ket vaqt tugasa, ishtirokchi mag'lub bo'ladi (30 s / 15 s = 2)."""
    return max(1, math.ceil(config.AFK_LIMIT / config.QUESTION_TIME - 1e-9))


class LoopClock:
    """Ishlab turgan asyncio sikliga asoslangan soat."""

    def now(self) -> float:
        return asyncio.get_running_loop().time()

    def call_later(self, delay: float, cb, *args):
        return asyncio.get_running_loop().call_later(delay, cb, *args)


def _cancel(handle) -> None:
    if handle is not None:
        handle.cancel()


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().lstrip("-").isdigit() and len(value.strip()) <= 18:
        value = int(value)
    if isinstance(value, int) and abs(value) < 2**62:  # SQLite chegarasidan oshmasin
        return value
    return None


class HubError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato."""


@dataclass
class Player:
    user_id: int
    login: str
    index: int = 0
    phase: str = "ready"  # ready | question | feedback | done
    q_started: float = 0.0
    answers: list = field(default_factory=list)
    correct: int = 0
    time_ms: int = 0
    timeouts_in_row: int = 0
    timer: Any = None
    disc_timer: Any = None
    disc_until: float | None = None
    forfeit: str | None = None

    def progress(self) -> dict:
        return {
            "answered": len(self.answers),
            "correct": self.correct,
            "timeMs": self.time_ms,
            "done": self.phase == "done",
        }


@dataclass
class Duel:
    id: str
    topic_id: int
    topic_name: str
    questions: list
    order: list
    players: dict
    status: str = "countdown"  # countdown | active | finished
    begin_at: float = 0.0
    started_ms: int = 0
    start_timer: Any = None

    def other(self, user_id: int) -> Player:
        a, b = self.order
        return self.players[b if user_id == a else a]


@dataclass
class WaitEntry:
    user_id: int
    topic_id: int
    since: float
    invite_for: int | None = None  # taklif orqali kelgan bo'lsa — taklif qilgan foydalanuvchi
    expire_timer: Any = None


def decide(a: Player, b: Player) -> tuple[int | None, str]:
    """G'olibni aniqlaydi: (g'olib id yoki None (durang), sabab)."""
    if a.forfeit and b.forfeit:
        return None, "both_left"
    if a.forfeit:
        return b.user_id, a.forfeit
    if b.forfeit:
        return a.user_id, b.forfeit
    if a.correct != b.correct:
        return (a.user_id if a.correct > b.correct else b.user_id), "score"
    if a.time_ms != b.time_ms:
        return (a.user_id if a.time_ms < b.time_ms else b.user_id), "time"
    return None, "draw"


def prepare_question(row: dict, shuffle: bool) -> dict:
    options = list(row["options"])
    correct = int(row["correct"])
    if shuffle and len(options) > 1:
        order = list(range(len(options)))
        random.shuffle(order)
        options = [options[i] for i in order]
        correct = order.index(correct)
    return {"id": row["id"], "text": row["text"], "options": options, "correct": correct}


class DuelHub:
    def __init__(self, db, clock, lan_url: str | None = None):
        self.db = db
        self.clock = clock
        self.lan_url = lan_url
        self.conns: dict[int, set] = {}
        self.logins: dict[int, str] = {}
        self.waiting: dict[int, WaitEntry] = {}
        self.code_owner: dict[str, int] = {}
        self.user_code: dict[int, str] = {}
        self.duels: dict[str, Duel] = {}
        self.user_duel: dict[int, str] = {}
        self.pending_results: dict[int, tuple[float, dict]] = {}
        self._presence_timer = None

    # ================================================================ info
    def rules(self) -> dict:
        return {
            "duelQuestions": config.DUEL_QUESTIONS,
            "questionTime": config.QUESTION_TIME,
            "afkSeconds": config.AFK_LIMIT,
            "afkTimeouts": afk_timeouts(),
            "disconnectGrace": config.DISCONNECT_GRACE,
            "lanUrl": self.lan_url,
        }

    def is_online(self, user_id: int) -> bool:
        return bool(self.conns.get(user_id))

    def presence(self) -> dict:
        users = []
        for uid in self.conns:
            status, topic = "idle", None
            if uid in self.user_duel:
                status = "duel"
            elif uid in self.waiting:
                status, topic = "waiting", self.waiting[uid].topic_id
            users.append({"id": uid, "login": self.logins.get(uid, "?"), "status": status, "topicId": topic})
        users.sort(key=lambda u: u["login"].casefold())
        waiting: dict[str, int] = {}
        for e in self.waiting.values():
            if e.invite_for is None and self.is_online(e.user_id):
                waiting[str(e.topic_id)] = waiting.get(str(e.topic_id), 0) + 1
        return {"online": len(users), "users": users, "waiting": waiting}

    def queue_state(self, user_id: int) -> dict | None:
        e = self.waiting.get(user_id)
        if not e:
            return None
        topic = self.db.get_topic(e.topic_id)
        state = {
            "topicId": e.topic_id,
            "topicName": topic["name"] if topic else "—",
            "questionCount": min(config.DUEL_QUESTIONS, topic["question_count"]) if topic else 0,
            "code": None,
            "inviteFor": None,
        }
        if e.invite_for is None:
            state["code"] = self._code_for(user_id)
        else:
            state["inviteFor"] = {
                "id": e.invite_for,
                "login": self.logins.get(e.invite_for, "?"),
                "online": self.is_online(e.invite_for),
            }
        return state

    def duel_state(self, user_id: int) -> dict | None:
        duel = self.duels.get(self.user_duel.get(user_id, ""))
        if not duel:
            return None
        me, opp = duel.players[user_id], duel.other(user_id)
        now = self.clock.now()
        return {
            "duelId": duel.id,
            "status": duel.status,
            "topicId": duel.topic_id,
            "topicName": duel.topic_name,
            "total": len(duel.questions),
            "questionTime": config.QUESTION_TIME,
            "me": {"id": me.user_id, "login": me.login, **me.progress()},
            "opp": {
                "id": opp.user_id,
                "login": opp.login,
                **opp.progress(),
                "connected": self.is_online(opp.user_id),
                "grace": round(max(0.0, opp.disc_until - now), 2) if opp.disc_until else 0.0,
            },
            "answers": [{"correct": a["correct"], "timedOut": a["timedOut"]} for a in me.answers],
            "phase": me.phase,
            "countdown": round(max(0.0, duel.begin_at - now), 3) if duel.status == "countdown" else 0.0,
            "question": self._question_payload(duel, me) if me.phase == "question" else None,
        }

    def invite_info(self, code: str) -> dict:
        host = self.code_owner.get((code or "").strip().upper())
        if host is None:
            return {"valid": False, "reason": "notfound"}
        base = {"host": self.logins.get(host, "?"), "hostId": host}
        if host in self.user_duel:
            return {"valid": False, "reason": "busy", **base}
        e = self.waiting.get(host)
        if not e or e.invite_for is not None:
            return {"valid": False, "reason": "idle", **base}
        topic = self.db.get_topic(e.topic_id)
        if not topic:
            return {"valid": False, "reason": "idle", **base}
        return {
            "valid": True,
            **base,
            "hostOnline": self.is_online(host),
            "topicId": e.topic_id,
            "topicName": topic["name"],
            "questionCount": min(config.DUEL_QUESTIONS, topic["question_count"]),
        }

    # ========================================================= connections
    def connect(self, user: dict, conn) -> None:
        uid = user["id"]
        self.logins[uid] = user["login"]
        self._touch(uid)
        first = not self.conns.get(uid)
        self.conns.setdefault(uid, set()).add(conn)
        conn.send("hello", {
            "rules": self.rules(),
            "presence": self.presence(),
            "queue": self.queue_state(uid),
            "duel": self.duel_state(uid),
        })
        if first:
            self._user_online(uid)
        self._presence_changed()

    def disconnect(self, user_id: int, conn) -> None:
        conns = self.conns.get(user_id)
        if not conns or conn not in conns:
            return
        conns.discard(conn)
        if not conns:
            del self.conns[user_id]
            self._touch(user_id)
            self._user_offline(user_id)
        self._presence_changed()

    def _touch(self, uid: int) -> None:
        """Foydalanuvchi oxirgi marta qachon saytda bo'lganini yozib qo'yadi."""
        try:
            self.db.touch_user(uid)
        except Exception:  # statistika uchun — xato o'yinni to'xtatmasin
            log.exception("last_seen yozilmadi")

    def handle(self, user_id: int, conn, msg_type, data: dict) -> None:
        try:
            if msg_type == "queue:join":
                self.join_queue(user_id, _as_int(data.get("topicId")))
            elif msg_type == "queue:leave":
                self.leave_queue(user_id)
            elif msg_type == "invite:accept":
                self.accept_invite(user_id, str(data.get("code", "")))
            elif msg_type == "duel:answer":
                self.answer(user_id, str(data.get("duelId", "")), _as_int(data.get("index")), _as_int(data.get("choice")))
            elif msg_type == "duel:leave":
                self.leave_duel(user_id)
            elif msg_type == "ping":
                conn.send("pong", {})
        except HubError as e:
            conn.send("error", {"message": str(e)})

    def broadcast(self, msg_type: str, data: dict) -> None:
        for conns in list(self.conns.values()):
            for c in list(conns):
                c.send(msg_type, data)

    def send_user(self, user_id: int, msg_type: str, data) -> None:
        """Foydalanuvchining barcha ochiq oynalariga xabar yuborish (masalan, huquqlari o'zgarganda)."""
        self._send(user_id, msg_type, data)

    def _send(self, user_id: int, msg_type: str, data) -> None:
        for c in list(self.conns.get(user_id, ())):
            c.send(msg_type, data)

    def _presence_changed(self) -> None:
        if self._presence_timer is None:
            self._presence_timer = self.clock.call_later(0.15, self._flush_presence)

    def _flush_presence(self) -> None:
        self._presence_timer = None
        self.broadcast("presence", self.presence())

    def _user_online(self, uid: int) -> None:
        e = self.waiting.get(uid)
        if e:
            _cancel(e.expire_timer)
            e.expire_timer = None
            if e.invite_for is None:
                self._refresh_invitees(uid)
        duel = self.duels.get(self.user_duel.get(uid, ""))
        if duel:
            p = duel.players[uid]
            if p.disc_timer is not None:
                _cancel(p.disc_timer)
                p.disc_timer = None
                p.disc_until = None
                self._send(duel.other(uid).user_id, "duel:opp", {"duelId": duel.id, "connected": True, "grace": 0})
        pending = self.pending_results.pop(uid, None)
        if pending and pending[0] > self.clock.now():
            self._send(uid, "duel:end", pending[1])
        if e:
            self._try_match(e.topic_id)

    def _user_offline(self, uid: int) -> None:
        e = self.waiting.get(uid)
        if e:
            _cancel(e.expire_timer)
            e.expire_timer = self.clock.call_later(config.WAITING_TTL, self._expire_wait, uid)
            if e.invite_for is None:
                self._refresh_invitees(uid)
        duel = self.duels.get(self.user_duel.get(uid, ""))
        if duel and duel.status != "finished":
            p = duel.players[uid]
            if p.phase != "done":
                _cancel(p.disc_timer)
                p.disc_until = self.clock.now() + config.DISCONNECT_GRACE
                p.disc_timer = self.clock.call_later(config.DISCONNECT_GRACE, self._forfeit, duel.id, uid, "left")
                self._send(
                    duel.other(uid).user_id,
                    "duel:opp",
                    {"duelId": duel.id, "connected": False, "grace": config.DISCONNECT_GRACE},
                )

    def _expire_wait(self, uid: int) -> None:
        e = self.waiting.get(uid)
        if e and not self.is_online(uid):
            e.expire_timer = None
            self.leave_queue(uid, notify=False)

    # ===================================================== queue & invites
    def _code_for(self, uid: int) -> str:
        code = self.user_code.get(uid)
        if code:
            return code
        while True:
            code = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(8))
            if code not in self.code_owner:
                break
        self.user_code[uid] = code
        self.code_owner[code] = uid
        return code

    def join_queue(self, uid: int, topic_id: int | None, invite_for: int | None = None) -> None:
        if uid in self.user_duel:
            raise HubError("Siz hozir duelda qatnashyapsiz")
        topic = self.db.get_topic(topic_id) if topic_id is not None else None
        if not topic or not topic["active"]:
            raise HubError("Mavzu topilmadi yoki yopilgan")
        if topic["question_count"] < 1:
            raise HubError("Bu mavzuda savollar yo'q")
        old = self.waiting.pop(uid, None)
        if old:
            _cancel(old.expire_timer)
            if old.invite_for is None and (old.topic_id != topic_id or invite_for is not None):
                self._drop_invitees(uid, f"{self.logins.get(uid, '?')} boshqa mavzuni tanladi — taklif bekor qilindi")
        self.waiting[uid] = WaitEntry(uid, topic["id"], self.clock.now(), invite_for)
        self._send(uid, "queue", self.queue_state(uid))
        if invite_for is not None:
            self._refresh_invitees(invite_for)
        self._presence_changed()
        self._try_match(topic["id"])

    def leave_queue(self, uid: int, notify: bool = True) -> None:
        e = self.waiting.pop(uid, None)
        if not e:
            return
        _cancel(e.expire_timer)
        if e.invite_for is None:
            self._drop_invitees(uid, f"{self.logins.get(uid, '?')} kutishni bekor qildi — taklif bekor qilindi")
        if notify:
            self._send(uid, "queue", None)
        self._presence_changed()

    def accept_invite(self, uid: int, code: str) -> None:
        host = self.code_owner.get(code.strip().upper())
        if host is None:
            raise HubError("Taklif havolasi noto'g'ri yoki muddati o'tgan")
        if host == uid:
            raise HubError("Bu sizning o'zingizning taklif havolangiz — uni do'stingizga yuboring")
        host_login = self.logins.get(host, "?")
        if host in self.user_duel:
            raise HubError(f"{host_login} hozir boshqa duelda")
        he = self.waiting.get(host)
        if not he or he.invite_for is not None:
            raise HubError(f"{host_login} hozir duel kutmayapti — taklif bekor qilingan")
        self.join_queue(uid, he.topic_id, invite_for=host)

    def _invitees(self, host: int) -> list[WaitEntry]:
        return [e for e in self.waiting.values() if e.invite_for == host]

    def _refresh_invitees(self, host: int) -> None:
        for e in self._invitees(host):
            self._send(e.user_id, "queue", self.queue_state(e.user_id))

    def _drop_invitees(self, host: int, message: str) -> None:
        for e in self._invitees(host):
            self.waiting.pop(e.user_id, None)
            _cancel(e.expire_timer)
            self._send(e.user_id, "queue", None)
            self._send(e.user_id, "notice", {"message": message, "kind": "warning"})

    def _try_match(self, topic_id: int) -> None:
        entries = sorted(
            (e for e in self.waiting.values() if e.topic_id == topic_id and self.is_online(e.user_id)),
            key=lambda e: e.since,
        )
        by_user = {e.user_id: e for e in entries}
        for e in entries:  # avval taklif orqali kelganlar
            if e.invite_for is not None and e.invite_for in by_user and by_user[e.invite_for].invite_for is None:
                self._start_duel(e.invite_for, e.user_id, topic_id)
                return
        generic = [e for e in entries if e.invite_for is None]
        if len(generic) >= 2:
            self._start_duel(generic[0].user_id, generic[1].user_id, topic_id)

    # =============================================================== duels
    def _start_duel(self, a: int, b: int, topic_id: int) -> None:
        topic = self.db.get_topic(topic_id)
        rows = self.db.pick_questions(topic_id, config.DUEL_QUESTIONS) if topic else []
        if not rows:
            for uid in (a, b):
                self.leave_queue(uid)
                self._send(uid, "notice", {"message": "Bu mavzuda savollar topilmadi", "kind": "error"})
            return
        questions = [prepare_question(r, bool(topic["shuffle_options"])) for r in rows]
        for uid in (a, b):
            e = self.waiting.pop(uid, None)
            if e:
                _cancel(e.expire_timer)
        for uid in (a, b):
            self._drop_invitees(uid, f"{self.logins.get(uid, '?')} boshqa raqib bilan duelga kirdi")

        duel = Duel(
            id=secrets.token_hex(8),
            topic_id=topic_id,
            topic_name=topic["name"],
            questions=questions,
            order=[a, b],
            players={uid: Player(uid, self.logins.get(uid, "?")) for uid in (a, b)},
            begin_at=self.clock.now() + config.COUNTDOWN,
            started_ms=now_ms(),
        )
        self.duels[duel.id] = duel
        for uid in (a, b):
            self.user_duel[uid] = duel.id
        for uid in (a, b):
            self._send(uid, "queue", None)
            self._send(uid, "duel:start", self.duel_state(uid))
        duel.start_timer = self.clock.call_later(config.COUNTDOWN, self._begin, duel.id)
        log.info("Duel %s boshlandi: %s vs %s (%s)", duel.id, self.logins.get(a), self.logins.get(b), topic["name"])
        self._presence_changed()

    def _begin(self, duel_id: str) -> None:
        duel = self.duels.get(duel_id)
        if not duel or duel.status != "countdown":
            return
        duel.status = "active"
        duel.start_timer = None
        for p in duel.players.values():
            self._ask(duel, p)

    def _question_payload(self, duel: Duel, p: Player) -> dict:
        q = duel.questions[p.index]
        remaining = max(0.0, config.QUESTION_TIME - (self.clock.now() - p.q_started))
        return {
            "duelId": duel.id,
            "index": p.index,
            "total": len(duel.questions),
            "text": q["text"],
            "options": q["options"],
            "timeLimit": config.QUESTION_TIME,
            "remaining": round(remaining, 3),
        }

    def _ask(self, duel: Duel, p: Player) -> None:
        p.phase = "question"
        p.q_started = self.clock.now()
        self._send(p.user_id, "duel:question", self._question_payload(duel, p))
        _cancel(p.timer)
        p.timer = self.clock.call_later(
            config.QUESTION_TIME + config.ANSWER_GRACE, self._timeout, duel.id, p.user_id, p.index
        )

    def answer(self, uid: int, duel_id: str, index: int | None, choice: int | None) -> None:
        duel = self.duels.get(self.user_duel.get(uid, ""))
        if not duel or duel.id != duel_id or duel.status != "active":
            return
        p = duel.players[uid]
        if p.phase != "question" or index != p.index:
            return
        q = duel.questions[p.index]
        if choice is None or not 0 <= choice < len(q["options"]):
            return
        elapsed = self.clock.now() - p.q_started
        if elapsed > config.QUESTION_TIME + config.ANSWER_GRACE:
            return  # kech qoldi — taymer o'zi "vaqt tugadi" deb yozadi
        self._record(duel, p, choice, int(min(elapsed, config.QUESTION_TIME) * 1000), timed_out=False)

    def _timeout(self, duel_id: str, uid: int, index: int) -> None:
        duel = self.duels.get(duel_id)
        if not duel or duel.status != "active":
            return
        p = duel.players[uid]
        if p.phase != "question" or p.index != index:
            return
        self._record(duel, p, None, int(config.QUESTION_TIME * 1000), timed_out=True)

    def _record(self, duel: Duel, p: Player, choice: int | None, ms: int, timed_out: bool) -> None:
        _cancel(p.timer)
        p.timer = None
        q = duel.questions[p.index]
        ok = choice is not None and choice == q["correct"]
        p.answers.append({"choice": choice, "correct": ok, "ms": ms, "timedOut": timed_out})
        p.correct += int(ok)
        p.time_ms += ms
        p.timeouts_in_row = p.timeouts_in_row + 1 if timed_out else 0
        self._send(p.user_id, "duel:feedback", {
            "duelId": duel.id,
            "index": p.index,
            "choice": choice,
            "correctIndex": q["correct"],
            "correct": ok,
            "timedOut": timed_out,
            "ms": ms,
        })
        p.index += 1
        p.phase = "feedback"
        self._progress(duel)
        if timed_out and p.timeouts_in_row >= afk_timeouts():
            p.forfeit = "afk"
            self._finish(duel)
            return
        if p.index >= len(duel.questions):
            p.timer = self.clock.call_later(config.FEEDBACK_DELAY, self._complete, duel.id, p.user_id)
        else:
            p.timer = self.clock.call_later(config.FEEDBACK_DELAY, self._next, duel.id, p.user_id)

    def _next(self, duel_id: str, uid: int) -> None:
        duel = self.duels.get(duel_id)
        if not duel or duel.status != "active":
            return
        p = duel.players[uid]
        if p.phase == "feedback" and p.index < len(duel.questions):
            self._ask(duel, p)

    def _complete(self, duel_id: str, uid: int) -> None:
        duel = self.duels.get(duel_id)
        if not duel or duel.status != "active":
            return
        p = duel.players[uid]
        p.timer = None
        p.phase = "done"
        _cancel(p.disc_timer)  # testni tugatgan ishtirokchi endi chiqib ketsa ham mag'lub bo'lmaydi
        p.disc_timer = None
        p.disc_until = None
        self._send(uid, "duel:done", {"duelId": duel.id})
        self._progress(duel)
        if all(pl.phase == "done" for pl in duel.players.values()):
            self._finish(duel)

    def _progress(self, duel: Duel) -> None:
        for uid in duel.order:
            me, opp = duel.players[uid], duel.other(uid)
            self._send(uid, "duel:progress", {
                "duelId": duel.id,
                "me": me.progress(),
                "opp": {**opp.progress(), "connected": self.is_online(opp.user_id)},
            })

    def leave_duel(self, uid: int) -> None:
        duel = self.duels.get(self.user_duel.get(uid, ""))
        if duel:
            self._forfeit(duel.id, uid, "left")

    def _forfeit(self, duel_id: str, uid: int, reason: str) -> None:
        duel = self.duels.get(duel_id)
        if not duel or duel.status == "finished":
            return
        p = duel.players.get(uid)
        if not p or p.phase == "done":
            return
        p.forfeit = reason
        self._finish(duel)

    def _finish(self, duel: Duel) -> None:
        if duel.status == "finished":
            return
        duel.status = "finished"
        _cancel(duel.start_timer)
        for p in duel.players.values():
            _cancel(p.timer)
            _cancel(p.disc_timer)
            p.timer = p.disc_timer = None
        a, b = (duel.players[u] for u in duel.order)
        winner, reason = decide(a, b)
        try:
            self.db.save_duel(
                topic_id=duel.topic_id,
                topic_name=duel.topic_name,
                p1={"id": a.user_id, "login": a.login, "correct": a.correct, "time_ms": a.time_ms},
                p2={"id": b.user_id, "login": b.login, "correct": b.correct, "time_ms": b.time_ms},
                total=len(duel.questions),
                winner=0 if winner is None else (1 if winner == a.user_id else 2),
                reason=reason,
                started_at=duel.started_ms,
                finished_at=now_ms(),
            )
        except Exception:  # natijani saqlab bo'lmasa ham o'yinchilar natijani ko'rsin
            log.exception("Duel natijasini saqlashda xato")
        log.info("Duel %s tugadi: %s %d:%d %s, sabab=%s", duel.id, a.login, a.correct, b.correct, b.login, reason)
        for p in (a, b):
            payload = self._result_payload(duel, p, duel.other(p.user_id), winner, reason)
            self.user_duel.pop(p.user_id, None)
            if self.is_online(p.user_id):
                self._send(p.user_id, "duel:end", payload)
            else:
                self.pending_results[p.user_id] = (self.clock.now() + config.RESULT_TTL, payload)
        self.duels.pop(duel.id, None)
        self._presence_changed()

    def _result_payload(self, duel: Duel, me: Player, opp: Player, winner: int | None, reason: str) -> dict:
        result = "draw" if winner is None else ("win" if winner == me.user_id else "lose")
        review = []
        for i, q in enumerate(duel.questions):
            mine = me.answers[i] if i < len(me.answers) else None
            theirs = opp.answers[i] if i < len(opp.answers) else None
            review.append({
                "text": q["text"],
                "options": q["options"],
                "correct": q["correct"],
                "mine": mine["choice"] if mine else None,
                "mineAnswered": mine is not None,
                "mineTimedOut": bool(mine and mine["timedOut"]),
                "opp": theirs["choice"] if theirs else None,
            })
        return {
            "duelId": duel.id,
            "topicId": duel.topic_id,
            "topicName": duel.topic_name,
            "total": len(duel.questions),
            "result": result,
            "reason": reason,
            "me": {"login": me.login, **me.progress()},
            "opp": {"id": opp.user_id, "login": opp.login, **opp.progress()},
            "review": review,
        }

    # ========================================================= admin hooks
    def topic_removed(self, topic_id: int, message: str = "Siz kutayotgan mavzu o'chirildi") -> None:
        """Mavzu o'chirilgan yoki yopilgan: uni kutayotganlar navbatdan chiqariladi."""
        for e in [e for e in self.waiting.values() if e.topic_id == topic_id]:
            self.waiting.pop(e.user_id, None)
            _cancel(e.expire_timer)
            self._send(e.user_id, "queue", None)
            self._send(e.user_id, "notice", {"message": message, "kind": "warning"})
        self._presence_changed()

    def kick_user(self, uid: int, reason: str) -> None:
        """Bloklangan yoki o'chirilgan foydalanuvchi: navbatdan chiqariladi, dueli yakunlanadi, oynalari yopiladi."""
        self.leave_queue(uid, notify=False)
        duel = self.duels.get(self.user_duel.get(uid, ""))
        if duel:
            self._forfeit(duel.id, uid, "left")
        for c in list(self.conns.get(uid, ())):
            c.close(reason)

    def purge_user(self, uid: int) -> None:
        """Foydalanuvchi o'chirilishidan oldin: kick_user + u bilan bog'liq barcha ma'lumotlarni tozalash."""
        self.kick_user(uid, "deleted")
        self.pending_results.pop(uid, None)
        code = self.user_code.pop(uid, None)
        if code:
            self.code_owner.pop(code, None)
