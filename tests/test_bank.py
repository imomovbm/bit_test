"""Savollar banki: eski bazani ko'chirish, takrorlarni birlashtirish, mavzularga biriktirish."""
import json
import sqlite3

from app.db import Database

OLD_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT NOT NULL, login_key TEXT NOT NULL UNIQUE,
    pass_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
    shuffle_options INTEGER NOT NULL DEFAULT 1, question_count INTEGER NOT NULL DEFAULT 0, source_file TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at INTEGER NOT NULL);
CREATE TABLE questions (id INTEGER PRIMARY KEY AUTOINCREMENT, topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, text TEXT NOT NULL, options TEXT NOT NULL, correct INTEGER NOT NULL);
CREATE INDEX idx_questions_topic ON questions(topic_id, position);
"""


def q(text, options=("x", "y"), correct=0):
    return {"text": text, "options": list(options), "correct": correct}


def test_old_database_is_migrated_keeping_ids(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO users VALUES (1, 'admin', 'admin', 'x', 1, 1)")
    c.execute("INSERT INTO topics VALUES (1, 'A', 'a', 1, 2, 'a.txt', 1, 5), (2, 'B', 'b', 1, 1, NULL, 1, 6)")
    rows = [(10, 1, 0, "Q1", ["x", "y"], 0), (11, 1, 1, "Q2", ["x", "y"], 1), (12, 2, 0, "Q3", ["p", "q"], 1)]
    c.executemany("INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?)", [(*r[:4], json.dumps(r[4]), r[5]) for r in rows])
    c.commit()
    c.close()

    db = Database(path)
    columns = {r[1] for r in db.conn.execute("PRAGMA table_info(questions)")}
    assert "topic_id" not in columns and "fingerprint" in columns
    assert [x["id"] for x in db.topic_questions(1)] == [10, 11]
    assert db.question_ids(2) == [12]
    assert db.question_by_id(12, 1) is None and db.question_by_id(12, 2)["text"] == "Q3"
    assert db.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()
    Database(path).close()  # ikkinchi marta ochilganda hech narsa buzilmaydi


def test_bank_dedup_links_and_deletes(tmp_path):
    db = Database(tmp_path / "bank.db")
    a = db.create_topic("A", [q("Birinchi"), q("Ikkinchi")], True, "a.txt", None)
    b = db.create_topic("B", [], True, None, None)
    # bir xil savol (bo'shliq va harf farqi bilan) qayta yuklansa — bankda takrorlanmaydi
    res = db.add_questions([q("  birinchi "), q("Uchinchi")], [b])
    assert res["created"] == 1 and res["reused"] == 1 and db.bank_count() == 3
    assert [x["text"] for x in db.topic_questions(b)] == ["Birinchi", "Uchinchi"]
    shared = db.topic_questions(b)[0]
    assert shared["topicCount"] == 2
    # bankdagi savolni boshqa mavzuga biriktirish (qayta biriktirish e'tiborsiz)
    third = db.topic_questions(b)[1]["id"]
    assert db.link_questions(a, [third, third, 99999]) == 1
    assert db.link_questions(a, [third]) == 0
    assert db.get_topic(a)["question_count"] == 3
    # mavzudan olib tashlash — savol bankda qoladi
    assert db.unlink_question(a, third) is True and db.bank_count() == 3
    # tahrirlash hamma mavzuda ko'rinadi
    db.update_question(shared["id"], q("Birinchi (yangi)"))
    assert db.topic_questions(a)[0]["text"] == db.topic_questions(b)[0]["text"] == "Birinchi (yangi)"
    # qidiruv, mavzu bo'yicha filtr, mavzusizlar, sahifalash
    total, items = db.bank_page(search="KKI")
    assert total == 1 and items[0]["text"] == "Ikkinchi" and items[0]["topics"] == [{"id": a, "name": "A"}]
    assert db.bank_page(search="100%")[0] == 0  # % belgisi oddiy belgi sifatida qidiriladi
    assert db.bank_page(topic_id=a)[0] == 2
    db.delete_topic(b)
    total, items = db.bank_page(unassigned=True)
    assert total == 1 and items[0]["text"] == "Uchinchi" and items[0]["topics"] == []
    assert db.bank_page(limit=1, offset=1)[1][0]["id"] == db.bank_ids()[1]
    # bankdan butunlay o'chirish mavzular sonini yangilaydi
    assert db.delete_bank_question(shared["id"]) == [a]
    assert db.get_topic(a)["question_count"] == 1 and db.delete_bank_question(shared["id"]) is None
    db.close()
