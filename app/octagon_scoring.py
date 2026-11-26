"""Octagon ball hisobi va reyting tartibi — sof funksiyalar (formula v1 dagidek o'zgarmagan).

Ball: to'g'ri javob — 500 + tezlik uchun 500 gacha, noto'g'ri yoki javobsiz — 0.
    score = round((1 - (t / timer) / 2) * max_points)
  * t — javob vaqti (ms), server soati bo'yicha savol faol bo'lgan paytdan (question_active boshlanishidan);
  * t ≤ FULL_POINTS_MS bo'lsa — to'liq ball (t = 0 deb olinadi);
  * t > timer bo'lsa — t = timer (eng kamida max_points / 2); vaqti o'tgan javobni o'yin qabul qilmaydi;
  * aniq kasrlar bilan hisoblanadi va faqat oxirida bir marta yaxlitlanadi (0.5 — yuqoriga).

Reyting: ball (ko'p) -> umumiy javob vaqti (kam; javobsiz savol = to'liq vaqt) -> ism kaliti (alifbo) -> id.
Shu tartib bilan har bir savoldan keyin o'rin o'zgarishi (rank_changes) va yakuniy podium (podium) hisoblanadi.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction

# Reyting uchun o'yinchi: (id, ball, umumiy javob vaqti ms, ism kaliti)
Standing = tuple[str, int, int, str]
# O'rin o'zgarishi: (oldingi o'rin | None, yangi o'rin, delta | None); delta = oldingi − yangi (musbat — yuqoriga)
RankChange = tuple[int | None, int, int | None]
JUMP_MIN = 2   # «eng katta sakrash» kamida shuncha o'rin
PODIUM_SIZE = 3

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


def rank_order(rows: Iterable[Standing]) -> list[str]:
    """O'yinchilar id lari reyting tartibida (standing_key: ball, vaqt, ism, id — ikki o'yinchi hech qachon bir o'rinda emas)."""
    return [r[0] for r in sorted(rows, key=lambda r: standing_key(r[1], r[2], r[3], r[0]))]


def rank_changes(before: Iterable[Standing] | None, after: Iterable[Standing]) -> dict[str, RankChange]:
    """Savoldan oldingi va keyingi reyting -> har bir o'yinchining o'rni va o'zgarishi.

    before — savol ballari qo'shilishidan oldingi holat (oldingi reytingda qatnashgan o'yinchilar); None — oldingi
    reyting yo'q (1-savol): hech kimda delta yo'q. Oldingi reytingda bo'lmagan o'yinchi (kech qo'shilgan) — delta None
    (ekranda «YANGI»). Oldingi reytingda bo'lib, endi yo'q o'yinchi (chiqarilgan) — natijaga kirmaydi.
    """
    prev = {pid: i for i, pid in enumerate(rank_order(before), 1)} if before is not None else {}
    out: dict[str, RankChange] = {}
    for i, pid in enumerate(rank_order(after), 1):
        k = prev.get(pid)
        out[pid] = (k, i, None if k is None else k - i)
    return out


def biggest_jump(changes: Mapping[str, RankChange], min_delta: int = JUMP_MIN) -> tuple[str, int] | None:
    """Savolning eng katta ko'tarilishi (id, delta) — kamida min_delta o'rin; teng bo'lsa — yangi o'rni yuqoriroq."""
    best = None
    for pid, (_, new, delta) in changes.items():
        if delta is not None and delta >= min_delta and (best is None or (delta, -new) > (best[1], -best[2])):
            best = (pid, delta, new)
    return (best[0], best[1]) if best else None


def podium(ranked_ids: Sequence[str], has_points: bool, ended_early: bool) -> list[str]:
    """Yakuniy ochilishda ko'rsatiladigan o'yinchilar: [1-o'rin, 2-o'rin, 3-o'rin] (o'yinchilar kam bo'lsa — kamroq).

    Bo'sh ro'yxat — ochilish bo'lmaydi: o'yinda hech kim yo'q yoki o'yin muddatidan oldin tugatilgan va hali hech kim
    ball olmagan. Oddiy tugashda hamma 0 ball bo'lsa ham o'rinlarni reyting tartibi (vaqt, ism) hal qiladi.
    """
    if not ranked_ids or (ended_early and not has_points):
        return []
    return list(ranked_ids[:PODIUM_SIZE])


def answer_shares(answered: int, correct: int, players: int) -> tuple[int | None, int]:
    """Savol natijasi ulushlari (foiz, butun, pastga yaxlitlangan) — o'qituvchi ekranidagi natija ovozi uchun:
    (to'g'ri javoblar — javob berganlar orasida | hech kim javob bermagan bo'lsa None, javob berganlar — o'yinchilardan).

    Pastga yaxlitlash butun chegaralarni aniq saqlaydi: ⌊x⌋ ≥ 60 ⇔ x ≥ 60 (59,9 % — «60 % dan kam» bo'lib qoladi).
    """
    answered, correct, players = max(0, answered), max(0, correct), max(0, players)
    pct = min(correct, answered) * 100 // answered if answered else None
    rate = min(100, answered * 100 // players) if players else 0
    return pct, rate
