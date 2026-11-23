"""TestDuel sozlamalari — barcha vaqtlar, chegaralar va bo'sag'alar shu yerda.

Har bir qiymatni muhit o'zgaruvchisi (environment variable) orqali o'zgartirish mumkin,
masalan:  set TD_PORT=9000  (Windows)  yoki  TD_PORT=9000 python run.py  (Linux).

Ishga tushishda tekshiriladi (`validate()`): noto'g'ri tur, ruxsat etilgan oraliqdan tashqari qiymat yoki bir-biriga
zid sozlamalar bo'lsa — server ishga tushmaydi va hamma xatolar ro'yxati chiqadi (jim standart qiymatga o'tilmaydi).
Joriy qiymatlarni ko'rish:  python run.py --check-config   (maxfiy qiymatlar yashiriladi).
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class ConfigError(ValueError):
    """Sozlamalarda xato — server ishga tushirilmaydi."""


@dataclass(frozen=True)
class Setting:
    env: str
    value: Any
    default: Any
    doc: str
    secret: bool = False


SETTINGS: list[Setting] = []     # hujjat va --check-config uchun (e'lon qilingan tartibda)
_PROBLEMS: list[str] = []


def _parse_bool(raw: str) -> bool:
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError("1/0 (yoki true/false) bo'lishi kerak")


def _parse_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("son bo'lishi kerak") from None
    if not math.isfinite(value):
        raise ValueError("chekli son bo'lishi kerak")
    return value


def _parse_int(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError:
        raise ValueError("butun son bo'lishi kerak") from None


def _bound(x: float | None) -> str:
    return "∞" if x is None else f"{x:g}"


def _setting(env: str, default: Any, doc: str, *, parse: Callable[[str], Any] | None = None, lo: float | None = None,
             hi: float | None = None, choices: tuple | None = None, legacy: tuple[str, ...] = (), secret: bool = False) -> Any:
    """Muhit o'zgaruvchisidan qiymat: tur va oraliq tekshiriladi; xato bo'lsa — _PROBLEMS ga yoziladi."""
    parser: Callable[[str], Any] = parse if parse is not None else {
        bool: _parse_bool, int: _parse_int, float: _parse_float}.get(type(default), str)
    raw, source = os.environ.get(env), env
    for name in legacy:  # eski nomlar (orqaga moslik)
        if raw is None and os.environ.get(name) is not None:
            raw, source = os.environ.get(name), name
    value = default
    if raw is not None and raw.strip() != "":
        try:
            value = parser(raw.strip())
        except ValueError as e:
            _PROBLEMS.append(f"{source}={'***' if secret else repr(raw)}: {e}")
            value = default
        else:
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                _PROBLEMS.append(f"{source}={raw!r}: {_bound(lo)} … {_bound(hi)} oralig'ida bo'lishi kerak")
                value = default
            elif choices is not None and value not in choices:
                _PROBLEMS.append(f"{source}={raw!r}: {' | '.join(map(str, choices))} dan biri bo'lishi kerak")
                value = default
    SETTINGS.append(Setting(env, value, default, doc, secret))
    return value


# ---------------------------------------------------------------- server
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(_setting("TD_DATA_DIR", str(BASE_DIR / "data"), "Ma'lumotlar papkasi (baza, o'yinlar holati)"))
DB_PATH = Path(_setting("TD_DB_PATH", str(DATA_DIR / "testduel.db"), "SQLite baza fayli"))

HOST = _setting("TD_HOST", "0.0.0.0", "Tinglanadigan manzil")
PORT = _setting("TD_PORT", 8080, "Port (Railway: PORT)", lo=1, hi=65535, legacy=("PORT",))

# Vergul bilan ajratilgan loginlar ro'yxati — ular ro'yxatdan o'tganda admin bo'ladi.
# (Birinchi ro'yxatdan o'tgan foydalanuvchi har doim admin bo'ladi.)
ADMIN_LOGINS = {s.strip().casefold() for s in _setting("TD_ADMINS", "", "Ro'yxatdan o'tganda admin bo'ladigan loginlar (vergul bilan)").split(",") if s.strip()}

# Bosh administrator (tizim egasi): faqat u foydalanuvchilarni boshqaradi (bloklash, parol, admin qilish, o'chirish).
# Bu login band qilingan: uni faqat birinchi foydalanuvchi sifatida ro'yxatdan o'tkazish mumkin.
SUPERADMIN_LOGIN = _setting("TD_SUPERADMIN", "admin", "Bosh administrator logini").strip() or "admin"
# Berilsa, ishga tushishda: bosh administrator akkaunti bo'lmasa — shu parol bilan yaratiladi,
# bor bo'lsa — paroli shu qiymatga tiklanadi (parol unutilganda tiklash uchun).
SUPERADMIN_PASSWORD = _setting("TD_SUPERADMIN_PASSWORD", "", "Bosh administrator paroli (yaratish/tiklash)", secret=True) or None

# Ilova teskari proksi (Nginx, Railway va h.k.) ortida ishlasa: mijozning haqiqiy IP manzili X-Forwarded-For dan,
# HTTPS esa X-Forwarded-Proto dan olinadi. Railway'da avtomatik yoqiladi.
TRUST_PROXY = _setting("TD_TRUST_PROXY", False, "X-Forwarded-* sarlavhalariga ishonish (proksi ortida)") or any(
    os.environ.get(k) for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID")
)

# Ishlab chiquvchi rejimi: statik fayllar har so'rovda diskdan o'qiladi va keshlanmaydi. Ishlab chiqarishda — o'chiq:
# fayllar xotiradan, gzip bilan, mazmun xeshli manzillarda bir yillik kesh bilan beriladi (app/assets.py).
DEV = _setting("TD_DEV", False, "Ishlab chiquvchi rejimi: statik fayllar diskdan, keshsiz")

SESSION_COOKIE = "td_sid"
SESSION_DAYS = _setting("TD_SESSION_DAYS", 30, "Kirish sessiyasi muddati (kun)", lo=1, hi=365)

# ---- Kuzatuv (docs/runbook.md) ----
LOG_FORMAT = _setting("TD_LOG_FORMAT", "text", "Jurnal formati: text | json (har qator — bitta JSON obyekt)", choices=("text", "json"))
LOG_LEVEL = _setting("TD_LOG_LEVEL", "INFO", "Jurnal darajasi", parse=str.upper, choices=("DEBUG", "INFO", "WARNING", "ERROR"))
METRICS_TOKEN = _setting("TD_METRICS_TOKEN", "", "/metrics uchun Bearer token (bo'lmasa — faqat administratorlar)", secret=True)
ERROR_WEBHOOK = _setting("TD_ERROR_WEBHOOK", "", "Xatolar yuboriladigan webhook (JSON POST); bo'sh — faqat jurnal", secret=True)
SHUTDOWN_GRACE = _setting("TD_SHUTDOWN_GRACE", 5.0, "To'xtashda ochiq so'rovlarni kutish (soniya)", lo=0, hi=120)

# ---- HTTP chegaralari ----
LOGIN_FAIL_LIMIT = _setting("TD_LOGIN_FAIL_LIMIT", 10, "Noto'g'ri parol: IP+login bo'yicha urinishlar", lo=1, hi=10_000)
LOGIN_FAIL_WINDOW = _setting("TD_LOGIN_FAIL_WINDOW", 600.0, "… shuncha soniyada", lo=1, hi=86_400)
REGISTER_LIMIT = _setting("TD_REGISTER_LIMIT", 100, "Ro'yxatdan o'tish: IP bo'yicha", lo=1, hi=100_000)
REGISTER_WINDOW = _setting("TD_REGISTER_WINDOW", 600.0, "… shuncha soniyada", lo=1, hi=86_400)
CLIENT_ERROR_LIMIT = _setting("TD_CLIENT_ERROR_LIMIT", 30, "Brauzer xatosi hisobotlari: IP bo'yicha 10 daqiqada", lo=0, hi=10_000)

# ---- Duel qoidalari ----
DUEL_QUESTIONS = _setting("TD_DUEL_QUESTIONS", 15, "Duelda har bir ishtirokchiga savollar soni", lo=1, hi=100)
QUESTION_TIME = _setting("TD_QUESTION_TIME", 15.0, "Duel: bitta savol uchun vaqt (soniya)", lo=3, hi=600)
AFK_LIMIT = _setting("TD_AFK_LIMIT", 30.0, "Duel: shuncha soniya javob bermasa — mag'lub", lo=5, hi=3600)
DISCONNECT_GRACE = _setting("TD_DISCONNECT_GRACE", 10.0, "Duel: aloqa uzilsa, qaytish uchun vaqt (soniya)", lo=0, hi=600)
ANSWER_GRACE = 0.8      # tarmoq kechikishi uchun qo'shimcha vaqt (soniya)
FEEDBACK_DELAY = 1.2    # javobdan keyin keyingi savolgacha pauza (vaqtga qo'shilmaydi)
COUNTDOWN = 3.0         # duel boshlanishidan oldingi sanoq
RESULT_TTL = 600.0      # aloqasiz qolgan ishtirokchi uchun natijani saqlab turish vaqti

# ---- Mavzular faolligi, reyting va lobbi (docs/scaling.md) ----
TZ_OFFSET_HOURS = _setting("TD_TZ_OFFSET_HOURS", 5.0, "Kunlik hisoblar vaqt mintaqasi (Toshkent: UTC+5)", lo=-12, hi=14)
# "Qizg'in" (hot) reyting: hot = Σ duellar(bugundan d kun oldin) · 0.5^(d / HOT_HALF_LIFE_DAYS)  (oxirgi HOT_WINDOW_DAYS kun)
#                                + HOT_LIVE_WEIGHT · (hozir kutayotganlar + hozir o'ynayotgan duellar)
HOT_WINDOW_DAYS = _setting("TD_HOT_WINDOW_DAYS", 14, "«Qizg'in» reyting oynasi (kun)", lo=1, hi=365)
HOT_HALF_LIFE_DAYS = _setting("TD_HOT_HALF_LIFE_DAYS", 2.0, "«Qizg'in» reyting yarim yemirilishi (kun)", lo=0.1, hi=365)
HOT_LIVE_WEIGHT = _setting("TD_HOT_LIVE_WEIGHT", 3.0, "Hozir o'ynayotganlar og'irligi", lo=0, hi=1000)
RANKING_TTL = _setting("TD_RANKING_TTL", 30.0, "Reyting ro'yxatlari keshi (soniya)", lo=0, hi=3600)
RANKING_REFRESH = _setting("TD_RANKING_REFRESH", 5.0, "Yangi duel boshlangach reyting eng tez yangilanishi (soniya)", lo=0, hi=3600)
TOPICS_PAGE = 24                                      # bosh sahifada bir martada yuklanadigan mavzular
SEEK_TTL = _setting("TD_SEEK_TTL", 120.0, "Raqib kutish muddati (soniya)", lo=10, hi=3600)
LOBBY_LIMIT = 50                                      # lobbida ko'rsatiladigan eng yangi kutayotganlar soni
LOBBY_FLUSH = 1.0                                     # lobbi yangilanishlari: har bir mijozga ko'pi bilan sekundiga bir marta
LIVE_TOPICS_LIMIT = 12                                # "hozir faol mavzular" bo'limi
SUGGEST_IDLE_DAYS = _setting("TD_SUGGEST_IDLE_DAYS", 90, "Shuncha kun o'ynalmagan mavzular o'chirishga tavsiya qilinadi", lo=1, hi=3650)

# ---- Octagon (jonli viktorina) ----
OCTAGON_INTRO = _setting("TD_OCTAGON_INTRO", 5.0, "«Boshlash»dan keyin mavzu nomi hamma ekranda (soniya)", lo=0, hi=60)
OCTAGON_READ = _setting("TD_OCTAGON_READ", 5.0, "Savolni o'qish vaqti: matn faqat o'qituvchida, tugmalar yopiq (soniya)",
                        lo=0, hi=60, legacy=("TD_OCTAGON_READY",))
OCTAGON_PODIUM_INTRO = _setting("TD_OCTAGON_PODIUM_INTRO", 3.0, "Oxirgi savoldan keyin «Va g'oliblar…» ekrani (soniya)", lo=0, hi=60)
OCTAGON_REVEAL_STEP = _setting("TD_OCTAGON_REVEAL_STEP", 3.5, "Podium: 3- va 2-o'rin ochilgandan keyingi pauza (soniya)", lo=0, hi=60)
OCTAGON_REVEAL_WINNER = _setting("TD_OCTAGON_REVEAL_WINNER", 6.0, "Podium: 1-o'rin ekrani, keyin to'liq natijalar (soniya)", lo=0, hi=60)
OCTAGON_TIME_MIN = _setting("TD_OCTAGON_TIME_MIN", 5, "Savol vaqti: eng kami (soniya)", lo=1, hi=600)
OCTAGON_TIME_MAX = _setting("TD_OCTAGON_TIME_MAX", 120, "Savol vaqti: eng ko'pi (soniya)", lo=1, hi=600)
OCTAGON_TIME_DEFAULT = _setting("TD_OCTAGON_TIME_DEFAULT", 20, "Savol vaqti: standart (soniya)", lo=1, hi=600)
OCTAGON_MAX_QUESTIONS = _setting("TD_OCTAGON_MAX_QUESTIONS", 100, "Bitta o'yindagi eng ko'p savollar", lo=1, hi=1000)
OCTAGON_DEFAULT_QUESTIONS = _setting("TD_OCTAGON_DEFAULT_QUESTIONS", 10, "Savollar soni: standart", lo=1, hi=1000)
OCTAGON_MAX_PLAYERS = _setting("TD_OCTAGON_MAX_PLAYERS", 300, "Bitta o'yindagi eng ko'p o'quvchilar", lo=1, hi=5000)
OCTAGON_MAX_GAMES_PER_TEACHER = _setting("TD_OCTAGON_MAX_GAMES_PER_TEACHER", 5, "O'qituvchining bir vaqtdagi o'yinlari", lo=1, hi=100)
OCTAGON_MAX_FINISHED_PER_TEACHER = _setting("TD_OCTAGON_MAX_FINISHED_PER_TEACHER", 5, "Xotirada saqlanadigan tugagan o'yinlar (o'qituvchiga)", lo=0, hi=100)
OCTAGON_MAX_GAMES = _setting("TD_OCTAGON_MAX_GAMES", 500, "Serverdagi jami o'yinlar", lo=1, hi=100_000)
OCTAGON_MAX_SOCKETS = _setting("TD_OCTAGON_MAX_SOCKETS", 5000, "Jami ochiq o'quvchi/o'qituvchi ulanishlari", lo=1, hi=1_000_000)
OCTAGON_MAX_SOCKETS_PER_IP = _setting("TD_OCTAGON_MAX_SOCKETS_PER_IP", 500, "Bitta IP dan ulanishlar (maktab NAT)", lo=1, hi=1_000_000)
OCTAGON_FAIL_LIMIT = _setting("TD_OCTAGON_FAIL_LIMIT", 60, "Noto'g'ri PIN/token urinishlari: IP bo'yicha", lo=1, hi=100_000)
OCTAGON_FAIL_WINDOW = _setting("TD_OCTAGON_FAIL_WINDOW", 300.0, "… shuncha soniyada", lo=1, hi=86_400)
OCTAGON_GLOBAL_FAIL_LIMIT = _setting("TD_OCTAGON_GLOBAL_FAIL_LIMIT", 300, "Barcha IP lardan noto'g'ri urinishlar — PIN taxmin hujumi belgisi", lo=1, hi=1_000_000)
OCTAGON_GLOBAL_FAIL_WINDOW = _setting("TD_OCTAGON_GLOBAL_FAIL_WINDOW", 60.0, "… shuncha soniyada", lo=1, hi=86_400)
OCTAGON_SURGE_FAIL_LIMIT = _setting("TD_OCTAGON_SURGE_FAIL_LIMIT", 5, "Hujum paytida bitta IP ga ruxsat etilgan noto'g'ri urinishlar", lo=1, hi=100_000)
OCTAGON_JOIN_LIMIT = _setting("TD_OCTAGON_JOIN_LIMIT", 1000, "Yangi o'yinchilar: IP bo'yicha (≥ o'yindagi eng ko'p o'quvchilar)", lo=1, hi=1_000_000)
OCTAGON_JOIN_WINDOW = _setting("TD_OCTAGON_JOIN_WINDOW", 600.0, "… shuncha soniyada", lo=1, hi=86_400)
OCTAGON_HOST_FLUSH = _setting("TD_OCTAGON_HOST_FLUSH", 0.25, "O'qituvchi ekrani yangilanishi: kichik o'yinlar (soniya)", lo=0.05, hi=10)
OCTAGON_HOST_FLUSH_BIG = _setting("TD_OCTAGON_HOST_FLUSH_BIG", 1.0, "… katta o'yinlar (soniya)", lo=0.05, hi=10)
OCTAGON_HOST_FLUSH_BIG_FROM = _setting("TD_OCTAGON_HOST_FLUSH_BIG_FROM", 40, "Katta o'yin: o'quvchilar soni shundan ko'p", lo=0, hi=100_000)
OCTAGON_TTL = _setting("TD_OCTAGON_TTL", 7200.0, "Faolsiz o'yin xotiradan o'chiriladi (soniya)", lo=60, hi=7 * 86_400)
OCTAGON_SWEEP_EVERY = _setting("TD_OCTAGON_SWEEP_EVERY", 60.0, "Eskirgan o'yinlarni tozalash oralig'i (soniya)", lo=1, hi=3600)
OCTAGON_RESTORE_MAX_AGE = _setting("TD_OCTAGON_RESTORE_MAX_AGE", 600.0,
                                   "Qayta ishga tushishda saqlangan o'yinlar tiklanadi, agar shundan yangi bo'lsa (soniya; 0 — tiklanmaydi)", lo=0, hi=86_400)

# ---- WebSocket ----
WS_OCTAGON_MAX_MESSAGE = _setting("TD_WS_OCTAGON_MAX_MESSAGE", 4096, "/ws/octagon: bitta xabarning eng katta hajmi (bayt)", lo=256, hi=1_048_576)
WS_OCTAGON_FLOOD_LIMIT = _setting("TD_WS_OCTAGON_FLOOD_LIMIT", 60, "/ws/octagon: 10 soniyada eng ko'p xabar", lo=5, hi=10_000)
WS_DUEL_FLOOD_LIMIT = _setting("TD_WS_DUEL_FLOOD_LIMIT", 120, "/ws: 10 soniyada eng ko'p xabar", lo=5, hi=10_000)
WS_FLOOD_WINDOW = 10.0


def _parse_public_url(raw: str) -> str:
    value = raw.rstrip("/")
    if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:[0-9]{1,5})?", value):
        raise ValueError("https://domen[:port] ko'rinishida bo'lishi kerak (yo'lsiz)")
    return value


# Saytning ommaviy manzili (masalan, https://quiz.maktab.uz). Berilsa, QR kod va qo'shilish havolasi doim shu manzilga
# ishora qiladi (aks holda so'rovdagi Host sarlavhasidan olinadi).
PUBLIC_URL = _setting("TD_PUBLIC_URL", "", "Saytning ommaviy manzili (QR va qo'shilish havolasi uchun)", parse=_parse_public_url) or None

# ---- Yuklash cheklovlari ----
MAX_UPLOAD_CHARS = 10_000_000
MAX_TOPIC_NAME = 120


def validate() -> list[str]:
    """Barcha muammolar: noto'g'ri qiymatlar (o'qishda) va bir-biriga zid sozlamalar (joriy qiymatlar bo'yicha)."""
    problems = list(_PROBLEMS)
    g = globals()

    def need(cond: bool, text: str) -> None:
        if not cond:
            problems.append(text)

    need(g["OCTAGON_TIME_MIN"] <= g["OCTAGON_TIME_DEFAULT"] <= g["OCTAGON_TIME_MAX"],
         "TD_OCTAGON_TIME_MIN ≤ TD_OCTAGON_TIME_DEFAULT ≤ TD_OCTAGON_TIME_MAX bo'lishi kerak")
    need(g["OCTAGON_DEFAULT_QUESTIONS"] <= g["OCTAGON_MAX_QUESTIONS"],
         "TD_OCTAGON_DEFAULT_QUESTIONS ≤ TD_OCTAGON_MAX_QUESTIONS bo'lishi kerak")
    need(g["OCTAGON_JOIN_LIMIT"] >= g["OCTAGON_MAX_PLAYERS"],
         "TD_OCTAGON_JOIN_LIMIT ≥ TD_OCTAGON_MAX_PLAYERS bo'lishi kerak (bitta maktab tarmog'idan to'liq sinf qo'shila olsin)")
    need(g["OCTAGON_MAX_SOCKETS_PER_IP"] >= g["OCTAGON_MAX_PLAYERS"],
         "TD_OCTAGON_MAX_SOCKETS_PER_IP ≥ TD_OCTAGON_MAX_PLAYERS bo'lishi kerak")
    need(g["OCTAGON_SURGE_FAIL_LIMIT"] <= g["OCTAGON_FAIL_LIMIT"],
         "TD_OCTAGON_SURGE_FAIL_LIMIT ≤ TD_OCTAGON_FAIL_LIMIT bo'lishi kerak")
    need(g["OCTAGON_HOST_FLUSH"] <= g["OCTAGON_HOST_FLUSH_BIG"],
         "TD_OCTAGON_HOST_FLUSH ≤ TD_OCTAGON_HOST_FLUSH_BIG bo'lishi kerak")
    need(g["OCTAGON_MAX_GAMES_PER_TEACHER"] <= g["OCTAGON_MAX_GAMES"],
         "TD_OCTAGON_MAX_GAMES_PER_TEACHER ≤ TD_OCTAGON_MAX_GAMES bo'lishi kerak")
    return problems


def check() -> None:
    problems = validate()
    if problems:
        raise ConfigError("Sozlamalarda xato:\n  - " + "\n  - ".join(problems))


def describe() -> list[tuple[str, str, str]]:
    """(muhit o'zgaruvchisi, joriy qiymat — maxfiylari yashirilgan, izoh)."""
    rows = []
    for s in SETTINGS:
        shown = ("***" if s.value else "(bo'sh)") if s.secret else repr(globals().get(_name_of(s.env), s.value))
        rows.append((s.env, shown, s.doc))
    return rows


def _name_of(env: str) -> str:
    return env.removeprefix("TD_")
