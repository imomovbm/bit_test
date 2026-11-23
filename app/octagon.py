"""Octagon — jonli viktorina: o'qituvchi ekrani (proyektor) + o'quvchilar telefonlari.

Oqim (bosqichlar mashinasi — app/octagon_flow.py, vaqtlar — app/config.py): o'qituvchi mavzu va sozlamalarni tanlaydi ->
lobbi (PIN + QR kod) -> o'quvchilar telefonda PIN, ism va avatar (emoji) bilan qo'shiladi -> o'qituvchi «Boshlash»ni
bosadi -> ``topic_intro`` (mavzu nomi hamma ekranda, bir marta) -> har bir savol uchun ``question_read`` (savol matni
faqat o'qituvchi ekranida) -> ``question_active`` (javoblar) -> ``question_result`` -> ``leaderboard`` (o'rin o'zgarishlari
bilan) -> ... -> oxirgi savoldan keyin yakuniy ochilish: ``podium_intro`` -> ``reveal_3rd`` -> ``reveal_2nd`` ->
``reveal_1st`` -> ``final_results``. Podium o'rinlari faqat o'z qadami boshlanganda yuboriladi (octagon_flow.revealed_places).

Barcha holat serverda (xotirada) — server yagona manba. Hub to'liq sinxron va tashqi dunyo bilan faqat
``conn.send(type, data)``, ``conn.close(reason, code)`` va ``clock.call_later(delay, fn, *args)`` orqali bog'lanadi,
shuning uchun soxta soat bilan testlanadi (tests/test_octagon.py).

O'quvchilarga yuboriladigan xabarlar ataylab juda kichik: savol matni, variantlar matni va (savol yopilguncha) to'g'ri
javob hech qachon yuborilmaydi — faqat bosqich kodi, savol raqami, variantlar soni, bosqich vaqtlari va shaxsiy natija.

WebSocket /ws/octagon xabarlari — JSON ``{"t": tur, "d": ma'lumot}``, protokol versiyasi PROTOCOL_VERSION:
  o'quvchi -> server: sync {c} | check {v, pin} | join {v, pin, nick, av} | resume {v, pin, id, tok} | av {i} | a {q, o} | ping
  server -> o'quvchi: sync {c, s} | c {pin} | w {v, pin, id, nick, av, tn, n, tok?} | s {holat} | e {c: kod, m: matn}
                      | k {r: sabab} | reload {v} | pong
  o'qituvchi -> server: host {v, pin} | start | next | skip | end | kick {id} | settings {timeLimit} | lock {locked} | close
  server -> o'qituvchi: h {to'liq holat} | closed {pin} | e {c, m, status} | reload {v}

O'quvchi holati ``s``: p — bosqich kodi (octagon_flow.PHASES dagi indeks), q — savol indeksi (0 dan), o — variantlar
soni, ps/pe — bosqich boshlangan/tugaydigan payt (server soati, Unix ms; faqat vaqtli bosqichlarda), a — o'quvchi
tanlagan variant, sc — umumiy ball, res — savol natijasi {ok, pts, co (to'g'ri variant)}, k — o'rin, pl — o'yinchilar
soni, dk — shu savoldagi o'rin o'zgarishi (+ yuqoriga, − pastga; 1-savoldan keyin yo'q), nw — reytingda birinchi marta
(kech qo'shilgan), bh — [farq, ism]: yuqoridagi o'yinchidan necha ball orqada (yaqin bo'lsa), nc — to'g'ri javoblar
soni (yakunda), top — ochilgan podium o'rinlari [[o'rin, ism, ball, avatar], ...]. Oxirgi savol natijasida va yakuniy
ochilishda o'rin (k) faqat shu o'quvchining o'rni e'lon qilingandan keyin yuboriladi. Mijoz soatlar farqini bir marta
(``sync``) o'lchaydi va sanoqni ps/pe dan ko'rsatadi; hech qanday qaror mijoz soatiga bog'liq emas.

Javob vaqti faqat serverda o'lchanadi: ``question_active`` boshlangan paytdan (server soati) javob serverga yetib kelgan
paytgacha (o'qish bosqichi hisobga kirmaydi). Server vaqti tugagach kelgan javob qabul qilinmaydi.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import random
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from . import config
from . import octagon_flow as flow
from .observability import ERRORS, METRICS, timed
from .octagon_scoring import MAX_POINTS, biggest_jump, calculate_score, rank_changes, standing_key
from .octagon_scoring import podium as pick_podium
from .qr import qr_path
from .roles import is_teacher
from .security import RateLimiter

log = logging.getLogger("testduel.octagon")

PROTOCOL_VERSION = 3            # o'zgarsa, eski ochiq oynalar "sahifani yangilang" xabarini oladi (3 — yakuniy ochilish bosqichlari)
SNAPSHOT_VERSION = 2            # qayta ishga tushishda saqlanadigan o'yinlar formati (1 — o'qiladi va yangilanadi, boshqasi e'tiborsiz)
# Vaqtlar va chegaralar — app/config.py da (muhit o'zgaruvchilari bilan o'zgartiriladi, ishga tushishda tekshiriladi);
# bu yerdagi nomlar — qisqa taxalluslar.
MIN_TIME, MAX_TIME, DEFAULT_TIME = config.OCTAGON_TIME_MIN, config.OCTAGON_TIME_MAX, config.OCTAGON_TIME_DEFAULT
MAX_OPTIONS = 4                 # shakllar: sakkizburchak, tomchi, yulduz, plyus (static/js/octagon/common.js) — mahsulot qoidasi
MAX_QUESTIONS = config.OCTAGON_MAX_QUESTIONS
DEFAULT_QUESTIONS = config.OCTAGON_DEFAULT_QUESTIONS
NICK_MAX = 20                   # mijozdagi maxlength bilan bir xil — mahsulot qoidasi
MAX_PLAYERS = config.OCTAGON_MAX_PLAYERS
MAX_GAMES_PER_OWNER = config.OCTAGON_MAX_GAMES_PER_TEACHER
MAX_GAMES = config.OCTAGON_MAX_GAMES
MAX_SOCKETS_PER_IP = config.OCTAGON_MAX_SOCKETS_PER_IP   # bitta IP ortida butun maktab bo'lishi mumkin
MAX_SOCKETS = config.OCTAGON_MAX_SOCKETS                 # barcha IP lardan jami ochiq ulanishlar (xotira himoyasi)
FAIL_LIMIT, FAIL_WINDOW = config.OCTAGON_FAIL_LIMIT, config.OCTAGON_FAIL_WINDOW     # noto'g'ri PIN/token: IP bo'yicha
GLOBAL_FAIL_LIMIT, GLOBAL_FAIL_WINDOW = config.OCTAGON_GLOBAL_FAIL_LIMIT, config.OCTAGON_GLOBAL_FAIL_WINDOW  # PIN taxmin hujumi
SURGE_FAIL_LIMIT = config.OCTAGON_SURGE_FAIL_LIMIT       # hujum paytida bitta IP ga ruxsat etilgan noto'g'ri urinishlar
JOIN_LIMIT, JOIN_WINDOW = config.OCTAGON_JOIN_LIMIT, config.OCTAGON_JOIN_WINDOW     # yangi o'yinchilar: IP bo'yicha
MAX_FINISHED_PER_OWNER = config.OCTAGON_MAX_FINISHED_PER_TEACHER   # tugagan o'yinlar: o'qituvchi uchun
HOST_FLUSH = config.OCTAGON_HOST_FLUSH          # o'qituvchi ekranini yangilash oralig'i (qo'shilish, javoblar)
HOST_FLUSH_BIG = config.OCTAGON_HOST_FLUSH_BIG  # katta o'yinlarda (HOST_FLUSH_BIG_FROM dan ko'p o'yinchi)
HOST_FLUSH_BIG_FROM = config.OCTAGON_HOST_FLUSH_BIG_FROM
BOARD_SIZE = 5                  # o'qituvchi ekranidagi reyting: eng yaxshi 5 talik
# O'yin davomida o'zgarmaydigan maydonlar: o'qituvchi oynasi ulanganda bir marta yuboriladi, keyingi yangilanishlarda
# takrorlanmaydi (QR kodning o'zi ~3 KB).
HOST_STATIC = ("qr", "joinUrl", "joinBase", "topicName", "createdAt")
SWEEP_EVERY = config.OCTAGON_SWEEP_EVERY
PIN_RE = re.compile(r"^[1-9][0-9]{5}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
LONG_OPTIONS = ("trim", "skip")  # 4 tadan ko'p variantli savollar: qisqartirish yoki o'tkazib yuborish
HOST_ACTIONS = ("start", "next", "skip", "end", "kick", "settings", "lock", "close")  # faqat o'yin egasi (WebSocket)
HANDSHAKES = ("check", "join", "resume", "host")  # protokol versiyasi tekshiriladigan xabarlar
RELOAD_TEXT = "Sayt yangilandi — davom etish uchun sahifani yangilang"
# v1 sahifalar "reload" xabarini bilmaydi: ular ham ko'rsatadigan xato kodlari (PIN maydoni ostida / bildirishnoma)
LEGACY_RELOAD_CODE = {"check": "pin", "join": "pin", "resume": "gone", "host": "reload"}

# Avatarlar: oddiy, eski telefonlarda ham bir xil ko'rinadigan emojilar (bitta kod nuqtasi, Unicode ≤ 6.0; teri rangi,
# bayroq va ZWJ ketma-ketliklari yo'q). Simda faqat indeks yuboriladi; static/js/octagon/common.js dagi AVATARS bilan
# bir xil tartibda (tests/test_octagon_avatars.py tekshiradi).
AVATARS = (
    "🐶", "🐱", "🐭", "🐹", "🐰", "🐺", "🐻", "🐼", "🐨", "🐯", "🐲", "🐸", "🐵", "🐧", "🐢",
    "🐙", "🐬", "🐳", "🐝", "🐞", "🍎", "🍉", "🍓", "🍕", "⚽", "🏀", "🚀", "🎈", "🎸", "🌈",
)


def timings() -> dict[str, float]:
    """Bosqich vaqtlari (soniya) — har safar app/config.py dan o'qiladi (octagon_flow.duration uchun)."""
    return {"intro": config.OCTAGON_INTRO, "read": config.OCTAGON_READ, "podium": config.OCTAGON_PODIUM_INTRO,
            "reveal": config.OCTAGON_REVEAL_STEP, "winner": config.OCTAGON_REVEAL_WINNER}


