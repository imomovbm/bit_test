"""Mavzular faolligi: duel boshlanganda hisoblagichlar, kunlik yig'indi, poyga holatlari va tarixdan to'ldirish."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app import config
from app.db import Database, day_back, day_key

QS = [{"text": f"Savol {i}", "options": ["A", "B", "C"], "correct": 0} for i in range(3)]
TASHKENT = timezone(timedelta(hours=5))


def ms(y, mo, d, h=12, mi=0, tz=TASHKENT):
    return int(datetime(y, mo, d, h, mi, tzinfo=tz).timestamp() * 1000)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TZ_OFFSET_HOURS", 5.0)
    d = Database(tmp_path / "a.db")
    yield d
    d.close()


def users(db, n):
    return [db.create_user(f"user{i}", "x", False) for i in range(n)]


def daily(db, topic_id):
    return {r["day"]: (r["duels_started"], r["unique_players"]) for r in db._all(
        "SELECT day, duels_started, unique_players FROM topic_activity_daily WHERE topic_id = ?", (topic_id,))}


def test_day_key_uses_local_timezone(monkeypatch):
    monkeypatch.setattr(config, "TZ_OFFSET_HOURS", 5.0)
    late_utc = int(datetime(2026, 3, 1, 19, 30, tzinfo=timezone.utc).timestamp() * 1000)  # Toshkentda 2 mart 00:30
    assert day_key(late_utc) == "2026-03-02"
    monkeypatch.setattr(config, "TZ_OFFSET_HOURS", 0.0)
    assert day_key(late_utc) == "2026-03-01"
    assert day_back("2026-03-01", 1) == "2026-02-28" and day_back("2026-01-05", 29) == "2025-12-07"


def test_duel_start_updates_counters_and_daily_aggregate(db):
    a, b, c = users(db, 3)
    t = db.create_topic("Mavzu", QS, False, None, None)
    assert db.get_topic(t)["total_duels"] == 0 and db.get_topic(t)["last_played_at"] is None
    db.record_duel_start(t, [a, b], ms(2026, 3, 1, 10))
    db.record_duel_start(t, [a, b], ms(2026, 3, 1, 11))   # o'sha ikki o'yinchi — noyoblar soni o'zgarmaydi
    db.record_duel_start(t, [a, c], ms(2026, 3, 1, 9))    # kechroq yozilgan, lekin oldinroq boshlangan
    db.record_duel_start(t, [b, c], ms(2026, 3, 2, 10))
    topic = db.get_topic(t)
    assert topic["total_duels"] == 4 and topic["last_played_at"] == ms(2026, 3, 2, 10)
    assert daily(db, t) == {"2026-03-01": (3, 3), "2026-03-02": (1, 2)}
    db.record_duel_start(999, [a, b])  # o'chirilgan mavzu — hech narsa yozilmaydi
    assert db._scalar("SELECT COUNT(*) FROM topic_activity_daily WHERE topic_id = 999") == 0


def test_concurrent_duel_starts_lose_no_updates(tmp_path, monkeypatch):
    """8 ta alohida ulanish (masalan, bir nechta jarayon) bir vaqtda 50 tadan duel boshlaydi."""
    monkeypatch.setattr(config, "TZ_OFFSET_HOURS", 5.0)
    path = tmp_path / "c.db"
    main = Database(path)
    players = users(main, 20)
    t = main.create_topic("Ommabop", QS, False, None, None)
    at = ms(2026, 5, 10, 15)
    errors = []

    def worker(k):
        conn = Database(path)
        try:
            for i in range(50):
                conn.record_duel_start(t, [players[(k + i) % 20], players[(k + i + 1) % 20]], at + i)
        except sqlite3.Error as e:  # pragma: no cover — testni yiqitadi
            errors.append(e)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors
    assert main.get_topic(t)["total_duels"] == 400
    assert daily(main, t) == {"2026-05-10": (400, 20)}
    main.close()


def test_backfill_from_duel_history_is_correct_and_idempotent(db):
    a, b, c = users(db, 3)
    t1 = db.create_topic("Birinchi", QS, False, None, None)
    t2 = db.create_topic("Ikkinchi", QS, False, None, None)
    gone = db.create_topic("O'chiriladi", QS, False, None, None)

    def duel(topic, p1, p2, started):
        db.save_duel(topic_id=topic, topic_name="x", p1={"id": p1, "login": "p1", "correct": 1, "time_ms": 10},
                     p2={"id": p2, "login": "p2", "correct": 0, "time_ms": 10}, total=3, winner=1, reason="score",
                     started_at=started, finished_at=started + 60_000)

    duel(t1, a, b, ms(2026, 3, 1, 23, 50))                                     # 1 mart (Toshkent vaqti)
    duel(t1, a, c, int(datetime(2026, 3, 1, 19, 30, tzinfo=timezone.utc).timestamp() * 1000))  # Toshkentda 2 mart 00:30
    duel(t1, b, c, ms(2026, 3, 2, 8))
    duel(t2, a, b, ms(2026, 2, 20, 9))
    duel(gone, a, b, ms(2026, 3, 3, 9))
    db.delete_topic(gone)  # tarix qoladi, mavzu yo'q (topic_id NULL)
    db.conn.execute("UPDATE topics SET total_duels = 99, last_played_at = 1")  # buzilgan qiymatlar — qayta hisoblanadi
    summary = db.backfill_activity()
    assert summary["duels"] == 4 and summary["topicsPlayed"] == 2
    assert db.get_topic(t1)["total_duels"] == 3 and db.get_topic(t1)["last_played_at"] == ms(2026, 3, 2, 8)
    assert db.get_topic(t2)["total_duels"] == 1
    assert daily(db, t1) == {"2026-03-01": (1, 2), "2026-03-02": (2, 3)}
    assert daily(db, t2) == {"2026-02-20": (1, 2)}
    first = db._all("SELECT * FROM topic_activity_daily ORDER BY topic_id, day")
    db.backfill_activity()
    assert db._all("SELECT * FROM topic_activity_daily ORDER BY topic_id, day") == first


def test_backfill_keeps_today_unique_players_consistent(db):
    a, b = users(db, 2)
    t = db.create_topic("Bugungi", QS, False, None, None)
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    db.save_duel(topic_id=t, topic_name="x", p1={"id": a, "login": "a", "correct": 1, "time_ms": 1},
                 p2={"id": b, "login": "b", "correct": 0, "time_ms": 1}, total=3, winner=1, reason="score",
                 started_at=now - 1000, finished_at=now)
    db.backfill_activity()
    db.record_duel_start(t, [a, b], now)  # o'sha o'yinchilar bugun yana — noyoblar 2 ligicha qoladi
    assert daily(db, t)[day_key(now)] == (2, 2)


def test_old_database_is_migrated_and_backfilled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TZ_OFFSET_HOURS", 5.0)
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT NOT NULL, login_key TEXT NOT NULL UNIQUE,
            pass_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
        CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
            shuffle_options INTEGER NOT NULL DEFAULT 1, question_count INTEGER NOT NULL DEFAULT 0, source_file TEXT,
            created_by INTEGER, created_at INTEGER NOT NULL);
        CREATE TABLE duels (id INTEGER PRIMARY KEY AUTOINCREMENT, topic_id INTEGER, topic_name TEXT NOT NULL,
            p1_id INTEGER, p2_id INTEGER, p1_login TEXT NOT NULL, p2_login TEXT NOT NULL, p1_correct INTEGER NOT NULL,
            p2_correct INTEGER NOT NULL, p1_time_ms INTEGER NOT NULL, p2_time_ms INTEGER NOT NULL, total INTEGER NOT NULL,
            winner INTEGER NOT NULL, reason TEXT NOT NULL, started_at INTEGER NOT NULL, finished_at INTEGER NOT NULL);
        INSERT INTO users (login, login_key, pass_hash, created_at) VALUES ('a', 'a', 'x', 0), ('b', 'b', 'x', 0);
        INSERT INTO topics (name, name_key, question_count, created_at) VALUES ('Eski', 'eski', 5, 0);
    """)
    started = ms(2025, 12, 31, 20)
    old.execute("""INSERT INTO duels (topic_id, topic_name, p1_id, p2_id, p1_login, p2_login, p1_correct, p2_correct,
                   p1_time_ms, p2_time_ms, total, winner, reason, started_at, finished_at)
                   VALUES (1, 'Eski', 1, 2, 'a', 'b', 3, 2, 1, 1, 5, 1, 'score', ?, ?)""", (started, started + 1))
    old.commit()
    old.close()
    db = Database(path)
    topic = db.get_topic(1)
    assert topic["total_duels"] == 1 and topic["last_played_at"] == started and topic["active"] == 1
    assert daily(db, 1) == {"2025-12-31": (1, 2)}
    indexes = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_activity_day", "idx_topics_active_played", "idx_topics_idle"} <= indexes
    db.close()


