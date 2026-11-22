"""Duel markazi: onlayn foydalanuvchilar, lobbi (raqib kutayotganlar — "seek"), tezkor juftlash, taklif havolalari
va duellar.

Hub to'liq sinxron ishlaydi va tashqi dunyo bilan faqat ikki narsa orqali bog'lanadi:
  * ``conn.send(type, data)`` — mijozga xabar yuborish (navbatga qo'yadi, kutmaydi);
  * ``clock.call_later(delay, fn, *args)`` — taymerlar.
Shu sababli uni soxta soat bilan oson testlash mumkin.

Lobbi va juftlash (docs/scaling.md):
  * har bir foydalanuvchida ko'pi bilan bitta ochiq seek: yangisi eskisini almashtiradi;
  * seek ``config.SEEK_TTL`` soniyada, bekor qilinganda, foydalanuvchining oxirgi oynasi yopilganda (aloqa uzilsa),
    u duelga kirganda yoki mavzu yopilganda o'chiriladi; zaxira tozalash har 10 soniyada;
  * mavzu bo'yicha tezkor juftlash: shu mavzuni kutayotgan eng eski seek, bo'lmasa "istalgan mavzu" seeki,
    bo'lmasa — yangi seek (kutish);
  * "istalgan mavzu": foydalanuvchi oxirgi o'ynagan 5 mavzudan birini kutayotgan raqib (eng yaqinda o'ynalgani
    oldin), bo'lmasa eng uzoq kutayotgan raqib (istalgan mavzuda), bo'lmasa boshqa "istalgan mavzu" kutuvchisi bilan
    eng qizg'in mavzuda, bo'lmasa — kutish. Mumkin bo'lsa, oxirgi raqib bilan ketma-ket qayta juftlanmaydi.
    (Bir mavzuni kutayotgan ikki kishi darhol juftlanadi, shuning uchun har bir mavzuda ko'pi bilan bitta kutuvchi.)
  * qo'shilish (Join) — taqqoslab-almashtirish: seek holati ``open`` -> ``taken`` bitta sinxron qadamda (oralig'ida
    ``await`` yo'q), shuning uchun bir vaqtda bosgan ikki kishidan faqat bittasi duelga kiradi;
  * holat bitta jarayon xotirasida (duellar kabi) — ilova bitta nusxada ishlaydi (docs/scaling.md).

Duel qoidalari:
  * ikkala ishtirokchiga bir xil savollar (``config.DUEL_QUESTIONS`` ta) beriladi;
  * har bir savolga ``config.QUESTION_TIME`` soniya; vaqt tugasa — javob noto'g'ri hisoblanadi;
  * ko'proq to'g'ri javob bergan g'olib; teng bo'lsa — kamroq vaqt sarflagan g'olib;
  * duelni tark etgan (aloqa uzilib ``DISCONNECT_GRACE`` ichida qaytmagan) yoki
    ``AFK_LIMIT`` soniya (ketma-ket bir necha savol) javob bermagan ishtirokchi mag'lub bo'ladi;
  * boshlanish sanog'i (``COUNTDOWN``) paytida ishtirokchi chiqib ketsa yoki aloqasi uzilsa — duel bekor qilinadi
    (natija yozilmaydi), ikkinchisiga xabar beriladi. Duel sanoq tugaganda "boshlangan" hisoblanadi: shu payt
    mavzuning faolligi (oxirgi o'yin, duellar soni, kunlik yig'indi) yoziladi.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from . import config
from .catalog import TopicCatalog
from .security import RateLimiter

log = logging.getLogger("testduel.hub")

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SEEK_ID_RE = re.compile(r"^[0-9a-f]{16}$")
SWEEP_EVERY = 10.0           # eskirgan seeklarni tozalash (zaxira)
MAINTENANCE_EVERY = 360      # har necha tozalashda bir marta xizmat ishlari (≈ 1 soat)
STATS_EVERY = 15.0           # onlayn foydalanuvchilar soni hammaga ko'pi bilan shuncha soniyada bir marta
TOPICS_SIGNAL_EVERY = 5.0    # "mavzular o'zgardi" xabari lobbi obunachilariga ko'pi bilan shuncha soniyada bir marta
WATCH_LIMIT = 60             # mijoz kuzatadigan mavzular (ekrandagi kartochkalar) soni
ACTION_LIMIT_USER = (30, 60.0)   # seek yaratish / qo'shilish / bekor qilish: foydalanuvchiga daqiqada 30 ta
ACTION_LIMIT_IP = (300, 60.0)    # bitta IP (maktab tarmog'i) dan daqiqada 300 ta


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
    """Foydalanuvchiga ko'rsatiladigan xato (code — mijoz uchun qisqa kod)."""

    def __init__(self, message: str, code: str | None = None, **extra):
        super().__init__(message)
        self.code = code
        self.extra = extra


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
class Seek:
    """Raqib kutayotgan o'yinchi (lobbidagi ochiq taklif). topic_id=None — istalgan mavzu."""
    id: str
    user_id: int
    login: str
    topic_id: int | None
    created: float
    created_ms: int
    state: str = "open"   # open | taken | closed
    expire_timer: Any = None


