"""TestDuel sozlamalari.

Har bir qiymatni muhit o'zgaruvchisi (environment variable) orqali o'zgartirish mumkin,
masalan:  set TD_PORT=9000  (Windows)  yoki  TD_PORT=9000 python run.py  (Linux).
"""
from __future__ import annotations

import os
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
WAITING_TTL = 120.0     # kutayotgan foydalanuvchi aloqasi uzilsa, navbatda saqlanish vaqti
RESULT_TTL = 600.0      # aloqasiz qolgan ishtirokchi uchun natijani saqlab turish vaqti

# ---- Yuklash cheklovlari ----
MAX_UPLOAD_CHARS = 10_000_000
MAX_TOPIC_NAME = 120
