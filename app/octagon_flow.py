"""Octagon o'yinining bosqichlar mashinasi — sof (holatsiz) qoidalar: bosqichlar, ruxsat etilgan o'tishlar, vaqtlar va
yakuniy ochilishda qaysi o'rinlar ochiq. Taymerlar, ulanishlar va xabarlar app/octagon.py da; bu modul faqat "qaysi
bosqichdan qaysiga o'tish mumkin", "bosqich qancha davom etadi" va "nima yuborish mumkin" degan savollarga javob beradi
(tests/test_octagon_flow.py, tests/test_octagon_ranks.py).

    lobby -> topic_intro -> question_read -> question_active -> question_result -> leaderboard
                               ^                                      |                 |
                               +--------------- (keyingi savol) ------)-----------------+
                                                                      | (oxirgi savol)
    podium_intro -> reveal_3rd -> reveal_2nd -> reveal_1st -> final_results  <-------+

* topic_intro — o'qituvchi «Boshlash»ni bosgach bir marta: mavzu nomi hamma ekranlarda (config.OCTAGON_INTRO soniya);
* question_read — savol matni faqat o'qituvchi ekranida, o'quvchilarda rangli shakllar (bosib bo'lmaydi) va sanoq
  (config.OCTAGON_READ soniya);
* question_active — javoblar qabul qilinadi; javob vaqti shu bosqich boshlangan paytdan o'lchanadi (savol vaqti);
* question_result, leaderboard — o'qituvchi «Keyingi» bilan o'tadi. Oxirgi savoldan keyin reyting ko'rsatilmaydi:
  natijadan to'g'ridan-to'g'ri yakuniy ochilishga o'tiladi (aks holda podium oldindan ma'lum bo'lib qoladi);
* podium_intro (config.OCTAGON_PODIUM_INTRO) -> reveal_3rd -> reveal_2nd (config.OCTAGON_REVEAL_STEP) -> reveal_1st
  (config.OCTAGON_REVEAL_WINNER) -> final_results: o'rinlar birma-bir ochiladi; o'yinchilar 3 tadan kam bo'lsa —
  ortiqcha qadamlar tashlab ketiladi (2 ta: 2-o'rin, 1-o'rin; 1 ta: faqat 1-o'rin; 0 ta — darhol final_results).
  O'qituvchi «Keyingi» bilan keyingi qadamga, «O'tkazib yuborish» bilan darhol natijalarga o'tadi.

O'yinni muddatidan oldin tugatish (end): istalgan bosqichdan yakuniy ochilishga (savol paytida — avval natija hisoblanadi).
"""
from __future__ import annotations

from collections.abc import Mapping

LOBBY = "lobby"
INTRO = "topic_intro"
READ = "question_read"
ACTIVE = "question_active"
RESULT = "question_result"
BOARD = "leaderboard"
PODIUM_INTRO = "podium_intro"
REVEAL_3 = "reveal_3rd"
REVEAL_2 = "reveal_2nd"
REVEAL_1 = "reveal_1st"
FINAL = "final_results"

# O'quvchilarga bosqich nomi emas, shu ro'yxatdagi indeksi yuboriladi (static/js/octagon/common.js — PHASES bilan bir xil)
PHASES = (LOBBY, INTRO, READ, ACTIVE, RESULT, BOARD, PODIUM_INTRO, REVEAL_3, REVEAL_2, REVEAL_1, FINAL)
CODE = {name: i for i, name in enumerate(PHASES)}

REVEALS = (REVEAL_3, REVEAL_2, REVEAL_1)          # o'rinlar ochiladigan tartib
PLACE = {REVEAL_3: 3, REVEAL_2: 2, REVEAL_1: 1}   # shu qadamda e'lon qilinadigan o'rin
TIMED = frozenset({INTRO, READ, ACTIVE, PODIUM_INTRO, *REVEALS})   # server taymeri bilan tugaydigan bosqichlar
WITH_QUESTION = frozenset({READ, ACTIVE, RESULT, BOARD})            # joriy savol indeksi ma'noga ega
FINISHED = frozenset({PODIUM_INTRO, *REVEALS, FINAL})              # savollar tugagan: ballar va reyting o'zgarmaydi
SHOWING = frozenset({PODIUM_INTRO, *REVEALS})                       # yakuniy ochilish davom etmoqda

# Ruxsat etilgan o'tishlar (boshqasi — dasturdagi xato, IllegalTransition)
TRANSITIONS: dict[str, frozenset[str]] = {
    LOBBY: frozenset({INTRO}),
    INTRO: frozenset({READ, PODIUM_INTRO, FINAL}),
    READ: frozenset({ACTIVE, PODIUM_INTRO, FINAL}),
    ACTIVE: frozenset({RESULT}),          # tugatish ham avval natijani hisoblaydi (RESULT -> PODIUM_INTRO)
    RESULT: frozenset({BOARD, PODIUM_INTRO, FINAL}),
    BOARD: frozenset({READ, PODIUM_INTRO, FINAL}),
    PODIUM_INTRO: frozenset({*REVEALS, FINAL}),
    REVEAL_3: frozenset({REVEAL_2, FINAL}),
    REVEAL_2: frozenset({REVEAL_1, FINAL}),
    REVEAL_1: frozenset({FINAL}),
    FINAL: frozenset(),
}