@dataclass
class Sub:
    """Lobbi obunasi (bitta oyna): faqat shu mijoz ko'rayotgan narsalar va unga oxirgi yuborilgan holat."""
    user_id: int
    topic: int | None = None
    watch: frozenset = frozenset()
    seeks: dict = field(default_factory=dict)    # seek id -> yuborilgan ko'rinish
    counts: dict = field(default_factory=dict)   # mavzu -> (kutmoqda, o'ynamoqda)
    live: list | None = None
    online: int = -1


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
        self.seeks: dict[str, Seek] = {}                      # ochiq seeklar (yaratilish tartibida)
        self.seek_of: dict[int, str] = {}                     # foydalanuvchi -> uning seeki
        self.topic_seeks: dict[int | None, dict[str, Seek]] = {}   # mavzu (None — istalgan) -> ochiq seeklar (FIFO)
        self.playing: dict[int, int] = {}                     # mavzu -> davom etayotgan duellar (hisoblagich)
        self.last_opponent: dict[int, int] = {}
        self.code_owner: dict[str, int] = {}
        self.user_code: dict[int, str] = {}
        self.duels: dict[str, Duel] = {}
        self.user_duel: dict[int, str] = {}
        self.pending_results: dict[int, tuple[float, dict]] = {}
        self.subs: dict[Any, Sub] = {}
        self.catalog = TopicCatalog(db, clock, self.topic_live)
        self.user_actions = RateLimiter(*ACTION_LIMIT_USER)
        self.ip_actions = RateLimiter(*ACTION_LIMIT_IP)
        self.stats = {"paired": 0, "seeks": 0, "joinRaces": 0, "cancelledHandshakes": 0}
        self._lobby_timer = None
        self._lobby_flushed = -math.inf
        self._stats_timer = None
        self._stats_sent = -1
        self._topics_timer = None
        self._sweep_timer = None
        self._sweeps = 0

    # ================================================================ info
    def rules(self) -> dict:
        return {
            "duelQuestions": config.DUEL_QUESTIONS,
            "questionTime": config.QUESTION_TIME,
            "afkSeconds": config.AFK_LIMIT,
            "afkTimeouts": afk_timeouts(),
            "disconnectGrace": config.DISCONNECT_GRACE,
            "seekSeconds": config.SEEK_TTL,
            "lanUrl": self.lan_url,
        }

    def is_online(self, user_id: int) -> bool:
        return bool(self.conns.get(user_id))

    def online_count(self) -> int:
        return len(self.conns)

    def topic_live(self, topic_id) -> tuple[int, int]:
        """(kutayotganlar, o'ynayotgan duellar) — hisoblagichlardan, duellar sanalmaydi."""
        return len(self.topic_seeks.get(topic_id, ())), self.playing.get(topic_id, 0)

    def queue_state(self, user_id: int) -> dict | None:
        s = self.seeks.get(self.seek_of.get(user_id, ""))
        if not s:
            return None
        topic = self.db.get_topic(s.topic_id) if s.topic_id is not None else None
        left = max(0.0, s.created + config.SEEK_TTL - self.clock.now())
        return {
            "seekId": s.id,
            "topicId": s.topic_id,
            "topicName": topic["name"] if topic else None,
            "questionCount": min(config.DUEL_QUESTIONS, topic["question_count"]) if topic else config.DUEL_QUESTIONS,
            "code": self._code_for(user_id) if s.topic_id is not None else None,
            "inviteFor": None,
            "expiresIn": round(left, 1),
        }

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
        s = self.seeks.get(self.seek_of.get(host, ""))
        topic = self.db.get_topic(s.topic_id) if s and s.topic_id is not None else None
        if not s or not topic:
            return {"valid": False, "reason": "idle", **base}
        return {
            "valid": True,
            **base,
            "hostOnline": self.is_online(host),
            "topicId": s.topic_id,
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
            "online": self.online_count(),
            "queue": self.queue_state(uid),
            "duel": self.duel_state(uid),
        })
        if first:
            self._user_online(uid)
        self._ensure_sweep()
        self._stats_changed()

    def disconnect(self, user_id: int, conn) -> None:
        self.subs.pop(conn, None)
        conns = self.conns.get(user_id)
        if not conns or conn not in conns:
            return
        conns.discard(conn)
        if not conns:
            del self.conns[user_id]
            self._touch(user_id)
            self._user_offline(user_id)
        self._stats_changed()

    def _touch(self, uid: int) -> None:
        """Foydalanuvchi oxirgi marta qachon saytda bo'lganini yozib qo'yadi."""
        try:
            self.db.touch_user(uid)
        except Exception:  # statistika uchun — xato o'yinni to'xtatmasin
            log.exception("last_seen yozilmadi")

    def handle(self, user_id: int, conn, msg_type, data: dict) -> None:
        try:
            if msg_type in ("queue:join", "seek:create"):
                self.seek(user_id, conn, data)
            elif msg_type in ("queue:leave", "seek:cancel"):
                self.cancel(user_id, conn, data.get("seekId"))
            elif msg_type == "seek:join":
                self.join(user_id, conn, data.get("seekId"))
            elif msg_type == "invite:accept":
                self.accept_invite(user_id, conn, str(data.get("code", "")))
            elif msg_type == "lobby:sub":
                self.subscribe(user_id, conn, data)
            elif msg_type == "lobby:unsub":
                self.subs.pop(conn, None)
            elif msg_type == "duel:answer":
                self.answer(user_id, str(data.get("duelId", "")), _as_int(data.get("index")), _as_int(data.get("choice")))
            elif msg_type == "duel:leave":
                self.leave_duel(user_id)
            elif msg_type == "ping":
                conn.send("pong", {})
        except HubError as e:
            conn.send("error", {"message": str(e), **({"code": e.code} if e.code else {}), **e.extra})

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

    def _user_online(self, uid: int) -> None:
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

    def _user_offline(self, uid: int) -> None:
        self._drop_seek(uid, notify=False)  # oxirgi oyna yopildi — lobbida "arvoh" qolmaydi
        duel = self.duels.get(self.user_duel.get(uid, ""))
        if duel and duel.status == "countdown":
            self._cancel_duel(duel, uid, "Raqibning aloqasi uzildi — duel bekor qilindi")
        elif duel and duel.status != "finished":
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

    # ======================================================= seek & lobbi
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

    def _rate(self, uid: int, conn) -> None:
        ip = getattr(conn, "ip", "?")
        if self.user_actions.blocked(str(uid)) or self.ip_actions.blocked(ip):
            raise HubError("Juda tez! Bir necha soniyadan keyin qayta urinib koʻring", "rate")
        self.user_actions.hit(str(uid))
        self.ip_actions.hit(ip)

    def _playable(self, topic_id) -> dict:
        topic = self.db.get_topic(topic_id) if topic_id is not None else None
        if not topic or not topic["active"]:
            raise HubError("Mavzu topilmadi yoki yopilgan", "topic")
        if topic["question_count"] < 1:
            raise HubError("Bu mavzuda savollar yoʻq", "topic")
        return topic

    def _others(self, seeks, uid: int) -> list[Seek]:
        return [s for s in seeks if s.user_id != uid and s.state == "open" and self.is_online(s.user_id)]

    def _prefer(self, candidates: list[Seek], uid: int) -> Seek:
        """Eng eski seek; mumkin bo'lsa — oxirgi raqib bilan ketma-ket qayta juftlanmaslik uchun boshqasi."""
        last = self.last_opponent.get(uid)
        for s in candidates:
            if s.user_id != last:
                return s
        return candidates[0]

    def seek(self, uid: int, conn, data: dict) -> None:
        """Tezkor juftlash: kutayotgan raqib bo'lsa — darhol duel, aks holda yangi seek (kutish)."""
        self._rate(uid, conn)
        if uid in self.user_duel:
            raise HubError("Siz hozir duelda qatnashyapsiz", "busy")
        raw = data.get("topicId")
        topic_id = None
        if raw is not None:  # null — istalgan mavzu; noto'g'ri qiymat rad etiladi
            topic_id = _as_int(raw)
            if topic_id is None or topic_id <= 0:
                raise HubError("Mavzu topilmadi yoki yopilgan", "topic")
            self._playable(topic_id)
        self._drop_seek(uid, notify=False)  # bitta foydalanuvchida bitta ochiq seek
        match = self._find_match(uid, topic_id)
        if match:
            other, topic = match
            self._pair(other, uid, topic)
            return
        self._open_seek(uid, topic_id)

    def _find_match(self, uid: int, topic_id: int | None) -> tuple[Seek, int] | None:
        if topic_id is not None:  # avval shu mavzuni kutayotgan, keyin "istalgan mavzu" kutuvchilari (FIFO)
            cands = self._others(self.topic_seeks.get(topic_id, {}).values(), uid)
            cands += self._others(self.topic_seeks.get(None, {}).values(), uid)
            return (self._prefer(cands, uid), topic_id) if cands else None
        recent = self._recent_topics(uid)
        rank = {tid: i for i, tid in enumerate(recent)}
        cands = [s for tid, seeks in self.topic_seeks.items() if tid is not None and self.catalog.is_playable(tid)
                 for s in self._others(seeks.values(), uid)]
        if cands:
            cands.sort(key=lambda s: (rank.get(s.topic_id, len(recent)), s.created))
            chosen = self._prefer(cands, uid)
            return chosen, chosen.topic_id
        cands = self._others(self.topic_seeks.get(None, {}).values(), uid)
        if cands:
            topic = self.catalog.hottest()
            if topic is not None:
                return self._prefer(cands, uid), topic
        return None

    def _recent_topics(self, uid: int, limit: int = 5) -> list[int]:
        """Foydalanuvchi oxirgi o'ynagan mavzular (indeks bo'yicha: idx_duels_p1 / idx_duels_p2)."""
        try:
            return self.db.recent_topics(uid, limit)
        except Exception:
            log.exception("Oxirgi mavzularni o'qib bo'lmadi")
            return []

    def _open_seek(self, uid: int, topic_id: int | None) -> Seek:
        s = Seek(secrets.token_hex(8), uid, self.logins.get(uid, "?"), topic_id, self.clock.now(), now_ms())
        s.expire_timer = self.clock.call_later(config.SEEK_TTL, self._expire_seek, s.id)
        self.seeks[s.id] = s
        self.seek_of[uid] = s.id
        self.topic_seeks.setdefault(topic_id, {})[s.id] = s
        self.stats["seeks"] += 1
        self._send(uid, "queue", self.queue_state(uid))
        self._lobby_changed()
        return s

    def _remove_seek(self, s: Seek, state: str = "closed") -> None:
        s.state = state
        _cancel(s.expire_timer)
        s.expire_timer = None
        self.seeks.pop(s.id, None)
        if self.seek_of.get(s.user_id) == s.id:
            del self.seek_of[s.user_id]
        bucket = self.topic_seeks.get(s.topic_id)
        if bucket is not None:
            bucket.pop(s.id, None)
            if not bucket:
                del self.topic_seeks[s.topic_id]
        self._lobby_changed()

    def _drop_seek(self, uid: int, notify: bool = True, message: str | None = None) -> None:
        s = self.seeks.get(self.seek_of.get(uid, ""))
        if not s:
            return
        self._remove_seek(s)
        if notify:
            self._send(uid, "queue", None)
            if message:
                self._send(uid, "notice", {"message": message, "kind": "warning"})

    def _expire_seek(self, seek_id: str) -> None:
        s = self.seeks.get(seek_id)
        if s and s.state == "open":
            self._drop_seek(s.user_id, message="Raqib topilmadi — kutish vaqti tugadi. Yana urinib koʻring.")

    def cancel(self, uid: int, conn, seek_id=None) -> None:
        """O'z seekini bekor qilish. Boshqaning seek identifikatori yuborilsa — rad etiladi."""
        self._rate(uid, conn)
        if seek_id is not None:
            s = self.seeks.get(seek_id) if isinstance(seek_id, str) else None
            if s and s.user_id != uid:
                raise HubError("Bu sizning taklifingiz emas", "forbidden")
        self._drop_seek(uid)

    def join(self, uid: int, conn, seek_id) -> None:
        """Lobbidagi seekka bir bosishda qo'shilish: darhol ikkalasi uchun duel boshlanadi."""
        self._rate(uid, conn)
        if not isinstance(seek_id, str) or not SEEK_ID_RE.fullmatch(seek_id):
            raise HubError("Taklif topilmadi", "taken", seekId=None)
        s = self.seeks.get(seek_id)
        if not s or s.state != "open" or not self.is_online(s.user_id):
            self.stats["joinRaces"] += 1
            raise HubError("Bu oʻyinchi allaqachon boshqa raqib bilan juftlandi yoki kutishni bekor qildi", "taken", seekId=seek_id)
        if s.user_id == uid:
            raise HubError("Bu sizning taklifingiz — boshqa oʻyinchi qoʻshilishini kuting", "own")
        if uid in self.user_duel:
            raise HubError("Siz hozir duelda qatnashyapsiz", "busy")
        topic = s.topic_id
        if topic is None:
            topic = self.catalog.hottest()
            if topic is None:
                raise HubError("Hozir oʻynash mumkin boʻlgan mavzu yoʻq", "topic")
        else:
            try:
                self._playable(topic)
            except HubError:
                self._drop_seek(s.user_id, message="Siz kutayotgan mavzu yopildi")
                raise
        self._drop_seek(uid, notify=False)
        self._pair(s, uid, topic)

    def _pair(self, s: Seek, joiner: int, topic_id: int) -> None:
        """Taqqoslab-almashtirish: seek faqat ochiq bo'lsa olinadi (bitta sinxron qadam, poyga bo'lmaydi)."""
        if s.state != "open":
            raise HubError("Bu oʻyinchi allaqachon boshqa raqib bilan juftlandi", "taken", seekId=s.id)
        self._remove_seek(s, state="taken")
        self.stats["paired"] += 1
        self._start_duel(s.user_id, joiner, topic_id)

    def accept_invite(self, uid: int, conn, code: str) -> None:
        host = self.code_owner.get(code.strip().upper())
        if host is None:
            raise HubError("Taklif havolasi notoʻgʻri yoki muddati oʻtgan")
        if host == uid:
            raise HubError("Bu sizning oʻzingizning taklif havolangiz — uni doʻstingizga yuboring")
        host_login = self.logins.get(host, "?")
        if host in self.user_duel:
            raise HubError(f"{host_login} hozir boshqa duelda")
        s = self.seeks.get(self.seek_of.get(host, ""))
        if not s or s.topic_id is None:
            raise HubError(f"{host_login} hozir duel kutmayapti — taklif bekor qilingan")
        self.join(uid, conn, s.id)

    # ------------------------------------------------------- lobbi obunasi
    def subscribe(self, uid: int, conn, data: dict) -> None:
        """Lobbi (yoki mavzular ro'yxati) ochilganda: darhol to'liq holat, keyin ko'pi bilan sekundiga bitta farq."""
        topic = _as_int(data.get("topicId")) if data.get("topicId") is not None else None
        watch = data.get("watch") or []
        ids = frozenset(t for t in (_as_int(x) for x in watch[:WATCH_LIMIT]) if t is not None) if isinstance(watch, list) else frozenset()
        sub = Sub(uid, topic, ids)
        self.subs[conn] = sub
        live = self._live_topics()
        conn.send("lobby", self._snapshot(sub, live))

    def _visible_seeks(self, topic: int | None) -> list[Seek]:
        source = self.topic_seeks.get(topic, {}) if topic is not None else self.seeks
        out = []
        for s in reversed(source.values()):  # eng yangilari
            if s.state == "open" and self.is_online(s.user_id):
                out.append(s)
                if len(out) >= config.LOBBY_LIMIT:
                    break
        return out

    def _seek_view(self, s: Seek, uid: int) -> dict:
        return {
            "id": s.id,
            "login": s.login,
            "topicId": s.topic_id,
            "topicName": self.catalog.name(s.topic_id),
            "since": s.created_ms,
            "mine": s.user_id == uid,
        }

    def _live_topics(self) -> list[list]:
        """Hozir faol mavzular: kutayotgan yoki o'ynayotganlar bor (hisoblagichlardan; eng faollari oldin)."""
        self.catalog.ensure()
        ids = {t for t in self.topic_seeks if t is not None} | {t for t, n in self.playing.items() if n > 0}
        rows = []
        for tid in ids:
            name = self.catalog.name(tid)
            if name is None:
                continue
            w, p = self.topic_live(tid)
            rows.append([tid, name, w, p])
        rows.sort(key=lambda r: (-(r[2] + r[3]), -r[2], r[1].casefold()))
        return rows[:config.LIVE_TOPICS_LIMIT]

    def _snapshot(self, sub: Sub, live: list) -> dict:
        seeks = self._visible_seeks(sub.topic)
        sub.seeks = {s.id: self._seek_view(s, sub.user_id) for s in seeks}
        sub.counts = {tid: self.topic_live(tid) for tid in sub.watch}
        sub.live = live
        sub.online = self.online_count()
        return {
            "seeks": list(sub.seeks.values()),
            "counts": {str(t): list(c) for t, c in sub.counts.items()},
            "live": live,
            "online": sub.online,
            "waiting": len(self.seeks),
            "limit": config.LOBBY_LIMIT,
        }

    def _lobby_changed(self) -> None:
        if self._lobby_timer is None and self.subs:
            delay = max(0.05, config.LOBBY_FLUSH - (self.clock.now() - self._lobby_flushed))
            self._lobby_timer = self.clock.call_later(delay, self._flush_lobby)

    def _flush_lobby(self) -> None:
        """Har bir obunachiga faqat o'zgarganlar: yangi/yo'qolgan seeklar, kuzatilayotgan mavzular sonlari."""
        self._lobby_timer = None
        self._lobby_flushed = self.clock.now()
        if not self.subs:
            return
        live = self._live_topics()
        views: dict[int | None, list[Seek]] = {}
        for conn, sub in list(self.subs.items()):
            if sub.topic not in views:
                views[sub.topic] = self._visible_seeks(sub.topic)
            current = {s.id: s for s in views[sub.topic]}
            added = [self._seek_view(s, sub.user_id) for sid, s in current.items() if sid not in sub.seeks]
            removed = [sid for sid in sub.seeks if sid not in current]
            counts = {}
            for tid in sub.watch:
                c = self.topic_live(tid)
                if sub.counts.get(tid) != c:
                    counts[str(tid)] = list(c)
                    sub.counts[tid] = c
            diff = {}
            if added or removed:
                for v in added:
                    sub.seeks[v["id"]] = v
                for sid in removed:
                    sub.seeks.pop(sid, None)
                diff["add"], diff["del"] = added, removed
                diff["waiting"] = len(self.seeks)
            if counts:
                diff["counts"] = counts
            if live != sub.live:
                diff["live"] = sub.live = live
            online = self.online_count()
            if online != sub.online:
                diff["online"] = sub.online = online
            if diff:
                conn.send("lobby:diff", diff)

    def _stats_changed(self) -> None:
        """Onlayn foydalanuvchilar soni (sarlavha uchun): hammaga ko'pi bilan STATS_EVERY soniyada bir marta."""
        self._lobby_changed()
        if self._stats_timer is None:
            self._stats_timer = self.clock.call_later(STATS_EVERY, self._flush_stats)

    def _flush_stats(self) -> None:
        self._stats_timer = None
        online = self.online_count()
        if online != self._stats_sent:
            self._stats_sent = online
            self.broadcast("stats", {"online": online})

    def topics_changed(self) -> None:
        """Mavzular o'zgardi (admin): katalog keshi bekor qilinadi, faqat lobbi obunachilariga kechiktirilgan xabar."""
        self.catalog.topics_changed()
        if self._topics_timer is None:
            self._topics_timer = self.clock.call_later(TOPICS_SIGNAL_EVERY, self._flush_topics)

    def _flush_topics(self) -> None:
        self._topics_timer = None
        for conn in list(self.subs):
            conn.send("topics", {})

    # -------------------------------------------------------- tozalash
    def _ensure_sweep(self) -> None:
        if self._sweep_timer is None:
            self._sweep_timer = self.clock.call_later(SWEEP_EVERY, self._sweep)

    def _sweep(self) -> None:
        """Zaxira tozalash: muddati o'tgan yoki egasi aloqada bo'lmagan seeklar; soatiga bir — xizmat ishlari."""
        self._sweep_timer = None
        try:
            now = self.clock.now()
            for s in list(self.seeks.values()):
                if s.created + config.SEEK_TTL <= now:
                    self._expire_seek(s.id)
                elif not self.is_online(s.user_id):
                    self._drop_seek(s.user_id, notify=False)
            self._sweeps += 1
            if self._sweeps % MAINTENANCE_EVERY == 0:
                self.maintenance()
        except Exception:
            log.exception("Lobbini tozalashda xato")
        finally:
            if self.conns or self.seeks or self.duels:
                self._ensure_sweep()

    def maintenance(self) -> None:
        """Soatlik: noyob o'yinchilar yordamchi jadvalini qisqartirish va (yoqilgan bo'lsa) avtomatik yopish."""
        try:
            self.db.prune_day_players()
            days = int(self.db.setting("auto_deactivate_days", "0") or 0)
            if days > 0:
                changed = self.db.auto_deactivate(days)
                for t in changed:
                    self.topic_removed(t["id"], "Siz kutayotgan mavzu yopildi")
                if changed:
                    self.topics_changed()
        except Exception:
            log.exception("Xizmat ishlarida xato")

    # =============================================================== duels
    def _start_duel(self, a: int, b: int, topic_id: int) -> None:
        topic = self.db.get_topic(topic_id)
        rows = self.db.pick_questions(topic_id, config.DUEL_QUESTIONS) if topic else []
        if not rows:
            for uid in (a, b):
                self._drop_seek(uid)
                self._send(uid, "notice", {"message": "Bu mavzuda savollar topilmadi", "kind": "error"})
            return
        questions = [prepare_question(r, bool(topic["shuffle_options"])) for r in rows]
        for uid in (a, b):
            self._drop_seek(uid, notify=False)
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
        self.playing[topic_id] = self.playing.get(topic_id, 0) + 1
        self.last_opponent[a], self.last_opponent[b] = b, a
        for uid in (a, b):
            self.user_duel[uid] = duel.id
        for uid in (a, b):  # ikkalasi birga duelga yuboriladi; duel:start navbatni ham yopadi (alohida queue:null yo'q —
            self._send(uid, "duel:start", self.duel_state(uid))  # aks holda brauzer bir lahzaga lobbini chizib, qayta obuna bo'lardi)
        duel.start_timer = self.clock.call_later(config.COUNTDOWN, self._begin, duel.id)
        log.info("Duel %s juftlandi: %s vs %s (%s)", duel.id, self.logins.get(a), self.logins.get(b), topic["name"])
        self._lobby_changed()

    def _begin(self, duel_id: str) -> None:
        duel = self.duels.get(duel_id)
        if not duel or duel.status != "countdown":
            return
        duel.status = "active"
        duel.start_timer = None
        try:  # duel boshlandi: mavzu faolligi (oxirgi o'yin, duellar soni, kunlik yig'indi)
            self.db.record_duel_start(duel.topic_id, duel.order, now_ms())
            self.catalog.activity_changed()
        except Exception:
            log.exception("Mavzu faolligini yozishda xato")
        for p in duel.players.values():
            self._ask(duel, p)

    def _cancel_duel(self, duel: Duel, by: int, message: str) -> None:
        """Boshlanish sanog'i paytida (qo'l siqish) chiqib ketildi: duel bekor, natija yozilmaydi."""
        if duel.status != "countdown":
            return
        duel.status = "finished"
        _cancel(duel.start_timer)
        self.duels.pop(duel.id, None)
        self._release_topic(duel.topic_id)
        self.stats["cancelledHandshakes"] += 1
        for uid in duel.order:
            self.user_duel.pop(uid, None)
            if uid != by:
                self._send(uid, "duel:cancel", {"duelId": duel.id, "message": message})
        log.info("Duel %s bekor qilindi (sanoq paytida %s chiqdi)", duel.id, self.logins.get(by))
        self._lobby_changed()

    def _release_topic(self, topic_id: int) -> None:
        n = self.playing.get(topic_id, 0) - 1
        if n > 0:
            self.playing[topic_id] = n
        else:
            self.playing.pop(topic_id, None)

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
        if not duel:
            return
        if duel.status == "countdown":
            self._cancel_duel(duel, uid, "Raqib duelni bekor qildi")
            self._send(uid, "duel:cancel", {"duelId": duel.id, "message": "Duel bekor qilindi"})
            return
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
        self._release_topic(duel.topic_id)
        self._lobby_changed()

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
    def topic_removed(self, topic_id: int, message: str = "Siz kutayotgan mavzu oʻchirildi") -> None:
        """Mavzu o'chirilgan yoki yopilgan: uni kutayotganlarning seeklari bekor qilinadi (davom etayotgan duellar
        tugaguncha o'ynaladi)."""
        for s in list(self.topic_seeks.get(topic_id, {}).values()):
            self._drop_seek(s.user_id, message=message)
        self.catalog.topics_changed()

    def kick_user(self, uid: int, reason: str) -> None:
        """Bloklangan yoki o'chirilgan foydalanuvchi: seeki bekor qilinadi, dueli yakunlanadi, oynalari yopiladi."""
        self._drop_seek(uid, notify=False)
        duel = self.duels.get(self.user_duel.get(uid, ""))
        if duel and duel.status == "countdown":
            self._cancel_duel(duel, uid, "Raqib duelni bekor qildi")
        elif duel:
            self._forfeit(duel.id, uid, "left")
        for c in list(self.conns.get(uid, ())):
            c.close(reason)

    def purge_user(self, uid: int) -> None:
        """Foydalanuvchi o'chirilishidan oldin: kick_user + u bilan bog'liq barcha ma'lumotlarni tozalash."""
        self.kick_user(uid, "deleted")
        self.pending_results.pop(uid, None)
        self.last_opponent.pop(uid, None)
        code = self.user_code.pop(uid, None)
        if code:
            self.code_owner.pop(code, None)