def clean_avatar(value) -> int:
    """Avatar — faqat ro'yxatdagi indeks (butun son). Emoji matni, kasr, bool, boshqa tur — rad etiladi."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(AVATARS):
        raise OctagonError("avatar", "Avatar notoʻgʻri — roʻyxatdan tanlang")
    return value


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
    last: dict | None = None       # oxirgi yopilgan savol natijasi {q, ok, pts, co, d — o'rin o'zgarishi yoki None}
    conn: Any = None
    avatar: int = 0                # AVATARS dagi indeks (qayta ulanganda ham saqlanadi)
    late: bool = False             # o'yin boshlangandan keyin qo'shilgan (reytingda birinchi marta — «YANGI»)
    first_q: int = 0               # birinchi marta qaysi savol reytingida qatnashadi (undan oldingi reytingda yo'q)
    after_end: bool = False        # savollar tugagandan keyin (yakuniy ochilish paytida) qo'shilgan — reyting oxirida


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
    phase: str = flow.LOBBY        # octagon_flow.PHASES
    index: int = -1
    phase_start: float = 0.0       # joriy bosqich boshlangan payt (server monoton soati)
    phase_end: float | None = None  # vaqtli bosqich tugaydigan payt (topic_intro, question_read, question_active)
    q_open_at: float = 0.0         # savol javoblar uchun ochilgan payt (question_active boshlanishi)
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
    podium: list = field(default_factory=list)   # yakunda muzlatilgan [1-, 2-, 3-o'rin] o'yinchi id lari (kam bo'lishi mumkin)

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
        # Unix vaqti (ms) = _epoch0 + monoton soat * 1000: mijozlarga mutlaq vaqtlar shu orqali yuboriladi.
        # Birinchi ishlatilganda hisoblanadi: ilova yig'ilayotganda hodisalar tsikli (loop soati) hali ishlamaydi.
        self._epoch0: float | None = None

    def wall_ms(self, mono: float | None = None) -> int:
        """Server monoton soatidagi payt -> Unix vaqti (ms). Mijoz sanoqlari uchun (qarorlar monoton soat bilan)."""
        now = self.clock.now()
        if self._epoch0 is None:
            self._epoch0 = time.time() * 1000 - now * 1000
        return round(self._epoch0 + (now if mono is None else mono) * 1000)

    def _later(self, delay: float, fn, *args):
        """Taymer: xato bo'lsa ham jarayon va boshqa o'yinlar to'xtab qolmaydi (xato jurnalga yoziladi)."""
        return self.clock.call_later(delay, self._guarded, fn, args)

    @staticmethod
    def _guarded(fn, args) -> None:
        try:
            fn(*args)
        except Exception:
            ERRORS.report("octagon_timer", f"Octagon taymerida xato: {getattr(fn, '__name__', fn)}", exc=True)

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
        mine = [g for g in self.games.values() if g.owner_id == owner["id"] and g.phase not in flow.FINISHED]
        if len(mine) >= MAX_GAMES_PER_OWNER:
            raise OctagonError("limit", f"Sizda {len(mine)} ta tugallanmagan oʻyin bor. Avval ularni yakunlang", 409)
        if len(self.games) >= MAX_GAMES:
            finished = sorted((g for g in self.games.values() if g.phase in flow.FINISHED), key=lambda g: g.finished_seq)
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
        METRICS.inc("octagon_games_created_total")
        log.info("Octagon %s yaratildi: mavzu #%s, %d savol, %d s, o'qituvchi #%s", pin, topic["id"], len(questions),
                 settings["timeLimit"], owner["id"])  # jurnalda ism va loginlar yo'q — faqat identifikatorlar
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
            self._skip(game)
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
        """Bosqich almashadi: o'tish qonuniyligi tekshiriladi (octagon_flow.TRANSITIONS), eski taymer bekor qilinadi,
        vaqtli bosqich uchun (octagon_flow.duration, vaqtlar — app/config.py) yangi taymer qo'yiladi."""
        flow.check(game.phase, phase)
        _cancel(game.timer)
        game.timer = None
        game.phase = phase
        game.phase_start = self.clock.now()
        length = flow.duration(phase, game.time_limit_ms / 1000, timings())
        game.phase_end = game.phase_start + length if length is not None else None
        if length is not None:
            game.timer = self._later(length, self._phase_timer, game.pin, phase, game.index)
        self._touch(game)

    def _phase_timer(self, pin: str, phase: str, index: int) -> None:
        """Vaqtli bosqich tugadi. O'yin yopilgan, bosqich o'tkazib yuborilgan yoki boshqa savolga o'tilgan bo'lsa — eski
        taymer hech narsa qilmaydi."""
        game = self.games.get(pin)
        if not game or game.phase != phase or game.index != index:
            return
        if phase == flow.INTRO:
            self._read(game, 0)
        elif phase == flow.READ:
            self._open_question(game)
        elif phase == flow.ACTIVE:
            self._end_question(game)
        elif phase in flow.SHOWING:
            self._reveal(game, flow.after_timer(phase, len(game.podium)))

    def _start(self, game: Game) -> None:
        if game.phase != flow.LOBBY:
            raise OctagonError("phase", "Oʻyin allaqachon boshlangan", 409)
        if not game.players:
            raise OctagonError("empty", "Kamida bitta oʻquvchi qoʻshilishi kerak", 409)
        self._set_phase(game, flow.INTRO)  # mavzu nomi — bir marta, 1-savoldan oldin
        self._broadcast(game)

    def _read(self, game: Game, index: int) -> None:
        """Savolni o'qish: matn faqat o'qituvchi ekranida, javob tugmalari hali yopiq."""
        game.index = index
        self._set_phase(game, flow.READ)
        self._broadcast(game)

    def _open_question(self, game: Game) -> None:
        self._set_phase(game, flow.ACTIVE)
        game.q_open_at = game.phase_start       # javob vaqti shu paytdan o'lchanadi
        game.deadline = game.q_open_at + game.time_limit_ms / 1000
        self._broadcast(game)

    @staticmethod
    def _standing(p: Player) -> tuple[str, int, int, str]:
        return (p.id, p.score, p.time_ms, p.key)

    def _end_question(self, game: Game) -> None:
        """Savol yopiladi: ballar hisoblanadi, o'rin o'zgarishlari (savoldan oldingi va keyingi reyting) saqlanadi,
        javoblar taqsimoti saqlanadi, hamma natijani ko'radi."""
        q = game.questions[game.index]
        # oldingi reyting: 1-savolda yo'q; keyin — shu savolgacha reytingda qatnashganlar (shu savol paytida
        # qo'shilganlar unda yo'q — ularda «YANGI»)
        before = [self._standing(p) for p in game.players.values() if p.first_q < game.index] if game.stats else None
        counts = [0] * len(q["options"])
        answered = correct = 0
        limit = game.time_limit_ms
        for p in game.players.values():
            a = p.answers.get(game.index)
            if a is None:
                p.time_ms += limit
                p.last = {"q": game.index, "ok": None, "pts": 0, "co": q["correct"], "d": None}
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
            p.last = {"q": game.index, "ok": ok, "pts": pts, "co": q["correct"], "d": None}
        changes = rank_changes(before, [self._standing(p) for p in game.players.values()])
        for p in game.players.values():
            p.last["d"] = changes[p.id][2]
        game.stats.append({"counts": counts, "answered": answered, "correct": correct})
        self._set_phase(game, flow.RESULT)
        self._broadcast(game)

    def _next(self, game: Game) -> None:
        if game.phase == flow.LOBBY:
            raise OctagonError("phase", "Avval oʻyinni boshlang", 409)
        nxt = flow.on_next(game.phase, game.index + 1 < len(game.questions), len(game.podium))
        if game.phase in flow.SHOWING:
            if nxt:
                self._reveal(game, nxt)
        elif nxt == flow.RESULT:
            self._end_question(game)
        elif nxt == flow.BOARD:
            self._set_phase(game, flow.BOARD)
            self._broadcast(game)
        elif nxt == flow.READ:
            self._read(game, game.index + 1)
        elif nxt == flow.PODIUM_INTRO:
            self._finish(game)
        # topic_intro / question_read / final_results: hech narsa (taymer tugaydi yoki «o'tkazib yuborish»)

    def _skip(self, game: Game) -> None:
        """O'qituvchi mavzu kirishini yoki o'qish vaqtini qisqartiradi, savolni muddatidan oldin yopadi, yakuniy
        ochilishdan darhol natijalarga o'tadi."""
        nxt = flow.on_skip(game.phase)
        if nxt == flow.READ:
            self._read(game, 0)
        elif nxt == flow.ACTIVE:
            self._open_question(game)
        elif nxt == flow.RESULT:
            self._end_question(game)
        elif nxt == flow.FINAL:
            self._reveal(game, flow.FINAL)

    def _end(self, game: Game) -> None:
        """O'yinni muddatidan oldin tugatish. Lobbida — o'yin bekor qilinadi."""
        if game.phase == flow.LOBBY:
            self.close_game(game.pin, "cancelled")
            return
        if game.phase in flow.FINISHED:
            return
        if game.phase == flow.ACTIVE:  # shu paytgacha berilgan javoblar hisoblanadi
            self._end_question(game)
        elif game.phase in (flow.INTRO, flow.READ):   # hali ochilmagan savol o'ynalmagan hisoblanadi
            game.index = len(game.stats) - 1
        game.ended_early = len(game.stats) < len(game.questions)
        self._finish(game)

    def _finish(self, game: Game) -> None:
        """Savollar tugadi: reyting muzlatiladi (ballar endi o'zgarmaydi, chiqarish yopiq), podium tanlanadi va yakuniy
        ochilish boshlanadi (ochiladigan hech kim bo'lmasa — darhol natijalar)."""
        order = self.standings(game)
        game.podium = pick_podium([p.id for p in order], any(p.score > 0 for p in order), game.ended_early)
        self._set_phase(game, flow.finish_phase(len(game.podium)))
        self._broadcast(game)
        METRICS.inc("octagon_games_finished_total")
        log.info("Octagon %s yakunlandi: %d o'yinchi, %d savol o'ynaldi%s", game.pin, len(game.players), len(game.stats),
                 " (muddatidan oldin)" if game.ended_early else "")
        self._finished += 1
        game.finished_seq = self._finished
        # tugagan o'yinlar xotirada cheksiz to'planmasin: o'qituvchining eng avval tugagan natijalari yopiladi
        others = sorted((g for g in self.games.values() if g.owner_id == game.owner_id and g.phase in flow.FINISHED and g is not game),
                        key=lambda g: -g.finished_seq)
        for old in others[MAX_FINISHED_PER_OWNER - 1:]:
            self.close_game(old.pin, "expired")

    def _reveal(self, game: Game, phase: str) -> None:
        """Yakuniy ochilishning keyingi qadami (taymer, «Keyingi» yoki «O'tkazib yuborish»)."""
        self._set_phase(game, phase)
        self._broadcast(game)

    def _kick(self, game: Game, pid: str) -> None:
        if game.phase in flow.FINISHED:  # podium muzlatilgan — o'rinlar ochilish paytida o'zgarmasin
            raise OctagonError("finished", "Oʻyin tugagan — endi oʻquvchini chiqarib boʻlmaydi", 409)
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
        if not self._close_if_all_answered(game):  # qolganlarning hammasi javob bergan bo'lishi mumkin
            self._broadcast(game)  # o'rinlar o'zgaradi

    def _update_settings(self, game: Game, data: dict) -> None:
        if game.phase != flow.LOBBY:
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
            if msg_type in HANDSHAKES and data.get("v") != PROTOCOL_VERSION:
                # eski (yangilanmagan) sahifa: jim buzilmasin — "sahifani yangilang" xabari
                conn.send("reload", {"v": PROTOCOL_VERSION})
                if "v" not in data:  # v1 sahifa: o'zi tushunadigan xato ko'rinishida
                    conn.send("e", {"c": LEGACY_RELOAD_CODE[msg_type], "m": RELOAD_TEXT, "status": 426})
                return
            if msg_type == "ping":
                conn.send("pong", {})
            elif msg_type == "sync":  # soatlar farqini o'lchash (mijoz faqat sanoqni ko'rsatish uchun ishlatadi)
                c = data.get("c")
                conn.send("sync", {"c": c if isinstance(c, (int, float)) and not isinstance(c, bool) else None, "s": self.wall_ms()})
            elif msg_type == "a":
                self._answer(conn, data)
            elif msg_type == "av":
                self._set_avatar(conn, data)
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
        if not flow.can_join(game.phase):
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
        avatar = clean_avatar(data.get("av"))
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
        p = Player(id=pid, token_hash=_token_hash(token), nick=nick, key=key, conn=conn, avatar=avatar)
        p.time_ms = len(game.stats) * game.time_limit_ms  # kech qo'shilgan: o'tib ketgan savollar javobsiz hisoblanadi
        p.late = game.phase != flow.LOBBY
        p.first_q = max(game.index, 0)             # natija/reytingda qo'shilsa — shu savol reytingida ko'rinadi
        p.after_end = game.phase in flow.FINISHED  # ochilish paytida: podiumga kira olmaydi, reyting oxirida
        game.players[pid] = p
        game.keys[key] = pid
        self.conn_info[conn] = ("player", game.pin, pid)
        self.joins.hit(ip)
        self._touch(game)
        METRICS.inc("octagon_joins_total")
        conn.send("w", {**self._welcome(game, p), "tok": token})
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
        conn.send("w", self._welcome(game, p))
        conn.send("s", self.student_state(game, p))
        self._host_changed(game)

    def _welcome(self, game: Game, p: Player) -> dict:
        """O'quvchiga bir marta (qo'shilish/qayta ulanishda): o'zgarmaydigan ma'lumotlar holat xabarlarida takrorlanmaydi."""
        return {"v": PROTOCOL_VERSION, "pin": game.pin, "id": p.id, "nick": p.nick, "av": p.avatar,
                "tn": game.topic_name, "n": len(game.questions)}

    def _player_of(self, conn) -> tuple[Game, Player]:
        info = self.conn_info.get(conn)
        if not info or info[0] != "player":
            raise OctagonError("bad", "Avval oʻyinga qoʻshiling")
        game = self.games.get(info[1])
        p = game.players.get(info[2]) if game else None
        if not p:
            raise OctagonError("gone", "Oʻyin topilmadi yoki siz undan chiqarilgansiz", 404)
        return game, p

    def _set_avatar(self, conn, data: dict) -> None:
        """Avatarni lobbida (o'yin boshlanguncha) almashtirish mumkin."""
        game, p = self._player_of(conn)
        avatar = clean_avatar(data.get("i"))
        if game.phase != flow.LOBBY:
            raise OctagonError("started", "Oʻyin boshlangan — avatarni endi oʻzgartirib boʻlmaydi", 409)
        if avatar != p.avatar:
            p.avatar = avatar
            self._touch(game)
            self._host_changed(game)
        conn.send("w", self._welcome(game, p))

    def _answer(self, conn, data: dict) -> None:
        game, p = self._player_of(conn)
        q, choice = _int(data.get("q")), _int(data.get("o"))
        upcoming = 0 if game.phase == flow.INTRO else game.index
        if game.phase in (flow.INTRO, flow.READ) and q == upcoming:
            raise OctagonError("early", "Savol hali ochilmagan — javob qabul qilinmadi", 409)
        if not flow.can_answer(game.phase) or q != game.index:
            raise OctagonError("late", "Bu savol yopilgan — javob qabul qilinmadi", 409)
        if q in p.answers:  # birinchi javob hisoblanadi, takrorlari e'tiborsiz
            conn.send("s", self.student_state(game, p))
            return
        if choice is None or not 0 <= choice < len(game.questions[q]["options"]):
            raise OctagonError("bad", "Notoʻgʻri javob")
        elapsed = round((self.clock.now() - game.q_open_at) * 1000)
        if elapsed > game.time_limit_ms:  # aynan chegaradagi (== taymer) javob qabul qilinadi
            raise OctagonError("late", "Vaqt tugadi — javob qabul qilinmadi", 409)
        p.answers[q] = (choice, max(0, elapsed))
        METRICS.inc("octagon_answers_total")
        self._touch(game)
        conn.send("s", self.student_state(game, p))
        if not self._close_if_all_answered(game):
            self._host_changed(game)

    def _close_if_all_answered(self, game: Game) -> bool:
        """Ulangan o'yinchilarning hammasi javob bergan bo'lsa — vaqt tugashini kutmasdan savol yopiladi."""
        if game.phase != flow.ACTIVE:
            return False
        connected = [x for x in game.players.values() if x.conn is not None]
        if connected and all(game.index in x.answers for x in connected):
            self._end_question(game)
            return True
        return False

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
        conn.send("h", self.host_state(game))  # to'liq holat (o'zgarmas maydonlar ham)

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
        """Reyting: ball (ko'p), umumiy javob vaqti (kam), ism (alifbo) — octagon_scoring.standing_key. Yakuniy ochilish
        paytida qo'shilganlar (after_end) har doim oxirida: tugagan o'yin reytingi va podium o'zgarmaydi."""
        return sorted(game.players.values(), key=lambda p: (p.after_end, *standing_key(p.score, p.time_ms, p.key, p.id)))

    def _times(self, game: Game) -> tuple[int, int] | None:
        """Vaqtli bosqichning boshlanishi va tugashi — Unix ms (server soati)."""
        if game.phase_end is None:
            return None
        return self.wall_ms(game.phase_start), self.wall_ms(game.phase_end)

    @staticmethod
    def _last_question(game: Game) -> bool:
        return game.index + 1 >= len(game.questions)

    def _ranked(self, game: Game) -> bool:
        """Shu bosqichda o'rinlar ko'rsatiladimi. Oxirgi savol natijasida — yo'q: yakuniy o'rinlar faqat ochilish
        qadamlarida, birma-bir e'lon qilinadi (oldindan sizib chiqmasin)."""
        return game.phase == flow.FINAL or (game.phase in (flow.RESULT, flow.BOARD) and not self._last_question(game))

    def _revealed(self, game: Game) -> list[tuple[int, Player]]:
        """E'lon qilingan podium o'rinlari (o'rin bo'yicha: 1, 2, 3) — faqat octagon_flow.revealed_places ruxsat berganlari."""
        shown = flow.revealed_places(game.phase, len(game.podium))
        out = []
        for place in sorted(shown):
            pl = game.players.get(game.podium[place - 1])
            if pl is not None:
                out.append((place, pl))
        return out

    def _shared(self, game: Game) -> dict:
        """Bitta tarqatishdagi umumiy hisoblar: reyting bir marta saralanadi, podium bir marta tayyorlanadi."""
        sh: dict[str, Any] = {}
        if self._ranked(game):
            order = self.standings(game)
            sh["order"] = order
            sh["rank"] = {p.id: i for i, p in enumerate(order, 1)}
        if game.phase in flow.FINISHED:
            top = self._revealed(game)
            sh["top"] = [[place, x.nick, x.score, x.avatar] for place, x in top]
            sh["place"] = {x.id: place for place, x in top}
        return sh

    def student_state(self, game: Game, p: Player, shared: dict | None = None) -> dict:
        """O'quvchiga faqat ekrani uchun kerakli minimal ma'lumot: o'z natijasi, o'rni va o'zgarishi, e'lon qilingan
        podium. Savol va variant matnlari, boshqalarning ro'yxati va hali e'lon qilinmagan o'rinlar yuborilmaydi."""
        sh = shared if shared is not None else self._shared(game)
        phase = game.phase
        d = {"p": flow.CODE[phase], "sc": p.score}
        if phase in flow.WITH_QUESTION:
            d["q"] = game.index
        if phase in (flow.READ, flow.ACTIVE):
            d["o"] = len(game.questions[game.index]["options"])
        times = self._times(game)
        if times:
            d["ps"], d["pe"] = times
        if phase in (flow.ACTIVE, flow.RESULT, flow.BOARD):
            a = p.answers.get(game.index)
            d["a"] = a[0] if a else None
        if phase in (flow.RESULT, flow.BOARD):
            scored = p.last is not None and p.last["q"] == game.index
            if scored:
                d["res"] = {"ok": p.last["ok"], "pts": p.last["pts"], "co": p.last["co"]}
            if "rank" in sh:
                k = sh["rank"][p.id]
                d["k"], d["pl"] = k, len(game.players)
                delta = p.last.get("d") if scored else None
                if delta is not None:
                    d["dk"] = delta
                if p.late and p.first_q == game.index:
                    d["nw"] = 1
                if k > 1:  # yuqoridagi o'yinchiga yaqin bo'lsa (bitta savolda quvib yetish mumkin) — "N ball orqada"
                    above = sh["order"][k - 2]
                    gap = above.score - p.score
                    if 0 < gap <= MAX_POINTS:
                        d["bh"] = [gap, above.nick]
        if phase in flow.FINISHED:
            d["top"] = sh["top"]
            if phase == flow.FINAL:
                d["k"], d["pl"], d["nc"] = sh["rank"][p.id], len(game.players), p.correct
            elif p.id in sh["place"]:  # o'z o'rni e'lon qilindi — telefonida ham shu paytdan
                d["k"] = sh["place"][p.id]
        return d

    def host_state(self, game: Game, full: bool = True) -> dict:
        """O'qituvchi ekrani holati. full=False — yangilanish: HOST_STATIC maydonlarisiz (mijoz ularni saqlab qoladi)."""
        d = {
            "v": PROTOCOL_VERSION,
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
        times = self._times(game)
        if times:
            d["phaseStart"], d["phaseEnd"] = times
        if game.phase == flow.LOBBY:
            d["players"] = [{"id": p.id, "nick": p.nick, "av": p.avatar, "online": p.conn is not None} for p in game.players.values()]
        if game.phase in (flow.READ, flow.ACTIVE, flow.RESULT):
            q = game.questions[game.index]
            d["question"] = {"text": q["text"], "options": q["options"]}
        if game.phase == flow.ACTIVE:
            d["answered"] = sum(1 for p in game.players.values() if game.index in p.answers)
        if game.phase == flow.RESULT:
            st = game.stats[game.index]
            d["question"]["correct"] = game.questions[game.index]["correct"]
            d.update(counts=st["counts"], answered=st["answered"], correctCount=st["correct"])
        if game.phase == flow.BOARD and self._ranked(game):
            order = self.standings(game)  # saralash faqat kerak bo'lganda
            d["leaderboard"] = [self._board_row(game, p, i) for i, p in enumerate(order[:BOARD_SIZE])]
            d["jump"] = self._jump(game, order)
        if game.phase in flow.FINISHED:
            d["places"] = len(game.podium)
            d["podium"] = [{**self._row(x, place - 1), "place": place} for place, x in self._revealed(game)]
            if game.phase == flow.FINAL:
                d["ranking"] = [self._row(p, i) for i, p in enumerate(self.standings(game))]
                d["played"] = len(game.stats)
        if not full:
            for key in HOST_STATIC:
                d.pop(key, None)
        return d

    @staticmethod
    def _row(p: Player, i: int) -> dict:
        return {"id": p.id, "nick": p.nick, "av": p.avatar, "score": p.score, "rank": i + 1, "correct": p.correct,
                "online": p.conn is not None}

    def _board_row(self, game: Game, p: Player, i: int) -> dict:
        """Reyting qatori: shu savolda olingan ball, o'rin o'zgarishi (d: + yuqoriga, − pastga, None — strelkasiz)
        va «YANGI» belgisi (kech qo'shilgan o'yinchining birinchi reytingi)."""
        scored = p.last is not None and p.last["q"] == game.index
        return {**self._row(p, i), "gained": p.last["pts"] if scored else 0, "d": p.last.get("d") if scored else None,
                "new": p.late and p.first_q == game.index}

    @staticmethod
    def _jump(game: Game, order: list[Player]) -> dict | None:
        """Savolning eng katta ko'tarilishi (kamida 2 o'rin) — o'qituvchi ekranidagi alohida qator uchun."""
        changes = {p.id: (None, i, p.last.get("d") if p.last and p.last["q"] == game.index else None)
                   for i, p in enumerate(order, 1)}
        best = biggest_jump(changes)
        if not best:
            return None
        p = game.players[best[0]]
        return {"id": p.id, "nick": p.nick, "av": p.avatar, "d": best[1], "rank": changes[p.id][1]}

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
        with timed("octagon_broadcast_ms"):  # xabarlarni tayyorlab navbatga qo'yish (yuborish — har ulanish o'z navbatida)
            shared = self._shared(game)
            for p in game.players.values():
                if p.conn is not None:
                    p.conn.send("s", self.student_state(game, p, shared))
            self._host_changed(game, now=True)

    def _host_changed(self, game: Game, now: bool = False) -> None:
        if not game.hosts:
            return
        if now:
            _cancel(game.host_timer)
            game.host_timer = None
            self._flush_hosts(game.pin)
        elif game.host_timer is None:
            every = HOST_FLUSH_BIG if len(game.players) > HOST_FLUSH_BIG_FROM else HOST_FLUSH
            game.host_timer = self._later(every, self._flush_hosts, game.pin)

    def _flush_hosts(self, pin: str) -> None:
        game = self.games.get(pin)
        if not game:
            return
        game.host_timer = None
        state = self.host_state(game, full=False)
        for c in list(game.hosts):
            c.send("h", state)

    # ============================================== qayta ishga tushish (o'yinlar saqlanadi)
    def snapshot(self) -> dict:
        """Xotiradagi barcha o'yinlar — to'xtashdan oldin diskka yoziladi (app/ops.py). Vaqtlar mutlaq emas: bosqich
        boshidan o'tgan va oxirigacha qolgan soniyalar saqlanadi, ya'ni server to'xtab turgan vaqt o'yinga pauza bo'ladi
        (savol vaqti yeyilmaydi). Tokenlarning o'zi emas, faqat xeshi saqlanadi."""
        now = self.clock.now()
        return {"v": SNAPSHOT_VERSION, "savedAt": self.wall_ms(), "games": [self._dump(g, now) for g in self.games.values()]}

    @staticmethod
    def _dump(g: Game, now: float) -> dict:
        return {
            "pin": g.pin, "ownerId": g.owner_id, "ownerLogin": g.owner_login, "topicId": g.topic_id, "topicName": g.topic_name,
            "questions": g.questions, "timeLimitMs": g.time_limit_ms, "settings": g.settings, "joinBase": g.join_base,
            "createdMs": g.created_ms, "trimmed": g.trimmed, "phase": g.phase, "index": g.index,
            "elapsed": max(0.0, now - g.phase_start),
            "remaining": None if g.phase_end is None else max(0.0, g.phase_end - now),
            "qElapsed": max(0.0, now - g.q_open_at) if g.phase == flow.ACTIVE else None,
            "idle": max(0.0, now - g.activity),
            "players": [{"id": p.id, "tokenHash": p.token_hash, "nick": p.nick, "key": p.key, "score": p.score,
                         "timeMs": p.time_ms, "correct": p.correct, "answers": [[q, o, ms] for q, (o, ms) in p.answers.items()],
                         "last": p.last, "avatar": p.avatar, "late": p.late, "firstQ": p.first_q, "afterEnd": p.after_end}
                        for p in g.players.values()],
            "stats": g.stats, "endedEarly": g.ended_early, "finishedSeq": g.finished_seq, "locked": g.locked,
            "banned": sorted(g.banned), "qr": g.qr, "podium": g.podium,
        }

    def restore(self, data: dict) -> int:
        """Saqlangan o'yinlarni tiklaydi (ishga tushishda). Taymerlar qolgan vaqt bilan qayta qo'yiladi; o'quvchilar va
        o'qituvchi oynalari avtomatik qayta ulanadi (resume/host) va o'sha joydan davom etadi."""
        if not isinstance(data, dict) or data.get("v") not in (1, SNAPSHOT_VERSION):
            return 0
        saved = data.get("savedAt")
        down = max(0.0, (self.wall_ms() - saved) / 1000) if isinstance(saved, (int, float)) else 0.0
        restored = 0
        for d in data.get("games") or []:
            try:
                game = self._load(d, down, data["v"])
            except Exception:
                ERRORS.report("octagon_restore", "Saqlangan o'yinni tiklab bo'lmadi", exc=True)
                continue
            if game.pin in self.games:
                continue
            self.games[game.pin] = game
            self._finished = max(self._finished, game.finished_seq)
            if game.phase in flow.TIMED:  # taymer qolgan vaqt bilan (to'xtab turgan vaqt — pauza)
                remaining = max(0.0, game.phase_end - self.clock.now()) if game.phase_end is not None else 0.0
                game.timer = self._later(remaining, self._phase_timer, game.pin, game.phase, game.index)
            restored += 1
        if restored:
            self._ensure_sweep()
            log.info("Octagon: %d ta o'yin tiklandi (server %.1f s to'xtab turdi)", restored, down)
        return restored

    def _load(self, d: dict, down: float, version: int = SNAPSHOT_VERSION) -> Game:
        now = self.clock.now()
        phase = d["phase"]
        if version == 1 and phase == "podium":  # v1: yakuniy natijalar bitta "podium" bosqichi edi
            phase = flow.FINAL
        if phase not in flow.PHASES or not PIN_RE.match(str(d["pin"])):
            raise ValueError("noto'g'ri o'yin yozuvi")
        g = Game(pin=d["pin"], owner_id=int(d["ownerId"]), owner_login=d["ownerLogin"], topic_id=int(d["topicId"]),
                 topic_name=d["topicName"], questions=d["questions"], time_limit_ms=int(d["timeLimitMs"]),
                 settings=d["settings"], join_base=d["joinBase"], created_ms=int(d["createdMs"]), trimmed=int(d["trimmed"]))
        g.phase, g.index = phase, int(d["index"])
        g.phase_start = now - float(d["elapsed"])
        g.phase_end = None if d["remaining"] is None else now + float(d["remaining"])
        if g.phase == flow.ACTIVE:
            g.q_open_at = now - float(d["qElapsed"])
            g.deadline = g.q_open_at + g.time_limit_ms / 1000
        g.activity = now - float(d["idle"]) - down
        for pd in d["players"]:
            p = Player(id=pd["id"], token_hash=pd["tokenHash"], nick=pd["nick"], key=pd["key"], score=int(pd["score"]),
                       time_ms=int(pd["timeMs"]), correct=int(pd["correct"]), last=pd["last"], avatar=clean_avatar(pd["avatar"]),
                       late=bool(pd.get("late", False)), first_q=int(pd.get("firstQ", 0)), after_end=bool(pd.get("afterEnd", False)))
            p.answers = {int(q): (int(o), int(ms)) for q, o, ms in pd["answers"]}
            g.players[p.id] = p
            g.keys[p.key] = p.id
        g.stats, g.ended_early, g.finished_seq = d["stats"], bool(d["endedEarly"]), int(d["finishedSeq"])
        g.locked, g.banned, g.qr = bool(d["locked"]), set(d["banned"]), d["qr"]
        if version == 1:  # v1 da podium saqlanmagan: tugagan o'yin uchun reytingdan olinadi
            order = self.standings(g)
            g.podium = pick_podium([p.id for p in order], any(p.score > 0 for p in order), g.ended_early) if phase == flow.FINAL else []
        else:
            g.podium = [str(x) for x in d["podium"] if str(x) in g.players][:3]
            if phase in flow.SHOWING and len(g.podium) != len(d["podium"]):
                raise ValueError("podium yozuvi buzilgan")
        return g

    def shutdown(self, code: int = 1012) -> dict:
        """Server to'xtamoqda: holat olinadi, taymerlar to'xtatiladi (keyin hech narsa o'zgarmaydi), ulangan o'quvchi va
        o'qituvchilarga 1012 (xizmat qayta ishga tushmoqda) bilan yopiladi — ular avtomatik qayta ulanadi."""
        data = self.snapshot()
        for g in self.games.values():
            _cancel(g.timer)
            _cancel(g.host_timer)
            g.timer = g.host_timer = None
            for p in g.players.values():
                if p.conn is not None:
                    p.conn.close("restart", code)
            for c in list(g.hosts):
                c.close("restart", code)
        _cancel(self._sweep_timer)
        self._sweep_timer = None
        return data

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
                        ERRORS.report("octagon_sweep", "Octagon tozalashda xato", exc=True, pin=pin)
        finally:
            if self.games:
                self._ensure_sweep()


def _wall_ms() -> int:
    return int(time.time() * 1000)