class IllegalTransition(RuntimeError):
    """Bosqichlar mashinasi buzildi (masalan, taymer o'yin tugagandan keyin ishladi) — dasturdagi xato."""


def check(src: str, dst: str) -> None:
    if dst not in TRANSITIONS.get(src, frozenset()):
        raise IllegalTransition(f"{src} -> {dst}")


def duration(phase: str, time_limit_s: float, timings: Mapping[str, float]) -> float | None:
    """Bosqich davomiyligi (soniya) yoki None — o'qituvchi o'tkazadigan bosqichlar uchun.
    timings: intro, read, podium, reveal, winner (app/config.py dan — app.octagon.timings())."""
    return {
        INTRO: timings["intro"], READ: timings["read"], ACTIVE: time_limit_s,
        PODIUM_INTRO: timings["podium"], REVEAL_3: timings["reveal"], REVEAL_2: timings["reveal"], REVEAL_1: timings["winner"],
    }.get(phase)


def reveal_steps(places: int) -> tuple[str, ...]:
    """Podiumdagi o'yinchilar soni (0–3) uchun ochilish qadamlari: 3 -> 3-, 2-, 1-o'rin; 2 -> 2-, 1-; 1 -> 1-; 0 -> yo'q."""
    places = max(0, min(len(REVEALS), places))
    return REVEALS[len(REVEALS) - places:]


def finish_phase(places: int) -> str:
    """Savollar tugaganda: ochiladigan o'rin bo'lsa — podium_intro, bo'lmasa (bo'sh o'yin) — darhol final_results."""
    return PODIUM_INTRO if places > 0 else FINAL


def revealed_places(phase: str, places: int) -> tuple[int, ...]:
    """Shu bosqichda ma'lumoti yuborilishi mumkin bo'lgan podium o'rinlari (ochilish tartibida: 3, 2, 1).
    Hali e'lon qilinmagan o'rin hech qachon kirmaydi — sizib chiqmaslik qoidasining yagona manbai."""
    if phase == FINAL:
        upto = 1
    elif phase in PLACE:
        upto = PLACE[phase]
    else:
        return ()
    return tuple(k for k in (3, 2, 1) if upto <= k <= places)


def after_timer(phase: str, places: int = 0) -> str:
    """Taymer tugaganda keyingi bosqich (faqat TIMED bosqichlar uchun)."""
    nxt = {INTRO: READ, READ: ACTIVE, ACTIVE: RESULT}.get(phase)
    if nxt is not None:
        return nxt
    if phase in SHOWING:
        steps = reveal_steps(places)
        later = steps[steps.index(phase) + 1:] if phase in steps else steps
        return later[0] if later else FINAL
    raise IllegalTransition(f"{phase}: taymer bilan tugamaydi")


def on_next(phase: str, has_more_questions: bool, places: int = 0) -> str | None:
    """O'qituvchining «Keyingi» tugmasi. None — bu bosqichda hech narsa qilmaydi (masalan, kirish yoki o'qish
    paytida: ular taymer bilan tugaydi yoki «O'tkazib yuborish» bilan; ikki marta bosish bosqichni sakratib yubormaydi).
    PODIUM_INTRO qaytsa — savollar tugadi (dvigatel podiumni hisoblab, finish_phase bo'yicha boshlaydi)."""
    if phase == ACTIVE:
        return RESULT
    if phase == RESULT:
        return BOARD if has_more_questions else PODIUM_INTRO
    if phase == BOARD:
        return READ if has_more_questions else PODIUM_INTRO
    if phase in SHOWING:
        return after_timer(phase, places)
    return None


def on_skip(phase: str) -> str | None:
    """«O'tkazib yuborish»: mavzu kirishi va o'qish vaqtini qisqartirish, savolni muddatidan oldin yopish, yakuniy
    ochilishni tugatib, darhol natijalarni ko'rsatish."""
    if phase in SHOWING:
        return FINAL
    return {INTRO: READ, READ: ACTIVE, ACTIVE: RESULT}.get(phase)


def can_answer(phase: str) -> bool:
    """Javob faqat savol faol bo'lganda qabul qilinadi (o'qish paytida — yo'q)."""
    return phase == ACTIVE


def can_join(phase: str) -> bool:
    """Qo'shilish yakuniy natijalargacha mumkin (kech qo'shilgan o'tgan savollar uchun 0 ball oladi; ochilish paytida
    qo'shilgan — e'lon qilinganlarni ko'radi va reyting oxirida turadi)."""
    return phase != FINAL
