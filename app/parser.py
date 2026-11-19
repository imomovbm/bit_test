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
