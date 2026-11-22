"""Octagon — jonli viktorina: o'qituvchi ekrani (proyektor) + o'quvchilar telefonlari.

Oqim: o'qituvchi mavzu va sozlamalarni tanlaydi -> lobbi ochiladi (PIN + QR kod) -> o'quvchilar telefonda PIN va ism
bilan qo'shiladi (ro'yxatdan o'tmasdan) -> o'qituvchi «Boshlash»ni bosadi -> har bir savol uchun:
``ready`` (tayyorlaning, config.OCTAGON_READY s) -> ``question`` (savol vaqti) -> ``reveal`` (javoblar taqsimoti va
to'g'ri javob) -> ``leaderboard`` (top 5) -> ... -> ``podium`` (yakuniy natijalar).

Barcha holat serverda (xotirada) saqlanadi — server yagona manba. Hub to'liq sinxron va tashqi dunyo bilan faqat
``conn.send(type, data)``, ``conn.close(reason, code)`` va ``clock.call_later(delay, fn, *args)`` orqali bog'lanadi,
shuning uchun soxta soat bilan testlanadi (tests/test_octagon.py).

O'quvchilarga yuboriladigan xabarlar ataylab juda kichik: savol matni, variantlar matni va (savol tugaguncha) to'g'ri
javob hech qachon yuborilmaydi — faqat savol raqami, variantlar soni, qolgan vaqt va shaxsiy natija.

WebSocket /ws/octagon xabarlari — JSON ``{"t": tur, "d": ma'lumot}``:
  o'quvchi -> server: check {pin} | join {pin, nick} | resume {pin, id, tok} | a {q, o} | ping
  server -> o'quvchi: c {pin} | w {pin, id, nick, tok?} | s {holat} | e {c: kod, m: matn} | k {r: sabab} | pong
  o'qituvchi -> server: host {pin} | start | next | skip | end | kick {id} | settings {timeLimit} | lock {locked} | close
  server -> o'qituvchi: h {to'liq holat} | closed {pin} | e {c, m, status}

O'quvchi holati ``s``: p — bosqich, q — savol indeksi (0 dan), n — savollar soni, o — variantlar soni,
r — bosqich tugashiga qolgan ms, t — savol vaqti (ms), a — o'quvchi tanlagan variant, sc — umumiy ball,
k — o'rin, pl — o'yinchilar soni, res — savol natijasi {ok, pts, co (to'g'ri variant)}, top — podium (top 3).

Javob vaqti faqat serverda o'lchanadi: savol ochilgan paytdan (server soati) javob serverga yetib kelgan paytgacha.
Tarmoq kechikishi o'quvchi hisobiga ketadi; server vaqti tugagach kelgan javob qabul qilinmaydi. O'quvchi ekranidagi
taymer o'lchangan kechikish (ping) bo'yicha biroz oldinroq tugaydi, shuning uchun u server muddatidan kech qolmaydi.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import math
import random
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from . import config
from .qr import qr_path
from .roles import is_teacher
from .security import RateLimiter

log = logging.getLogger("testduel.octagon")

MAX_POINTS = 1000
FULL_POINTS_MS = 500            # shundan tez (yoki aynan shu vaqtda) berilgan to'g'ri javob — to'liq ball
MIN_TIME, MAX_TIME, DEFAULT_TIME = 5, 120, 20   # savol vaqti (soniya)
MAX_OPTIONS = 4                 # shakllar: sakkizburchak, tomchi, yulduz, plyus (static/js/octagon/common.js)
MAX_QUESTIONS = 100
DEFAULT_QUESTIONS = 10
NICK_MAX = 20
MAX_PLAYERS = 300
MAX_GAMES_PER_OWNER = 5
MAX_GAMES = 500
MAX_SOCKETS_PER_IP = 500        # bitta IP ortida butun maktab bo'lishi mumkin
MAX_SOCKETS = config.OCTAGON_MAX_SOCKETS     # barcha IP lardan jami ochiq ulanishlar (xotira himoyasi)
FAIL_LIMIT, FAIL_WINDOW = 20, 300            # noto'g'ri PIN/token urinishlari: IP bo'yicha, 5 daqiqada
GLOBAL_FAIL_LIMIT, GLOBAL_FAIL_WINDOW = 300, 60   # barcha IP lardan: shundan oshsa — PIN taxmin qilish hujumi
SURGE_FAIL_LIMIT = 5                          # hujum paytida bitta IP ga ruxsat etilgan noto'g'ri urinishlar
JOIN_LIMIT, JOIN_WINDOW = 200, 600           # yangi o'yinchilar: IP bo'yicha, 10 daqiqada
MAX_FINISHED_PER_OWNER = 5                    # tugagan (podium) o'yinlar: o'qituvchi uchun xotirada saqlanadigan eng ko'p soni
HOST_FLUSH = 0.25               # o'qituvchi ekranini yangilash oralig'i (o'quvchilar qo'shilganda, javob berganda)
SWEEP_EVERY = 60.0
PIN_RE = re.compile(r"^[1-9][0-9]{5}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
LONG_OPTIONS = ("trim", "skip")  # 4 tadan ko'p variantli savollar: qisqartirish yoki o'tkazib yuborish
HOST_ACTIONS = ("start", "next", "skip", "end", "kick", "settings", "lock", "close")  # faqat o'yin egasi (WebSocket)


# =================================================================== ball
def calculate_score(is_correct: bool, response_time_ms, timer_ms, max_points: int = MAX_POINTS) -> int:
    """Bitta savol uchun ball (butun son): to'g'ri javob — 500 + tezlik uchun 500 gacha, noto'g'ri/javobsiz — 0.

    ``score = round((1 - (t / timer) / 2) * max_points)`` — bu yerda t javob vaqti (ms):
      * t ≤ 500 ms bo'lsa — to'liq ball (t = 0 deb olinadi);
      * t > timer bo'lsa — t = timer (eng kamida max_points / 2). Vaqti o'tgan javobni o'yin qabul qilmaydi.
    Hisob aniq kasrlar bilan bajariladi va faqat oxirida bir marta yaxlitlanadi (0.5 — yuqoriga).
    """
    if not is_correct:
        return 0
    timer = Fraction(timer_ms)
    if timer <= 0:
        raise ValueError("timer_ms musbat bo'lishi kerak")
    t = Fraction(response_time_ms)
    if t <= FULL_POINTS_MS:
        t = Fraction(0)
    t = min(t, timer)
    exact = (1 - t / timer / 2) * max_points
    return math.floor(exact + Fraction(1, 2))


# ============================================================== ismlar
class NicknameError(ValueError):
    pass


_NICK_PUNCT = set(" .-_'’!?#@+()")
# Kirill/yunon harflaridagi "o'xshash" belgilar: "Аli" (kirillcha А) va "Ali" bitta ism hisoblanadi.
_LOOKALIKE = str.maketrans({
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ӏ": "l", "α": "a", "ο": "o", "ρ": "p", "ν": "v",
    "ι": "i", "κ": "k", "τ": "t", "χ": "x", "ε": "e", "μ": "m",
})
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "ё": "е"})
# Oddiy so'kinish filtri (o'zbek, rus, ingliz). Uzun o'zaklar so'z ichida ham, qisqalari faqat alohida so'z sifatida.
_BAD_ANYWHERE = (
    "fuck", "fuk", "bitch", "cunt", "whore", "nigger", "nigga", "pussy", "porn", "slut", "asshole",
    "dalbayob", "dalbayop", "dolboyob", "dolbayob", "jalab", "qanjiq", "kotinga", "kotingga", "kotingni", "sikaman", "sikay",
    "sikish", "sikdim", "onangni", "pizd", "blyat", "blyad", "gandon", "pidor", "pidar", "mudak", "eblan", "zaeb",
    "хуй", "хуе", "хуё", "пизд", "бляд", "блят", "ебат", "ебан", "ёбан", "уеб", "сука", "мудак", "пидор", "пидар",
    "гандон", "шлюх", "далбаёб", "далбайоб", "жалаб", "қанжиқ", "канжик", "сикай", "сикаман", "онангни",
)
_BAD_WORDS = {"sik", "suka", "huy", "xuy", "hui", "dick", "shit", "shitty", "fag", "kotak", "qotoq", "бля", "сик", "кутак", "қўтоқ"}


def nickname_key(nick: str) -> str:
    """Bir xil ismni aniqlash uchun: katta-kichik harf, bo'shliq/tinish belgilari va o'xshash harflar hisobga olinmaydi."""
    key = "".join(ch for ch in nick.casefold().translate(_LOOKALIKE) if ch.isalnum())
    return key or nick.casefold()


def is_profane(nick: str) -> bool:
    low = nick.casefold().translate(_LEET)
    tokens = [t for t in re.split(r"[\W_]+", low) if t]
    joined = "".join(tokens)
    if any(root in joined for root in _BAD_ANYWHERE):
        return True
    spelled, run = [], ""  # "s u k a" kabi harfma-harf yozilgan so'zlar
    for t in tokens + [""]:
        if len(t) == 1:
            run += t
            continue
        if len(run) > 1:
            spelled.append(run)
        run = ""
    return any(t in _BAD_WORDS for t in tokens + spelled)


def clean_nickname(raw) -> str:
    """Ismni tozalaydi va tekshiradi: 1–20 belgi; HTML/boshqaruv/ko'rinmas belgilar va emoji olib tashlanadi."""
    if not isinstance(raw, str):
        raise NicknameError("Ismingizni kiriting")
    text = unicodedata.normalize("NFC", re.sub(r"<[^>]{0,60}>", "", raw[:200]))  # HTML teglari butunlay olib tashlanadi
    out: list[str] = []
    marks = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if ch.isspace():
            out.append(" ")
            marks = 0
        elif cat.startswith("M"):  # urg'u belgilari: harfdan keyin ko'pi bilan 2 ta ("zalgo" matnga qarshi)
            if out and out[-1] != " " and marks < 2:
                out.append(ch)
                marks += 1
        elif cat[0] in "LN" or ch in _NICK_PUNCT:
            out.append(ch)
            marks = 0
        # boshqa belgilar (< > & " `, boshqaruv va ko'rinmas belgilar, emoji) tashlab yuboriladi
    nick = " ".join("".join(out).split())
    if not any(ch.isalnum() for ch in nick):
        raise NicknameError("Ismingizni kiriting (kamida bitta harf yoki raqam)")
    if len(nick) > NICK_MAX:
        raise NicknameError(f"Ism {NICK_MAX} belgidan oshmasin")
    if is_profane(nick):
        raise NicknameError("Bu ismni ishlatib boʻlmaydi. Boshqa ism tanlang")
    return nick


