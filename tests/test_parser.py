from app.parser import parse_questions

SAMPLE = """Dasturiy taʼminotni testlash nima?
====
Dasturni foydalanuvchilarga sotish
====
#Dastur talablarga mos ishlayotganini tekshirish jarayoni
====
Dasturchilar uchun ish jadvalini tuzish
++++
Testlashning asosiy maqsadi nima?
====
#Xatoni foydalanuvchi koʻrmasdan oldin topish
====
Dastur kodini qisqartirish
++++
"""


def test_parses_basic_format():
    res = parse_questions(SAMPLE)
    assert res["errors"] == []
    assert res["blocks"] == 2
    q1, q2 = res["questions"]
    assert q1["text"] == "Dasturiy taʼminotni testlash nima?"
    assert len(q1["options"]) == 3
    assert q1["options"][q1["correct"]] == "Dastur talablarga mos ishlayotganini tekshirish jarayoni"
    assert q2["correct"] == 0
    assert q2["options"][0] == "Xatoni foydalanuvchi koʻrmasdan oldin topish"


def test_handles_crlf_bom_and_spaces():
    text = "﻿" + SAMPLE.replace("\n", "\r\n").replace("====", "  =====  ")
    res = parse_questions(text)
    assert not res["errors"]
    assert len(res["questions"]) == 2


def test_reports_invalid_questions_and_keeps_valid_ones():
    text = "\n".join([
        "Belgilanmagan savol", "====", "A", "====", "B", "++++",
        "Ikkita to'g'ri", "====", "#A", "====", "#B", "++++",
        "Bitta variant", "====", "#A", "++++",
        "", "====", "#A", "====", "B", "++++",
        "To'g'ri savol", "====", "\\#include", "====", "#main", "++++",
    ])
    res = parse_questions(text)
    assert [e["n"] for e in res["errors"]] == [1, 2, 3, 4]
    assert len(res["questions"]) == 1
    q = res["questions"][0]
    assert q["options"] == ["#include", "main"]
    assert q["correct"] == 1


def test_multiline_question_text_is_kept():
    res = parse_questions("Kod natijasi?\nprint(1 + 1)\n====\n#2\n====\n11\n")
    assert res["questions"][0]["text"] == "Kod natijasi?\nprint(1 + 1)"


def test_empty_input():
    assert parse_questions("   \n  ")["questions"] == []