def test_prune_day_players_keeps_only_recent_days(db):
    a, b = users(db, 2)
    t = db.create_topic("Mavzu", QS, False, None, None)
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    db.record_duel_start(t, [a, b], now - 5 * 86_400_000)
    db.record_duel_start(t, [a, b], now)
    assert db.prune_day_players() == 2
    assert db._scalar("SELECT COUNT(*) FROM topic_day_players") == 2
    assert sum(v[0] for v in daily(db, t).values()) == 2  # yig'indi o'zgarmaydi


def test_backfill_cli_dry_run_never_touches_the_original(tmp_path, monkeypatch, capsys):
    from app import backfill

    monkeypatch.setattr(config, "TZ_OFFSET_HOURS", 5.0)
    path = tmp_path / "prod.db"
    db = Database(path)
    a, b = users(db, 2)
    t = db.create_topic("Mavzu", QS, False, None, None)
    db.save_duel(topic_id=t, topic_name="x", p1={"id": a, "login": "a", "correct": 1, "time_ms": 1},
                 p2={"id": b, "login": "b", "correct": 0, "time_ms": 1}, total=3, winner=1, reason="score",
                 started_at=ms(2026, 1, 10), finished_at=ms(2026, 1, 10) + 1)
    db.conn.execute("UPDATE topics SET total_duels = 0")
    db.close()
    before = path.read_bytes()
    assert backfill.main(["--db", str(path), "--dry-run"]) == 0
    assert "duellar: 1" in capsys.readouterr().out and path.read_bytes() == before
    assert backfill.main(["--db", str(path)]) == 0
    db = Database(path)
    assert db.get_topic(t)["total_duels"] == 1
    db.close()