# =========================================================== sozlamalar
class OctagonError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato. code — mijoz uchun qisqa kod, status — HTTP holat kodi."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def payload(self) -> dict:
        return {"c": self.code, "m": self.message, "status": self.status}


def _int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def clean_settings(data: dict) -> dict:
    """O'yin oldidan tanlanadigan sozlamalarni tekshiradi (serverda)."""
    time_limit = data.get("timeLimit", DEFAULT_TIME)
    if _int(time_limit) is None or not MIN_TIME <= time_limit <= MAX_TIME:
        raise OctagonError("settings", f"Savol vaqti {MIN_TIME}–{MAX_TIME} soniya oraligʻida butun son boʻlsin")
    count = data.get("questionCount", DEFAULT_QUESTIONS)
    if _int(count) is None or count < 1:
        raise OctagonError("settings", "Savollar soni notoʻgʻri")
    long_options = data.get("longOptions", "trim")
    if long_options not in LONG_OPTIONS:
        raise OctagonError("settings", "4 tadan koʻp variantli savollar uchun tanlov notoʻgʻri")
    return {
        "timeLimit": time_limit,
        "questionCount": min(count, MAX_QUESTIONS),
        "shuffleQuestions": bool(data.get("shuffleQuestions", True)),
        "shuffleAnswers": bool(data.get("shuffleAnswers", True)),
        "longOptions": long_options,
    }


