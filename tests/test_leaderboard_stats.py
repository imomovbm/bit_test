"""Reyting yig'indisi (user_duel_stats): duel saqlanganda yangilanadi, eski hisob bilan bir xil natija, migratsiyada
to'ldiriladi, foydalanuvchi o'chirilganda yo'qoladi — reyting sahifasi duels jadvalini sanamaydi."""
import random
import sqlite3

from app.db import Database, now_ms

# Avvalgi (duels jadvalini har safar sanaydigan) reyting so'rovi — natijalarni solishtirish uchun.
LEGACY = """
    WITH parts AS (
        SELECT p1_id AS uid, CASE WHEN winner = 1 THEN 1 ELSE 0 END AS w, CASE WHEN winner = 2 THEN 1 ELSE 0 END AS l,
               CASE WHEN winner = 0 THEN 1 ELSE 0 END AS d, p1_correct AS c, total AS t FROM duels WHERE p1_id IS NOT NULL
        UNION ALL
        SELECT p2_id, CASE WHEN winner = 2 THEN 1 ELSE 0 END, CASE WHEN winner = 1 THEN 1 ELSE 0 END,
               CASE WHEN winner = 0 THEN 1 ELSE 0 END, p2_correct, total FROM duels WHERE p2_id IS NOT NULL)
    SELECT u.id, u.login, COUNT(*) AS played, SUM(w) AS wins, SUM(l) AS losses, SUM(d) AS draws, SUM(c) AS correct, SUM(t) AS questions
    FROM parts JOIN users u ON u.id = parts.uid GROUP BY u.id
    ORDER BY wins DESC, (wins * 1.0 / played) DESC, (SUM(c) * 1.0 / MAX(SUM(t), 1)) DESC, u.login_key LIMIT ?"""


def play_random(db, users, n, rnd):
    for _ in range(n):
        a, b = rnd.sample(users, 2)
        ca, cb = rnd.randint(0, 10), rnd.randint(0, 10)
        winner = 1 if ca > cb else 2 if cb > ca else rnd.choice([0, 1, 2])
        t = now_ms()
        db.save_duel(topic_id=None, topic_name="T", total=10, winner=winner, reason="score", started_at=t - 1000, finished_at=t,
                     p1={"id": a, "login": f"u{a}", "correct": ca, "time_ms": 900},
                     p2={"id": b, "login": f"u{b}", "correct": cb, "time_ms": 800})


def test_aggregate_matches_legacy_query_and_updates_per_duel(tmp_path):
    db = Database(tmp_path / "s.db")
    users = [db.create_user(f"o{i}", "x", False) for i in range(12)]
    rnd = random.Random(5)
    play_random(db, users, 300, rnd)
    legacy = [tuple(r) for r in db.conn.execute(LEGACY, (100,))]
    assert [tuple(r.values()) for r in db.leaderboard()] == legacy
    top = db.leaderboard(1)[0]
    play_random(db, [top["id"], users[0] if users[0] != top["id"] else users[1]], 1, rnd)
    assert db.leaderboard(100) and next(r for r in db.leaderboard() if r["id"] == top["id"])["played"] == top["played"] + 1
    # qayta hisoblash idempotent va bir xil natija beradi
    before = [tuple(r.values()) for r in db.leaderboard()]
    assert db.backfill_user_stats() == 12
    assert [tuple(r.values()) for r in db.leaderboard()] == before
    db.close()


def test_deleted_user_disappears_and_opponent_keeps_history(tmp_path):
    db = Database(tmp_path / "d.db")
    a, b = db.create_user("ali", "x", False), db.create_user("vali", "x", False)
    play_random(db, [a, b], 5, random.Random(1))
    db.conn.execute("DELETE FROM users WHERE id = ?", (a,))
    board = db.leaderboard()
    assert [r["login"] for r in board] == ["vali"] and board[0]["played"] == 5
    assert [tuple(r.values()) for r in board] == [tuple(r) for r in db.conn.execute(LEGACY, (100,))]
    db.close()


def test_old_database_is_backfilled_on_open(tmp_path):
    path = tmp_path / "old.db"
    db = Database(path)
    users = [db.create_user(f"o{i}", "x", False) for i in range(6)]
    play_random(db, users, 80, random.Random(9))
    expected = [tuple(r) for r in db.conn.execute(LEGACY, (100,))]
    db.close()
    raw = sqlite3.connect(path)  # eski sxemani taqlid qilamiz: yig'indi jadvali hali yo'q
    raw.execute("DROP TABLE user_duel_stats")
    raw.commit()
    raw.close()
    db = Database(path)
    assert [tuple(r.values()) for r in db.leaderboard()] == expected
    captured = []
    db.conn.set_trace_callback(captured.append)
    db.leaderboard()
    db.conn.set_trace_callback(None)
    plan = " ".join(r[3] for r in db.conn.execute(f"EXPLAIN QUERY PLAN {captured[-1]}"))
    assert "idx_user_stats_rank" in plan and "duels" not in plan  # indeks bo'yicha, duels jadvali sanalmaydi
    db.close()
