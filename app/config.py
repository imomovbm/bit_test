"""TestDuel sozlamalari.

Har bir qiymatni muhit o'zgaruvchisi (environment variable) orqali o'zgartirish mumkin,
masalan:  set TD_PORT=9000  (Windows)  yoki  TD_PORT=9000 python run.py  (Linux).
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("TD_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("TD_DB_PATH", DATA_DIR / "testduel.db"))

HOST = os.environ.get("TD_HOST", "0.0.0.0")
PORT = _int("TD_PORT", _int("PORT", 8080))

# Vergul bilan ajratilgan loginlar ro'yxati — ular ro'yxatdan o'tganda admin bo'ladi.
# (Birinchi ro'yxatdan o'tgan foydalanuvchi har doim admin bo'ladi.)
ADMIN_LOGINS = {s.strip().casefold() for s in os.environ.get("TD_ADMINS", "").split(",") if s.strip()}

# Bosh administrator (tizim egasi): faqat u foydalanuvchilarni boshqaradi (bloklash, parol, admin qilish, o'chirish).
# Bu login band qilingan: uni faqat birinchi foydalanuvchi sifatida ro'yxatdan o'tkazish mumkin.
SUPERADMIN_LOGIN = os.environ.get("TD_SUPERADMIN", "admin").strip() or "admin"
# Berilsa, ishga tushishda: bosh administrator akkaunti bo'lmasa — shu parol bilan yaratiladi,
# bor bo'lsa — paroli shu qiymatga tiklanadi (parol unutilganda tiklash uchun).
SUPERADMIN_PASSWORD = os.environ.get("TD_SUPERADMIN_PASSWORD") or None

# Ilova teskari proksi (Nginx, Railway va h.k.) ortida ishlasa: mijozning haqiqiy IP manzili X-Forwarded-For dan,
# HTTPS esa X-Forwarded-Proto dan olinadi. Railway'da avtomatik yoqiladi.
TRUST_PROXY = os.environ.get("TD_TRUST_PROXY", "") == "1" or any(
    os.environ.get(k) for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID")
)

# Ishlab chiquvchi rejimi: statik fayllar har so'rovda diskdan o'qiladi va keshlanmaydi (TD_DEV=1). Ishlab chiqarishda —
# o'chiq: fayllar xotiradan, gzip bilan, mazmun xeshli manzillarda bir yillik kesh bilan beriladi (app/assets.py).
DEV = os.environ.get("TD_DEV", "") == "1"

SESSION_COOKIE = "td_sid"
SESSION_DAYS = 30

# ---- Duel qoidalari ----
DUEL_QUESTIONS = _int("TD_DUEL_QUESTIONS", 15)          # har bir ishtirokchiga savollar soni
QUESTION_TIME = _float("TD_QUESTION_TIME", 15.0)        # bitta savol uchun vaqt (soniya)
AFK_LIMIT = _float("TD_AFK_LIMIT", 30.0)                # shuncha soniya javob bermasa — mag'lub
DISCONNECT_GRACE = _float("TD_DISCONNECT_GRACE", 10.0)  # aloqa uzilsa, qaytish uchun vaqt
ANSWER_GRACE = 0.8      # tarmoq kechikishi uchun qo'shimcha vaqt (soniya)
FEEDBACK_DELAY = 1.2    # javobdan keyin keyingi savolgacha pauza (vaqtga qo'shilmaydi)
COUNTDOWN = 3.0         # duel boshlanishidan oldingi sanoq
RESULT_TTL = 600.0      # aloqasiz qolgan ishtirokchi uchun natijani saqlab turish vaqti

# ---- Mavzular faolligi, reyting va lobbi (docs/scaling.md) ----
TZ_OFFSET_HOURS = _float("TD_TZ_OFFSET_HOURS", 5.0)   # "bugun" va kunlik hisoblar qaysi vaqt mintaqasida (Toshkent: UTC+5)
# "Qizg'in" (hot) reyting: hot = Σ duellar(bugundan d kun oldin) · 0.5^(d / HOT_HALF_LIFE_DAYS)  (oxirgi HOT_WINDOW_DAYS kun)
#                                + HOT_LIVE_WEIGHT · (hozir kutayotganlar + hozir o'ynayotgan duellar)
HOT_WINDOW_DAYS = _int("TD_HOT_WINDOW_DAYS", 14)
HOT_HALF_LIFE_DAYS = _float("TD_HOT_HALF_LIFE_DAYS", 2.0)
HOT_LIVE_WEIGHT = _float("TD_HOT_LIVE_WEIGHT", 3.0)
RANKING_TTL = _float("TD_RANKING_TTL", 30.0)          # reyting ro'yxatlari keshi: eng ko'pi bilan shuncha soniya eskiradi
RANKING_REFRESH = _float("TD_RANKING_REFRESH", 5.0)   # yangi duel boshlangach, ro'yxat eng tez shuncha soniyada yangilanadi
TOPICS_PAGE = 24                                      # bosh sahifada bir martada yuklanadigan mavzular
SEEK_TTL = _float("TD_SEEK_TTL", 120.0)               # raqib kutish (seek) muddati, soniya
LOBBY_LIMIT = 50                                      # lobbida ko'rsatiladigan eng yangi kutayotganlar soni
LOBBY_FLUSH = 1.0                                     # lobbi yangilanishlari: har bir mijozga ko'pi bilan sekundiga bir marta
LIVE_TOPICS_LIMIT = 12                                # "hozir faol mavzular" bo'limi
SUGGEST_IDLE_DAYS = _int("TD_SUGGEST_IDLE_DAYS", 90)  # shuncha kun o'ynalmagan mavzular o'chirishga tavsiya qilinadi

# ---- Octagon (jonli viktorina) ----
OCTAGON_INTRO = _float("TD_OCTAGON_INTRO", 5.0)    # «Boshlash»dan keyin mavzu nomi hamma ekranda (bir marta), soniya
# Savolni o'qish vaqti (matn faqat o'qituvchi ekranida, javob tugmalari yopiq). TD_OCTAGON_READY — eski nomi (v1).
OCTAGON_READ = _float("TD_OCTAGON_READ", _float("TD_OCTAGON_READY", 5.0))
OCTAGON_TTL = _float("TD_OCTAGON_TTL", 7200.0)     # shuncha soniya faolsiz qolgan o'yin xotiradan o'chiriladi
OCTAGON_MAX_SOCKETS = _int("TD_OCTAGON_MAX_SOCKETS", 5000)  # jami ochiq o'quvchi/o'qituvchi ulanishlari


def _public_url() -> str | None:
    """TD_PUBLIC_URL — saytning ommaviy manzili (masalan, https://quiz.maktab.uz). Berilsa, QR kod va qo'shilish
    havolasi doim shu manzilga ishora qiladi (aks holda so'rovdagi Host sarlavhasidan olinadi)."""
    value = os.environ.get("TD_PUBLIC_URL", "").strip().rstrip("/")
    if value and not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:[0-9]{1,5})?", value):
        print(f"Ogohlantirish: TD_PUBLIC_URL noto'g'ri ({value!r}) — e'tiborga olinmadi", flush=True)
        return None
    return value or None


PUBLIC_URL = _public_url()

# ---- Yuklash cheklovlari ----
MAX_UPLOAD_CHARS = 10_000_000
MAX_TOPIC_NAME = 120