def prepare_questions(rows: list[dict], settings: dict, rng: random.Random) -> tuple[list[dict], int]:
    """Mavzu savollaridan o'yin savollarini tayyorlaydi. Natija: (savollar, qisqartirilganlar soni).

    4 tadan ko'p variantli savol: "trim" — to'g'ri javob + tasodifiy 3 ta noto'g'ri variant qoldiriladi,
    "skip" — savol o'yinga olinmaydi.
    """
    pool = [r for r in rows if len(r["options"]) >= 2]
    if settings["longOptions"] == "skip":
        pool = [r for r in pool if len(r["options"]) <= MAX_OPTIONS]
    if settings["shuffleQuestions"]:
        rng.shuffle(pool)
    pool = pool[: settings["questionCount"]]
    out, trimmed = [], 0
    for r in pool:
        options, correct = list(r["options"]), int(r["correct"])
        order = list(range(len(options)))
        if len(options) > MAX_OPTIONS:
            wrong = [i for i in order if i != correct]
            order = sorted([correct, *rng.sample(wrong, MAX_OPTIONS - 1)])
            trimmed += 1
        if settings["shuffleAnswers"]:
            rng.shuffle(order)
        out.append({"id": r["id"], "text": r["text"], "options": [options[i] for i in order], "correct": order.index(correct)})
    return out, trimmed


def norm_pin(value) -> str | None:
    pin = re.sub(r"\s+", "", str(value or ""))[:12]
    return pin if PIN_RE.fullmatch(pin) else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()  # token doim TOKEN_RE ga mos (ASCII)


def _cancel(handle) -> None:
    if handle is not None:
        handle.cancel()


# ============================================================ holatlar
@dataclass
class Player:
    id: str
    token_hash: str
    nick: str
    key: str
    score: int = 0
    time_ms: int = 0               # tenglikda: umumiy javob vaqti (javobsiz savol = to'liq vaqt), kam — yaxshi
    correct: int = 0
    answers: dict = field(default_factory=dict)   # savol indeksi -> (variant, javob vaqti ms)
    last: dict | None = None       # oxirgi yopilgan savol natijasi {q, ok, pts, co}
    conn: Any = None


@dataclass
class Game:
    pin: str
    owner_id: int
    owner_login: str
    topic_id: int
    topic_name: str
    questions: list
    time_limit_ms: int
    settings: dict
    join_base: str
    created_ms: int
    trimmed: int = 0
    phase: str = "lobby"           # lobby | ready | question | reveal | leaderboard | podium
    index: int = -1
    q_open_at: float = 0.0         # savol javoblar uchun ochiladigan/ochilgan payt (server soati)
    deadline: float = 0.0
    timer: Any = None
    host_timer: Any = None
    activity: float = 0.0
    players: dict = field(default_factory=dict)  # id -> Player (qo'shilish tartibida)
    keys: dict = field(default_factory=dict)     # ism kaliti -> o'yinchi id
    hosts: set = field(default_factory=set)
    stats: list = field(default_factory=list)    # har bir yopilgan savol: {counts, answered, correct}
    ended_early: bool = False
    finished_seq: int = 0                        # tugash tartibi (eski natijalarni tozalash uchun)
    locked: bool = False                         # o'qituvchi yangi o'quvchilar qo'shilishini to'xtatgan
    banned: set = field(default_factory=set)     # o'yindan chiqarilganlarning ism kalitlari (shu ism bilan qaytib bo'lmaydi)
    qr: dict | None = None

    @property
    def join_url(self) -> str:
        return f"{self.join_base}/play/{self.pin}"


