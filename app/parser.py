"""Test fayllarini o'qish.

Fayl formati:

    Savol matni
    ====
    Variant
    ====
    #To'g'ri variant
    ====
    Variant
    ++++
    Keyingi savol
    ...

* savollar ``++++`` bilan ajratiladi;
* savol matni va variantlar ``====`` bilan ajratiladi;
* to'g'ri variant oldiga ``#`` qo'yiladi (variant matni o'zi ``#`` bilan
  boshlanishi kerak bo'lsa, ``\\#`` deb yoziladi).
"""
from __future__ import annotations

import re

QUESTION_SEP = re.compile(r"\+{4,}")
OPTION_SEP = re.compile(r"={4,}")
MAX_OPTIONS = 10
MAX_QUESTION_LEN = 5000
MAX_OPTION_LEN = 2000


def _clean(part: str) -> str:
    lines = [line.rstrip() for line in part.split("\n")]
    return "\n".join(lines).strip()


def _snippet(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_questions(text: str) -> dict:
    """Matndan savollarni ajratib oladi.

    Natija: ``{"questions": [...], "errors": [...], "blocks": n}``.
    Har bir savol: ``{"text", "options", "correct"}`` (correct — to'g'ri variant indeksi).
    Xatolik bor savollar saqlanmaydi, ular ``errors`` ro'yxatida qaytadi.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "")
    questions: list[dict] = []
    errors: list[dict] = []
    number = 0

    for block in QUESTION_SEP.split(text):
        if not block.strip():
            continue
        number += 1
        parts = [_clean(p) for p in OPTION_SEP.split(block)]
        qtext = parts[0]
        options: list[str] = []
        correct: list[int] = []
        for opt in parts[1:]:
            if not opt:
                continue
            if opt.startswith("\\#"):
                opt = opt[1:]
            elif opt.startswith("#"):
                opt = opt[1:].strip()
                if opt.startswith("\\#"):  # "#\#matn" — to'g'ri javob matni o'zi # bilan boshlanadi
                    opt = opt[1:]
                correct.append(len(options))
            options.append(opt[:MAX_OPTION_LEN])

        problem = None
        if not qtext:
            problem = "Savol matni bo'sh"
        elif len(options) < 2:
            problem = "Javob variantlari kamida 2 ta bo'lishi kerak"
        elif len(options) > MAX_OPTIONS:
            problem = f"Javob variantlari {MAX_OPTIONS} tadan ko'p"
        elif not correct:
            problem = "To'g'ri javob # belgisi bilan belgilanmagan"
        elif len(correct) > 1:
            problem = f"{len(correct)} ta javob # bilan belgilangan (faqat bittasi bo'lishi kerak)"
        elif not options[correct[0]]:
            problem = "To'g'ri javob matni bo'sh"

        if problem:
            errors.append({"n": number, "message": problem, "snippet": _snippet(qtext) or "(bo'sh)"})
            continue
        questions.append({"text": qtext[:MAX_QUESTION_LEN], "options": options, "correct": correct[0]})

    return {"questions": questions, "errors": errors, "blocks": number}


class QuestionError(ValueError):
    """Qo'lda kiritilgan savol noto'g'ri (xabar foydalanuvchiga ko'rsatiladi)."""


def _plain(value, what: str, limit: int) -> str:
    if not isinstance(value, str):
        raise QuestionError(f"{what} matn bo'lishi kerak")
    text = _clean(value.replace("\r\n", "\n").replace("\r", "\n"))
    if not text:
        raise QuestionError(f"{what} bo'sh bo'lmasin")
    if len(text) > limit:
        raise QuestionError(f"{what} {limit} belgidan oshmasin")
    if QUESTION_SEP.search(text) or OPTION_SEP.search(text):
        raise QuestionError(f"{what} ichida ==== yoki ++++ bo'lmasin (bu belgilar fayl formatida ajratuvchi)")
    return text


def validate_question(data) -> dict:
    """Boshqaruv panelida qo'lda kiritilgan savolni tekshiradi: {"text", "options", "correct"}."""
    if not isinstance(data, dict):
        raise QuestionError("Savol ma'lumotlari noto'g'ri")
    text = _plain(data.get("text"), "Savol matni", MAX_QUESTION_LEN)
    raw = data.get("options")
    if not isinstance(raw, list):
        raise QuestionError("Javob variantlari ro'yxat bo'lishi kerak")
    if not 2 <= len(raw) <= MAX_OPTIONS:
        raise QuestionError(f"Javob variantlari 2 tadan {MAX_OPTIONS} tagacha bo'lishi kerak")
    options = [_plain(o, f"{i + 1}-variant", MAX_OPTION_LEN) for i, o in enumerate(raw)]
    if len({o.casefold() for o in options}) != len(options):
        raise QuestionError("Javob variantlari takrorlanmasin")
    correct = data.get("correct")
    if isinstance(correct, bool) or not isinstance(correct, int) or not 0 <= correct < len(options):
        raise QuestionError("To'g'ri javobni belgilang")
    return {"text": text, "options": options, "correct": correct}


def format_questions(questions: list[dict]) -> str:
    """Savollarni yuklash formatidagi matnga aylantiradi (``parse_questions`` ning teskarisi).

    Mavzuni .txt fayl sifatida yuklab olib, tahrirlab, qayta yuklash uchun ishlatiladi.
    """
    blocks = []
    for q in questions:
        lines = [q["text"]]
        for i, option in enumerate(q["options"]):
            if i == q["correct"]:
                option = f"#{option}"
            elif option.startswith("#"):
                option = f"\\{option}"  # oddiy variant # bilan boshlansa — \# deb yoziladi
            lines += ["====", option]
        blocks.append("\n".join(lines))
    return "\n++++\n".join(blocks) + "\n"
