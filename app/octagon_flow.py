"""Octagon o'yinining bosqichlar mashinasi — sof (holatsiz) qoidalar: bosqichlar, ruxsat etilgan o'tishlar va
vaqtlar. Taymerlar, ulanishlar va xabarlar app/octagon.py da; bu modul faqat "qaysi bosqichdan qaysiga o'tish mumkin"
va "bosqich qancha davom etadi" degan savollarga javob beradi (tests/test_octagon_flow.py).

    lobby -> topic_intro -> question_read -> question_active -> question_result -> leaderboard
                               ^                                                    |
                               +----------------- (keyingi savol) ------------------+
    leaderboard (oxirgi savoldan keyin) -> podium

* topic_intro — o'qituvchi «Boshlash»ni bosgach bir marta: mavzu nomi hamma ekranlarda (config.OCTAGON_INTRO soniya);
* question_read — savol matni faqat o'qituvchi ekranida, o'quvchilarda rangli shakllar (bosib bo'lmaydi) va sanoq
  (config.OCTAGON_READ soniya);
* question_active — javoblar qabul qilinadi; javob vaqti shu bosqich boshlangan paytdan o'lchanadi (savol vaqti);
* question_result, leaderboard — o'qituvchi «Keyingi» bilan o'tadi; podium — o'yin tugadi.

O'yinni muddatidan oldin tugatish (end): istalgan bosqichdan podiumga (savol paytida — avval natija hisoblanadi).
"""
from __future__ import annotations

LOBBY = "lobby"
INTRO = "topic_intro"
READ = "question_read"
ACTIVE = "question_active"
RESULT = "question_result"
BOARD = "leaderboard"
PODIUM = "podium"

# O'quvchilarga bosqich nomi emas, shu ro'yxatdagi indeksi yuboriladi (static/js/octagon/common.js — PHASES bilan bir xil)
PHASES = (LOBBY, INTRO, READ, ACTIVE, RESULT, BOARD, PODIUM)
CODE = {name: i for i, name in enumerate(PHASES)}

TIMED = frozenset({INTRO, READ, ACTIVE})          # server taymeri bilan tugaydigan bosqichlar
WITH_QUESTION = frozenset({READ, ACTIVE, RESULT, BOARD})  # joriy savol indeksi ma'noga ega

# Ruxsat etilgan o'tishlar (boshqasi — dasturdagi xato, IllegalTransition)
TRANSITIONS: dict[str, frozenset[str]] = {
    LOBBY: frozenset({INTRO}),
    INTRO: frozenset({READ, PODIUM}),
    READ: frozenset({ACTIVE, PODIUM}),
    ACTIVE: frozenset({RESULT}),          # tugatish ham avval natijani hisoblaydi (RESULT -> PODIUM)
    RESULT: frozenset({BOARD, PODIUM}),
    BOARD: frozenset({READ, PODIUM}),
    PODIUM: frozenset(),
}


class IllegalTransition(RuntimeError):
    """Bosqichlar mashinasi buzildi (masalan, taymer o'yin tugagandan keyin ishladi) — dasturdagi xato."""


def check(src: str, dst: str) -> None:
    if dst not in TRANSITIONS.get(src, frozenset()):
        raise IllegalTransition(f"{src} -> {dst}")


def duration(phase: str, time_limit_s: float, intro_s: float, read_s: float) -> float | None:
    """Bosqich davomiyligi (soniya) yoki None — o'qituvchi o'tkazadigan bosqichlar uchun."""
    return {INTRO: intro_s, READ: read_s, ACTIVE: time_limit_s}.get(phase)


def after_timer(phase: str) -> str:
    """Taymer tugaganda keyingi bosqich (faqat TIMED bosqichlar uchun)."""
    nxt = {INTRO: READ, READ: ACTIVE, ACTIVE: RESULT}.get(phase)
    if nxt is None:
        raise IllegalTransition(f"{phase}: taymer bilan tugamaydi")
    return nxt


def on_next(phase: str, has_more_questions: bool) -> str | None:
    """O'qituvchining «Keyingi» tugmasi. None — bu bosqichda hech narsa qilmaydi (masalan, kirish yoki o'qish
    paytida: ular taymer bilan tugaydi yoki «O'tkazib yuborish» bilan; ikki marta bosish bosqichni sakratib yubormaydi)."""
    if phase == ACTIVE:
        return RESULT
    if phase == RESULT:
        return BOARD
    if phase == BOARD:
        return READ if has_more_questions else PODIUM
    return None


def on_skip(phase: str) -> str | None:
    """«O'tkazib yuborish»: mavzu kirishi va o'qish vaqtini qisqartirish, savolni muddatidan oldin yopish."""
    return {INTRO: READ, READ: ACTIVE, ACTIVE: RESULT}.get(phase)


def can_answer(phase: str) -> bool:
    """Javob faqat savol faol bo'lganda qabul qilinadi (o'qish paytida — yo'q)."""
    return phase == ACTIVE


def can_join(phase: str) -> bool:
    """Qo'shilish o'yin tugaguncha mumkin (kech qo'shilgan o'tgan savollar uchun 0 ball oladi)."""
    return phase != PODIUM