class OctagonHub:
    def __init__(self, db, clock):
        self.db = db
        self.clock = clock
        self.games: dict[str, Game] = {}
        self.conn_info: dict[Any, tuple] = {}  # ulanish -> ("player", pin, id) | ("host", pin, user_id)
        self.failed = RateLimiter(limit=FAIL_LIMIT, window=FAIL_WINDOW)    # noto'g'ri PIN/token urinishlari (IP bo'yicha)
        self.failed_all = RateLimiter(limit=GLOBAL_FAIL_LIMIT, window=GLOBAL_FAIL_WINDOW)  # barcha IP lardan
        self.joins = RateLimiter(limit=JOIN_LIMIT, window=JOIN_WINDOW)     # yangi o'yinchilar (bitta IP ortida butun maktab bo'lishi mumkin)
        self.rng = random.SystemRandom()
        self.sockets: dict[str, int] = {}
        self.socket_total = 0
        self._finished = 0
        self._sweep_timer = None

    def _later(self, delay: float, fn, *args):
        """Taymer: xato bo'lsa ham jarayon va boshqa o'yinlar to'xtab qolmaydi (xato jurnalga yoziladi)."""
        return self.clock.call_later(delay, self._guarded, fn, args)

    @staticmethod
    def _guarded(fn, args) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("Octagon taymerida xato: %s", getattr(fn, "__name__", fn))

    # ============================================================ ulanishlar
    def socket_opened(self, ip: str) -> bool:
        if self.socket_total >= MAX_SOCKETS or self.sockets.get(ip, 0) >= MAX_SOCKETS_PER_IP:
            return False
        self.sockets[ip] = self.sockets.get(ip, 0) + 1
        self.socket_total += 1
        return True

    def socket_closed(self, ip: str) -> None:
        n = self.sockets.get(ip, 0) - 1
        if n > 0:
            self.sockets[ip] = n
        else:
            self.sockets.pop(ip, None)
        self.socket_total = max(0, self.socket_total - 1)

    # ================================================================ o'qituvchi
    def create_game(self, owner: dict, topic: dict, rows: list[dict], settings: dict, join_base: str) -> Game:
        mine = [g for g in self.games.values() if g.owner_id == owner["id"] and g.phase != "podium"]
        if len(mine) >= MAX_GAMES_PER_OWNER:
            raise OctagonError("limit", f"Sizda {len(mine)} ta tugallanmagan oʻyin bor. Avval ularni yakunlang", 409)
        if len(self.games) >= MAX_GAMES:
            finished = sorted((g for g in self.games.values() if g.phase == "podium"), key=lambda g: g.finished_seq)
            if not finished:
                raise OctagonError("busy", "Serverda oʻyinlar juda koʻp. Birozdan keyin qayta urinib koʻring", 503)
            self.close_game(finished[0].pin, "expired")  # eng eski tugagan o'yin joy bo'shatadi
        questions, trimmed = prepare_questions(rows, settings, self.rng)
        if not questions:
            raise OctagonError("empty", "Bu mavzuda oʻyin uchun mos savol yoʻq (2–4 variantli savollar kerak)")
        pin = self._new_pin()
        game = Game(
            pin=pin,
            owner_id=owner["id"],
            owner_login=owner["login"],
            topic_id=topic["id"],
            topic_name=topic["name"],
            questions=questions,
            time_limit_ms=settings["timeLimit"] * 1000,
            settings={**settings, "questionCount": len(questions)},
            join_base=join_base.rstrip("/"),
            created_ms=_wall_ms(),
            trimmed=trimmed,
            activity=self.clock.now(),
        )
        game.qr = qr_path(game.join_url)
        self.games[pin] = game
        self._ensure_sweep()
        log.info("Octagon %s: %s (%d savol, %d s) — %s", pin, topic["name"], len(questions), settings["timeLimit"], owner["login"])
        return game

    def _new_pin(self) -> str:
        for _ in range(1000):
            pin = str(100000 + secrets.randbelow(900000))
            if pin not in self.games:
                return pin
        raise OctagonError("busy", "Boʻsh PIN topilmadi. Birozdan keyin qayta urinib koʻring", 503)

    def games_of(self, owner_id: int) -> list[Game]:
        return sorted((g for g in self.games.values() if g.owner_id == owner_id), key=lambda g: -g.created_ms)

    def owned_game(self, user: dict | None, pin) -> Game:
        """O'qituvchi o'z o'yinini boshqaradi. Huquq har safar bazadan qayta tekshiriladi (rol olib qo'yilgan bo'lishi mumkin)."""
        fresh = self.db.user_by_id(user["id"]) if user else None
        if not fresh or fresh.get("blocked") or not is_teacher(fresh):
            raise OctagonError("forbidden", "Bu amal faqat oʻqituvchi yoki administrator uchun", 403)
        game = self.games.get(norm_pin(pin) or "")
        if not game or game.owner_id != fresh["id"]:
            raise OctagonError("notfound", "Oʻyin topilmadi — u tugagan yoki oʻchirilgan boʻlishi mumkin", 404)
        return game

    def host_action(self, user: dict | None, pin, action: str, data: dict | None = None) -> Game | None:
        """O'qituvchi amallari. data.phase / data.q berilsa va hozirgi holatga mos kelmasa — amal e'tiborsiz
        qoldiriladi (ikki marta bosish yoki ikkita oyna bir bosqichni o'tkazib yubormasligi uchun)."""
        data = data or {}
        game = self.owned_game(user, pin)
        expected_phase, expected_q = data.get("phase"), data.get("q")
        if (expected_phase is not None and expected_phase != game.phase) or (expected_q is not None and expected_q != game.index):
            return game
        if action == "start":
            self._start(game)
        elif action == "next":
            self._next(game)
        elif action == "skip":
            if game.phase == "question":
                self._end_question(game)
        elif action == "end":
            self._end(game)
            if game.pin not in self.games:
                return None
        elif action == "kick":
            self._kick(game, str(data.get("id", "")))
        elif action == "settings":
            self._update_settings(game, data)
        elif action == "lock":
            game.locked = data.get("locked") is True
            self._touch(game)
            self._host_changed(game, now=True)
        elif action == "close":
            self.close_game(game.pin, "closed")
            return None
        else:
            raise OctagonError("bad", "Nomaʼlum amal")
        return game

    def end_games_of(self, owner_id: int, reason: str = "ended") -> None:
        """O'qituvchi huquqi olib qo'yilganda, bloklanganda yoki o'chirilganda — uning o'yinlari yopiladi."""
        for game in [g for g in self.games.values() if g.owner_id == owner_id]:
            self.close_game(game.pin, reason)

    def close_game(self, pin: str, reason: str = "closed") -> None:
        game = self.games.pop(pin, None)
        if not game:
            return
        _cancel(game.timer)
        _cancel(game.host_timer)
        for p in game.players.values():
            if p.conn is not None:
                self.conn_info.pop(p.conn, None)
                p.conn.send("k", {"r": "ended"})
                p.conn.close("ended", 4003)
                p.conn = None
        for c in list(game.hosts):
            self.conn_info.pop(c, None)
            c.send("closed", {"pin": pin, "reason": reason})
        game.hosts.clear()
        log.info("Octagon %s yopildi (%s)", pin, reason)

    # -------------------------------------------------------- bosqichlar
    def _touch(self, game: Game) -> None:
        game.activity = self.clock.now()

    def _set_phase(self, game: Game, phase: str) -> None:
        _cancel(game.timer)
        game.timer = None
        game.phase = phase
        self._touch(game)

    def _start(self, game: Game) -> None:
        if game.phase != "lobby":
            raise OctagonError("phase", "Oʻyin allaqachon boshlangan", 409)
        if not game.players:
            raise OctagonError("empty", "Kamida bitta oʻquvchi qoʻshilishi kerak", 409)
        self._ready(game, 0)

    def _ready(self, game: Game, index: int) -> None:
        game.index = index
        self._set_phase(game, "ready")
        game.q_open_at = self.clock.now() + config.OCTAGON_READY
        game.timer = self._later(config.OCTAGON_READY, self._open_question, game.pin, index)
        self._broadcast(game)

    def _open_question(self, pin: str, index: int) -> None:
        game = self.games.get(pin)
        if not game or game.phase != "ready" or game.index != index:
            return
        self._set_phase(game, "question")
        game.q_open_at = self.clock.now()
        game.deadline = game.q_open_at + game.time_limit_ms / 1000
        game.timer = self._later(game.time_limit_ms / 1000, self._timeout, pin, index)
        self._broadcast(game)

    def _timeout(self, pin: str, index: int) -> None:
        game = self.games.get(pin)
        if game and game.phase == "question" and game.index == index:
            self._end_question(game)

    def _end_question(self, game: Game) -> None:
        """Savol yopiladi: ballar hisoblanadi, javoblar taqsimoti saqlanadi, hamma natijani ko'radi."""
        q = game.questions[game.index]
        counts = [0] * len(q["options"])
        answered = correct = 0
        limit = game.time_limit_ms
        for p in game.players.values():
            a = p.answers.get(game.index)
            if a is None:
                p.time_ms += limit
                p.last = {"q": game.index, "ok": None, "pts": 0, "co": q["correct"]}
                continue
            choice, ms = a
            ok = choice == q["correct"]
            pts = calculate_score(ok, ms, limit)
            counts[choice] += 1
            answered += 1
            correct += ok
            p.score += pts
            p.correct += ok
            p.time_ms += ms
            p.last = {"q": game.index, "ok": ok, "pts": pts, "co": q["correct"]}
        game.stats.append({"counts": counts, "answered": answered, "correct": correct})
        self._set_phase(game, "reveal")
        self._broadcast(game)

    def _next(self, game: Game) -> None:
        if game.phase == "lobby":
            raise OctagonError("phase", "Avval oʻyinni boshlang", 409)
        if game.phase == "question":
            self._end_question(game)
        elif game.phase == "reveal":
            self._set_phase(game, "leaderboard")
            self._broadcast(game)
        elif game.phase == "leaderboard":
            if game.index + 1 < len(game.questions):
                self._ready(game, game.index + 1)
            else:
                self._finish(game)
        # ready / podium: hech narsa (sanoq tugashini kutamiz / o'yin tugagan)

    def _end(self, game: Game) -> None:
        """O'yinni muddatidan oldin tugatish. Lobbida — o'yin bekor qilinadi."""
        if game.phase == "lobby":
            self.close_game(game.pin, "cancelled")
            return
        if game.phase == "podium":
            return
        if game.phase == "question":  # shu paytgacha berilgan javoblar hisoblanadi
            self._end_question(game)
        elif game.phase == "ready":   # hali ochilmagan savol o'ynalmagan hisoblanadi
            game.index = len(game.stats) - 1
        game.ended_early = True
        self._finish(game)

    def _finish(self, game: Game) -> None:
        self._set_phase(game, "podium")
        self._broadcast(game)
        top = self.standings(game)[:3]
        log.info("Octagon %s yakunlandi: %s", game.pin, ", ".join(f"{p.nick} {p.score}" for p in top) or "o'yinchilarsiz")
        self._finished += 1
        game.finished_seq = self._finished
        # tugagan o'yinlar xotirada cheksiz to'planmasin: o'qituvchining eng avval tugagan natijalari yopiladi
        others = sorted((g for g in self.games.values() if g.owner_id == game.owner_id and g.phase == "podium" and g is not game),
                        key=lambda g: -g.finished_seq)
        for old in others[MAX_FINISHED_PER_OWNER - 1:]:
            self.close_game(old.pin, "expired")

    def _kick(self, game: Game, pid: str) -> None:
        p = game.players.pop(pid, None)
        if not p:
            return
        game.keys.pop(p.key, None)
        game.banned.add(p.key)  # shu ism bilan qaytib qo'shilib bo'lmaydi (boshqa ism bilan — mumkin)
        if p.conn is not None:
            self.conn_info.pop(p.conn, None)
            p.conn.send("k", {"r": "kicked"})
            p.conn.close("kicked", 4002)
        self._touch(game)
        self._broadcast(game)  # o'rinlar o'zgaradi

    def _update_settings(self, game: Game, data: dict) -> None:
        if game.phase != "lobby":
            raise OctagonError("locked", "Oʻyin boshlangan — sozlamalarni oʻzgartirib boʻlmaydi", 409)
        time_limit = data.get("timeLimit")
        if _int(time_limit) is None or not MIN_TIME <= time_limit <= MAX_TIME:
            raise OctagonError("settings", f"Savol vaqti {MIN_TIME}–{MAX_TIME} soniya oraligʻida butun son boʻlsin")
        game.time_limit_ms = time_limit * 1000
        game.settings["timeLimit"] = time_limit
        self._touch(game)
        self._host_changed(game, now=True)

    # ============================================================ o'quvchilar
    def handle(self, conn, msg_type, data: dict, user: dict | None = None) -> None:
        try:
            if msg_type == "ping":
                conn.send("pong", {})
            elif msg_type == "a":
                self._answer(conn, data)
            elif msg_type == "check":
                game = self._lookup(conn, data.get("pin"))
                conn.send("c", {"pin": game.pin})
            elif msg_type == "join":
                self._join(conn, data)
            elif msg_type == "resume":
                self._resume(conn, data)
            elif msg_type == "host":
                self._attach_host(conn, user, data.get("pin"))
            elif msg_type in HOST_ACTIONS:
                info = self.conn_info.get(conn)
                if not info or info[0] != "host":
                    raise OctagonError("forbidden", "Bu amal faqat oʻyinni oʻtkazayotgan oʻqituvchi uchun", 403)
                if not user:  # sessiya tugagan (tizimdan chiqilgan, parol tiklangan): boshqaruv oynasi uziladi
                    self.drop_host(conn, OctagonError("forbidden", "Sessiya tugagan — qaytadan tizimga kiring", 403))
                    return
                self.host_action(user, info[1], msg_type, data)
            else:
                raise OctagonError("bad", "Nomaʼlum soʻrov")
        except OctagonError as e:
            conn.send("e", e.payload())

    def _attempts_blocked(self, ip: str) -> bool:
        """Noto'g'ri PIN/token urinishlari: odatda IP ga FAIL_LIMIT ta; ko'p IP dan hujum paytida — SURGE_FAIL_LIMIT ta."""
        surge = self.failed_all.count("*") >= GLOBAL_FAIL_LIMIT
        return self.failed.count(ip) >= (SURGE_FAIL_LIMIT if surge else FAIL_LIMIT)

    def _failed_attempt(self, ip: str) -> None:
        self.failed.hit(ip)
        if self.failed_all.count("*") < GLOBAL_FAIL_LIMIT * 2:  # hujum aniqlanishi uchun shuning o'zi yetarli
            self.failed_all.hit("*")

    def _lookup(self, conn, pin_value) -> Game:
        ip = getattr(conn, "ip", "?")
        if self._attempts_blocked(ip):
            raise OctagonError("rate", "Juda koʻp notoʻgʻri urinish. Bir necha daqiqadan keyin qayta urinib koʻring", 429)
        game = self.games.get(norm_pin(pin_value) or "")
        if not game:
            self._failed_attempt(ip)
            raise OctagonError("pin", "Bunday PIN bilan oʻyin topilmadi. PIN ni tekshiring", 404)
        if game.phase == "podium":
            self._failed_attempt(ip)  # tugagan o'yinlar PIN larini ham bepul "skanerlab" bo'lmaydi
            raise OctagonError("ended", "Bu oʻyin tugagan", 410)
        if game.locked:
            raise OctagonError("locked", "Oʻqituvchi yangi oʻquvchilar qoʻshilishini toʻxtatgan", 423)
        return game

    def _join(self, conn, data: dict) -> None:
        if conn in self.conn_info:
            raise OctagonError("bad", "Siz allaqachon oʻyindasiz")
        game = self._lookup(conn, data.get("pin"))
        ip = getattr(conn, "ip", "?")
        if self.joins.blocked(ip):
            raise OctagonError("rate", "Bu tarmoqdan juda koʻp qoʻshilish urinishi. Birozdan keyin qayta urinib koʻring", 429)
        try:
            nick = clean_nickname(data.get("nick"))
        except NicknameError as e:
            raise OctagonError("nick", str(e))
        key = nickname_key(nick)
        if key in game.banned:
            raise OctagonError("banned", "Bu ism bilan qoʻshilib boʻlmaydi — boshqa ism tanlang", 403)
        if key in game.keys:
            raise OctagonError("taken", "Bu ism band. Boshqa ism tanlang", 409)
        if len(game.players) >= MAX_PLAYERS:
            raise OctagonError("full", "Oʻyinda joy qolmadi", 409)
        pid = secrets.token_urlsafe(6)
        while pid in game.players:
            pid = secrets.token_urlsafe(6)
        token = secrets.token_urlsafe(24)
        p = Player(id=pid, token_hash=_token_hash(token), nick=nick, key=key, conn=conn)
        p.time_ms = len(game.stats) * game.time_limit_ms  # kech qo'shilgan: o'tib ketgan savollar javobsiz hisoblanadi
        game.players[pid] = p
        game.keys[key] = pid
        self.conn_info[conn] = ("player", game.pin, pid)
        self.joins.hit(ip)
        self._touch(game)
        conn.send("w", {"pin": game.pin, "id": pid, "nick": nick, "tok": token})
        conn.send("s", self.student_state(game, p))
        self._host_changed(game)

    def _resume(self, conn, data: dict) -> None:
        """Qayta ulanish: o'sha o'yinchi (ball, javoblar, ism, o'rin) davom etadi. Eng yangi ulanish eskisini almashtiradi."""
        ip = getattr(conn, "ip", "?")
        if self._attempts_blocked(ip):
            raise OctagonError("rate", "Juda koʻp notoʻgʻri urinish. Bir necha daqiqadan keyin qayta urinib koʻring", 429)
        game = self.games.get(norm_pin(data.get("pin")) or "")
        p = game.players.get(str(data.get("id", ""))) if game else None
        token = data.get("tok")
        valid = isinstance(token, str) and TOKEN_RE.fullmatch(token) is not None
        if not p or not valid or not hmac.compare_digest(p.token_hash, _token_hash(token)):
            self._failed_attempt(ip)
            raise OctagonError("gone", "Oʻyin topilmadi yoki siz undan chiqarilgansiz", 404)
        info = self.conn_info.get(conn)
        if info and info[1:] != (game.pin, p.id):
            raise OctagonError("bad", "Bu oynada boshqa oʻyin ochiq")
        old = p.conn
        if old is not None and old is not conn:
            self.conn_info.pop(old, None)
            old.send("k", {"r": "replaced"})
            old.close("replaced", 4001)
        p.conn = conn
        self.conn_info[conn] = ("player", game.pin, p.id)
        self._touch(game)
        conn.send("w", {"pin": game.pin, "id": p.id, "nick": p.nick})
        conn.send("s", self.student_state(game, p))
        self._host_changed(game)

    def _answer(self, conn, data: dict) -> None:
        info = self.conn_info.get(conn)
        if not info or info[0] != "player":
            raise OctagonError("bad", "Avval oʻyinga qoʻshiling")
        game = self.games.get(info[1])
        p = game.players.get(info[2]) if game else None
        if not p:
            raise OctagonError("gone", "Oʻyin topilmadi yoki siz undan chiqarilgansiz", 404)
        q, choice = _int(data.get("q")), _int(data.get("o"))
        if game.phase == "ready" and q == game.index:
            raise OctagonError("early", "Savol hali ochilmagan — javob qabul qilinmadi", 409)
        if game.phase != "question" or q != game.index:
            raise OctagonError("late", "Bu savol yopilgan — javob qabul qilinmadi", 409)
        if q in p.answers:  # birinchi javob hisoblanadi, takrorlari e'tiborsiz
            conn.send("s", self.student_state(game, p))
            return
        if choice is None or not 0 <= choice < len(game.questions[q]["options"]):
            raise OctagonError("bad", "Notoʻgʻri javob")
        elapsed = round((self.clock.now() - game.q_open_at) * 1000)
        if elapsed > game.time_limit_ms:
            raise OctagonError("late", "Vaqt tugadi — javob qabul qilinmadi", 409)
        p.answers[q] = (choice, max(0, elapsed))
        self._touch(game)
        conn.send("s", self.student_state(game, p))
        connected = [x for x in game.players.values() if x.conn is not None]
        if connected and all(q in x.answers for x in connected):
            self._end_question(game)  # hamma javob berdi — vaqt tugashini kutmaymiz
        else:
            self._host_changed(game)

    def _attach_host(self, conn, user: dict | None, pin) -> None:
        game = self.owned_game(user, pin)
        info = self.conn_info.get(conn)
        if info and info[0] == "player":
            raise OctagonError("bad", "Bu oyna oʻyinchi sifatida ulangan")
        if info and info[1] != game.pin:
            old = self.games.get(info[1])
            if old:
                old.hosts.discard(conn)
        game.hosts.add(conn)
        self.conn_info[conn] = ("host", game.pin, user["id"])
        self._touch(game)
        conn.send("h", self.host_state(game))

    def drop_host(self, conn, error: OctagonError | None = None) -> None:
        """Boshqaruv oynasini o'yindan uzadi va ulanishni yopadi (4401 — qaytadan tizimga kirish kerak)."""
        info = self.conn_info.pop(conn, None)
        game = self.games.get(info[1]) if info and info[0] == "host" else None
        if game:
            game.hosts.discard(conn)
        if error:
            conn.send("e", error.payload())
        conn.close("session", 4401)

    def drop_hosts(self, user_id: int | None = None, session: str | None = None, keep: str | None = None) -> None:
        """Sessiyasi bekor bo'lgan boshqaruv oynalarini uzadi: tizimdan chiqish (session) yoki parol tiklanishi
        (user_id, keep — parolni o'zi almashtirgan foydalanuvchining joriy sessiyasi saqlanadi)."""
        for conn, info in list(self.conn_info.items()):
            if info[0] != "host":
                continue
            conn_session = getattr(conn, "session", None)
            if (user_id is not None and info[2] != user_id) or (session is not None and conn_session != session):
                continue
            if keep is not None and conn_session == keep:
                continue
            self.drop_host(conn)

    def disconnect(self, conn) -> None:
        info = self.conn_info.pop(conn, None)
        if not info:
            return
        kind, pin, ident = info
        game = self.games.get(pin)
        if not game:
            return
        if kind == "host":
            game.hosts.discard(conn)
            return
        p = game.players.get(ident)
        if p and p.conn is conn:
            p.conn = None  # ball va javoblar saqlanadi; qayta ulanganda davom etadi
            self._host_changed(game)

    # ================================================================ holat
    def standings(self, game: Game) -> list[Player]:
        """Reyting: ball (ko'p), umumiy javob vaqti (kam), ism (alifbo)."""
        return sorted(game.players.values(), key=lambda p: (-p.score, p.time_ms, p.key, p.id))

    def _ranks(self, game: Game) -> dict[str, int]:
        return {p.id: i + 1 for i, p in enumerate(self.standings(game))}

    def _remaining_ms(self, game: Game) -> int:
        end = game.q_open_at if game.phase == "ready" else game.deadline
        return max(0, round((end - self.clock.now()) * 1000))

    def student_state(self, game: Game, p: Player, ranks: dict | None = None) -> dict:
        """O'quvchiga faqat kerakli minimal ma'lumot: savol matni va variantlar yuborilmaydi."""
        ranks = ranks if ranks is not None else self._ranks(game)
        d = {"p": game.phase, "n": len(game.questions), "sc": p.score, "k": ranks.get(p.id, 0), "pl": len(game.players)}
        if game.phase in ("ready", "question", "reveal", "leaderboard"):
            d["q"] = game.index
        if game.phase in ("ready", "question"):
            d["o"] = len(game.questions[game.index]["options"])
            d["t"] = game.time_limit_ms
            d["r"] = self._remaining_ms(game)
        if game.phase in ("question", "reveal", "leaderboard"):
            a = p.answers.get(game.index)
            d["a"] = a[0] if a else None
        if game.phase in ("reveal", "leaderboard") and p.last and p.last["q"] == game.index:
            d["res"] = {"ok": p.last["ok"], "pts": p.last["pts"], "co": p.last["co"]}
        if game.phase == "podium":
            d["top"] = [[x.nick, x.score] for x in self.standings(game)[:3]]
        return d

    def host_state(self, game: Game) -> dict:
        standings = self.standings(game)
        d = {
            "pin": game.pin,
            "phase": game.phase,
            "topicName": game.topic_name,
            "total": len(game.questions),
            "index": game.index,
            "timeLimit": game.time_limit_ms // 1000,
            "settings": game.settings,
            "trimmed": game.trimmed,
            "joinUrl": game.join_url,
            "joinBase": game.join_base,
            "qr": game.qr,
            "playerCount": len(game.players),
            "connectedCount": sum(1 for p in game.players.values() if p.conn is not None),
            "endedEarly": game.ended_early,
            "locked": game.locked,
            "createdAt": game.created_ms,
        }
        if game.phase == "lobby":
            d["players"] = [{"id": p.id, "nick": p.nick, "online": p.conn is not None} for p in game.players.values()]
        if game.phase in ("ready", "question", "reveal"):
            q = game.questions[game.index]
            d["question"] = {"text": q["text"], "options": q["options"]}
        if game.phase in ("ready", "question"):
            d["remainingMs"] = self._remaining_ms(game)
        if game.phase == "question":
            d["answered"] = sum(1 for p in game.players.values() if game.index in p.answers)
        if game.phase == "reveal":
            st = game.stats[game.index]
            d["question"]["correct"] = game.questions[game.index]["correct"]
            d.update(counts=st["counts"], answered=st["answered"], correctCount=st["correct"])
        if game.phase in ("leaderboard", "podium"):
            d["leaderboard"] = [self._row(p, i) for i, p in enumerate(standings[:5])]
        if game.phase == "podium":
            d["ranking"] = [self._row(p, i) for i, p in enumerate(standings)]
            d["played"] = len(game.stats)
        return d

    def _row(self, p: Player, i: int) -> dict:
        gained = p.last["pts"] if p.last else 0
        return {"id": p.id, "nick": p.nick, "score": p.score, "gained": gained, "rank": i + 1, "correct": p.correct, "online": p.conn is not None}

    def game_summary(self, game: Game) -> dict:
        return {
            "pin": game.pin,
            "topicName": game.topic_name,
            "phase": game.phase,
            "total": len(game.questions),
            "index": game.index,
            "players": len(game.players),
            "timeLimit": game.time_limit_ms // 1000,
            "createdAt": game.created_ms,
        }

    # ========================================================= xabarlar
    def _broadcast(self, game: Game) -> None:
        """Bosqich o'zgardi: har bir o'quvchiga shaxsiy holat, o'qituvchi ekranlariga to'liq holat."""
        ranks = self._ranks(game)
        for p in game.players.values():
            if p.conn is not None:
                p.conn.send("s", self.student_state(game, p, ranks))
        self._host_changed(game, now=True)

    def _host_changed(self, game: Game, now: bool = False) -> None:
        if not game.hosts:
            return
        if now:
            _cancel(game.host_timer)
            game.host_timer = None
            self._flush_hosts(game.pin)
        elif game.host_timer is None:
            game.host_timer = self._later(HOST_FLUSH, self._flush_hosts, game.pin)

    def _flush_hosts(self, pin: str) -> None:
        game = self.games.get(pin)
        if not game:
            return
        game.host_timer = None
        state = self.host_state(game)
        for c in list(game.hosts):
            c.send("h", state)

    # ============================================================ tozalash
    def _ensure_sweep(self) -> None:
        if self._sweep_timer is None:
            self._sweep_timer = self._later(SWEEP_EVERY, self._sweep)

    def _sweep(self) -> None:
        """~2 soat faolsiz qolgan o'yinlar xotiradan o'chiriladi (bitta o'yindagi xato qolganlarini to'xtatmaydi)."""
        self._sweep_timer = None
        try:
            now = self.clock.now()
            for pin, game in list(self.games.items()):
                if now - game.activity > config.OCTAGON_TTL:
                    try:
                        self.close_game(pin, "expired")
                    except Exception:
                        log.exception("Octagon %s: tozalashda xato", pin)
        finally:
            if self.games:
                self._ensure_sweep()


def _wall_ms() -> int:
    return int(time.time() * 1000)
