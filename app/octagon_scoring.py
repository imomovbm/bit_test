"""Octagon ball hisobi va reyting tartibi — sof funksiyalar (formula v1 dagidek o'zgarmagan).

Ball: to'g'ri javob — 500 + tezlik uchun 500 gacha, noto'g'ri yoki javobsiz — 0.
    score = round((1 - (t / timer) / 2) * max_points)
  * t — javob vaqti (ms), server soati bo'yicha savol faol bo'lgan paytdan (question_active boshlanishidan);
  * t ≤ FULL_POINTS_MS bo'lsa — to'liq ball (t = 0 deb olinadi);
  * t > timer bo'lsa — t = timer (eng kamida max_points / 2); vaqti o'tgan javobni o'yin qabul qilmaydi;
  * aniq kasrlar bilan hisoblanadi va faqat oxirida bir marta yaxlitlanadi (0.5 — yuqoriga).

Reyting: ball (ko'p) -> umumiy javob vaqti (kam; javobsiz savol = to'liq vaqt) -> ism kaliti (alifbo) -> id.
"""
from __future__ import annotations

import math
from fractions import Fraction

MAX_POINTS = 1000
FULL_POINTS_MS = 500   # shundan tez (yoki aynan shu vaqtda) berilgan to'g'ri javob — to'liq ball


def calculate_score(is_correct: bool, response_time_ms, timer_ms, max_points: int = MAX_POINTS) -> int:
    """Bitta savol uchun ball (butun son)."""
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


def standing_key(score: int, total_time_ms: int, name_key: str, player_id: str) -> tuple:
    """Reytingdagi tartib kaliti (kichigi yuqorida)."""
    return (-score, total_time_ms, name_key, player_id)
