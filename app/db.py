"""SQLite ma'lumotlar bazasi bilan ishlash."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    login       TEXT NOT NULL,
    login_key   TEXT NOT NULL UNIQUE,
    pass_hash   TEXT NOT NULL,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    blocked     INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    last_seen_at INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    name_key        TEXT NOT NULL UNIQUE,
    shuffle_options INTEGER NOT NULL DEFAULT 1,
    question_count  INTEGER NOT NULL DEFAULT 0,
    source_file     TEXT,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id  INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    options   TEXT NOT NULL,
    correct   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic_id, position);

CREATE TABLE IF NOT EXISTS duels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id    INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    topic_name  TEXT NOT NULL,
    p1_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    p2_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    p1_login    TEXT NOT NULL,
    p2_login    TEXT NOT NULL,
    p1_correct  INTEGER NOT NULL,
    p2_correct  INTEGER NOT NULL,
    p1_time_ms  INTEGER NOT NULL,
    p2_time_ms  INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    winner      INTEGER NOT NULL,          -- 0: durang, 1: p1, 2: p2
    reason      TEXT NOT NULL,             -- score | time | draw | left | afk | both_left
    started_at  INTEGER NOT NULL,
    finished_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_duels_p1 ON duels(p1_id);
CREATE INDEX IF NOT EXISTS idx_duels_p2 ON duels(p2_id);

CREATE TABLE IF NOT EXISTS practice_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id    INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    topic_name  TEXT NOT NULL,
    total       INTEGER NOT NULL,
    answered    INTEGER NOT NULL,
    correct     INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practice_user ON practice_results(user_id);

CREATE TABLE IF NOT EXISTS balloon_games (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id    INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    topic_name  TEXT NOT NULL,
    status      TEXT NOT NULL,             -- active | finished
    state       TEXT NOT NULL,             -- o'yin holati (JSON, app/balloon.py)
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_balloon_owner ON balloon_games(owner_id, updated_at);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

# Eski bazalarga keyinroq qo'shilgan ustunlar (jadval nomi, ustun, ta'rif).
MIGRATIONS = (
    ("users", "blocked", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "last_seen_at", "INTEGER"),
)


def now_ms() -> int:
    return int(time.time() * 1000)


def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


class Database:
    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        for table, column, ddl in MIGRATIONS:
            columns = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def _one(self, sql: str, args=()) -> dict | None:
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _scalar(self, sql: str, args=()):
        return self.conn.execute(sql, args).fetchone()[0]

    def _all(self, sql: str, args=()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # ------------------------------------------------------------ users
    def count_users(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_user(self, login: str, pass_hash: str, is_admin: bool) -> int:
        cur = self.conn.execute(
            "INSERT INTO users (login, login_key, pass_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
            (login, login.casefold(), pass_hash, int(is_admin), now_ms()),
        )
        return cur.lastrowid

    def user_by_login(self, login: str) -> dict | None:
        return self._one("SELECT * FROM users WHERE login_key = ?", (login.casefold(),))

    def user_by_id(self, user_id: int) -> dict | None:
        return self._one("SELECT * FROM users WHERE id = ?", (user_id,))

    def admin_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]

    def list_users(self) -> list[dict]:
        return self._all(
            """
            SELECT u.id, u.login, u.is_admin, u.blocked, u.created_at, u.last_seen_at,
                   (SELECT COUNT(*) FROM duels d WHERE d.p1_id = u.id OR d.p2_id = u.id) AS duels,
                   (SELECT COUNT(*) FROM practice_results p WHERE p.user_id = u.id) AS practices,
                   (SELECT COUNT(*) FROM balloon_games b WHERE b.owner_id = u.id) AS balloon_games
            FROM users u ORDER BY u.created_at
            """
        )

    def set_admin(self, user_id: int, flag: bool) -> None:
        self.conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(flag), user_id))

    def set_blocked(self, user_id: int, flag: bool) -> None:
        """Bloklangan foydalanuvchi tizimga kira olmaydi; uning barcha sessiyalari o'chiriladi."""
        with self.tx():
            self.conn.execute("UPDATE users SET blocked = ? WHERE id = ?", (int(flag), user_id))
            if flag:
                self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def touch_user(self, user_id: int) -> None:
        self.conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (now_ms(), user_id))

    def set_password(self, user_id: int, pass_hash: str, keep_session: str | None = None) -> None:
        """Parolni almashtiradi va barcha sessiyalarni yopadi (keep_session — saqlab qolinadigan joriy sessiya)."""
        with self.tx():
            self.conn.execute("UPDATE users SET pass_hash = ? WHERE id = ?", (pass_hash, user_id))
            self.conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash IS NOT ?", (user_id, keep_session))

    def delete_user(self, user_id: int) -> None:
        self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # --------------------------------------------------------- sessions
    def create_session(self, token_hash: str, user_id: int, days: int) -> None:
        now = now_ms()
        self.conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now, now + days * 86_400_000),
        )

    def session_user(self, token_hash: str) -> dict | None:
        return self._one(
            """
            SELECT u.id, u.login, u.is_admin FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ? AND u.blocked = 0
            """,
            (token_hash, now_ms()),
        )

    def delete_session(self, token_hash: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def purge_sessions(self) -> None:
        self.conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_ms(),))

    # ----------------------------------------------------------- topics
    def list_topics(self) -> list[dict]:
        return self._all(
            """
            SELECT t.id, t.name, t.shuffle_options, t.question_count, t.source_file, t.created_at,
                   u.login AS created_by
            FROM topics t LEFT JOIN users u ON u.id = t.created_by
            ORDER BY t.created_at DESC, t.id DESC
            """
        )

    def get_topic(self, topic_id: int) -> dict | None:
        return self._one("SELECT * FROM topics WHERE id = ?", (topic_id,))

    def topic_name_taken(self, name: str, exclude_id: int | None = None) -> bool:
        row = self.conn.execute(
            "SELECT id FROM topics WHERE name_key = ? AND id IS NOT ?", (name_key(name), exclude_id)
        ).fetchone()
        return row is not None

    def create_topic(self, name: str, questions: list[dict], shuffle: bool, source_file: str | None, user_id: int | None) -> int:
        name = " ".join(name.split())
        with self.tx():
            cur = self.conn.execute(
                """INSERT INTO topics (name, name_key, shuffle_options, question_count, source_file, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, name_key(name), int(shuffle), len(questions), source_file, user_id, now_ms()),
            )
            topic_id = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO questions (topic_id, position, text, options, correct) VALUES (?, ?, ?, ?, ?)",
                [
                    (topic_id, i, q["text"], json.dumps(q["options"], ensure_ascii=False), q["correct"])
                    for i, q in enumerate(questions)
                ],
            )
        return topic_id

    def replace_topic_questions(self, topic_id: int, questions: list[dict], source_file: str | None) -> None:
        """Mavzu savollarini yangi fayldagilar bilan almashtiradi (mavzu nomi va sozlamalari saqlanadi)."""
        with self.tx():
            self.conn.execute("DELETE FROM questions WHERE topic_id = ?", (topic_id,))
            self.conn.executemany(
                "INSERT INTO questions (topic_id, position, text, options, correct) VALUES (?, ?, ?, ?, ?)",
                [
                    (topic_id, i, q["text"], json.dumps(q["options"], ensure_ascii=False), q["correct"])
                    for i, q in enumerate(questions)
                ],
            )
            self.conn.execute(
                "UPDATE topics SET question_count = ?, source_file = COALESCE(?, source_file) WHERE id = ?",
                (len(questions), source_file, topic_id),
            )

    def update_topic(self, topic_id: int, name: str | None = None, shuffle: bool | None = None) -> None:
        if name is not None:
            name = " ".join(name.split())
            self.conn.execute("UPDATE topics SET name = ?, name_key = ? WHERE id = ?", (name, name_key(name), topic_id))
        if shuffle is not None:
            self.conn.execute("UPDATE topics SET shuffle_options = ? WHERE id = ?", (int(shuffle), topic_id))

    def delete_topic(self, topic_id: int) -> None:
        self.conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))

    @staticmethod
    def _question(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "text": row["text"], "options": json.loads(row["options"]), "correct": row["correct"]}

    def topic_questions(self, topic_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, text, options, correct FROM questions WHERE topic_id = ? ORDER BY position", (topic_id,)
        ).fetchall()
        return [self._question(r) for r in rows]

    def question_ids(self, topic_id: int) -> list[int]:
        return [r[0] for r in self.conn.execute("SELECT id FROM questions WHERE topic_id = ? ORDER BY position", (topic_id,))]

    def question_by_id(self, question_id: int, topic_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT id, text, options, correct FROM questions WHERE id = ? AND topic_id = ?", (question_id, topic_id)
        ).fetchone()
        return self._question(row) if row else None

    def pick_questions(self, topic_id: int, limit: int | None, random_order: bool = True) -> list[dict]:
        order = "RANDOM()" if random_order else "position"
        sql = f"SELECT id, text, options, correct FROM questions WHERE topic_id = ? ORDER BY {order}"
        args: tuple = (topic_id,)
        if limit is not None:
            sql += " LIMIT ?"
            args = (topic_id, limit)
        return [self._question(r) for r in self.conn.execute(sql, args).fetchall()]

    # ------------------------------------------------------------ duels
    def save_duel(self, *, topic_id, topic_name, p1, p2, total, winner, reason, started_at, finished_at) -> int:
        """p1/p2: {'id', 'login', 'correct', 'time_ms'}; winner: 0 durang, 1 yoki 2."""
        if topic_id is not None and not self.get_topic(topic_id):
            topic_id = None
        ids = [p["id"] if self.user_by_id(p["id"]) else None for p in (p1, p2)]
        cur = self.conn.execute(
            """INSERT INTO duels (topic_id, topic_name, p1_id, p2_id, p1_login, p2_login, p1_correct, p2_correct,
                                  p1_time_ms, p2_time_ms, total, winner, reason, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                topic_id, topic_name, ids[0], ids[1], p1["login"], p2["login"], p1["correct"], p2["correct"],
                p1["time_ms"], p2["time_ms"], total, winner, reason, started_at, finished_at,
            ),
        )
        return cur.lastrowid

    def user_duels(self, user_id: int, limit: int = 30) -> list[dict]:
        rows = self._all(
            "SELECT * FROM duels WHERE p1_id = ? OR p2_id = ? ORDER BY finished_at DESC LIMIT ?",
            (user_id, user_id, limit),
        )
        result = []
        for r in rows:
            mine = 1 if r["p1_id"] == user_id else 2
            other = 2 if mine == 1 else 1
            outcome = "draw" if r["winner"] == 0 else ("win" if r["winner"] == mine else "lose")
            result.append({
                "id": r["id"],
                "topicName": r["topic_name"],
                "opponent": r[f"p{other}_login"],
                "myCorrect": r[f"p{mine}_correct"],
                "oppCorrect": r[f"p{other}_correct"],
                "myTimeMs": r[f"p{mine}_time_ms"],
                "oppTimeMs": r[f"p{other}_time_ms"],
                "total": r["total"],
                "result": outcome,
                "reason": r["reason"],
                "finishedAt": r["finished_at"],
            })
        return result

    def duel_summary(self, user_id: int) -> dict:
        row = self._one(
            """
            SELECT COUNT(*) AS played,
                   COALESCE(SUM(CASE WHEN (p1_id = :u AND winner = 1) OR (p2_id = :u AND winner = 2) THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM(CASE WHEN winner = 0 THEN 1 ELSE 0 END), 0) AS draws,
                   COALESCE(SUM(CASE WHEN p1_id = :u THEN p1_correct ELSE p2_correct END), 0) AS correct,
                   COALESCE(SUM(total), 0) AS questions
            FROM duels WHERE p1_id = :u OR p2_id = :u
            """,
            {"u": user_id},
        )
        row["losses"] = row["played"] - row["wins"] - row["draws"]
        return row

    def leaderboard(self, limit: int = 100) -> list[dict]:
        return self._all(
            """
            WITH parts AS (
                SELECT p1_id AS uid,
                       CASE WHEN winner = 1 THEN 1 ELSE 0 END AS w,
                       CASE WHEN winner = 2 THEN 1 ELSE 0 END AS l,
                       CASE WHEN winner = 0 THEN 1 ELSE 0 END AS d,
                       p1_correct AS c, total AS t
                FROM duels WHERE p1_id IS NOT NULL
                UNION ALL
                SELECT p2_id,
                       CASE WHEN winner = 2 THEN 1 ELSE 0 END,
                       CASE WHEN winner = 1 THEN 1 ELSE 0 END,
                       CASE WHEN winner = 0 THEN 1 ELSE 0 END,
                       p2_correct, total
                FROM duels WHERE p2_id IS NOT NULL
            )
            SELECT u.id, u.login, COUNT(*) AS played, SUM(w) AS wins, SUM(l) AS losses, SUM(d) AS draws,
                   SUM(c) AS correct, SUM(t) AS questions
            FROM parts JOIN users u ON u.id = parts.uid
            GROUP BY u.id
            ORDER BY wins DESC, (wins * 1.0 / played) DESC, (SUM(c) * 1.0 / MAX(SUM(t), 1)) DESC, u.login_key
            LIMIT ?
            """,
            (limit,),
        )

    # --------------------------------------------------------- practice
    def save_practice(self, user_id: int, topic_id: int | None, topic_name: str, total: int, answered: int, correct: int) -> None:
        if topic_id is not None and not self.get_topic(topic_id):
            topic_id = None
        self.conn.execute(
            """INSERT INTO practice_results (user_id, topic_id, topic_name, total, answered, correct, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, topic_id, topic_name, total, answered, correct, now_ms()),
        )

    def user_practice(self, user_id: int, limit: int = 30) -> list[dict]:
        return self._all(
            """SELECT id, topic_name AS topicName, total, answered, correct, created_at AS createdAt
               FROM practice_results WHERE user_id = ? ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        )

    def practice_summary(self, user_id: int) -> dict:
        return self._one(
            """SELECT COUNT(*) AS sessions, COALESCE(SUM(correct), 0) AS correct, COALESCE(SUM(total), 0) AS questions
               FROM practice_results WHERE user_id = ?""",
            (user_id,),
        )

    # ------------------------------------------------- balloon pop o'yinlari
    @staticmethod
    def _balloon_row(row: dict | None) -> dict | None:
        if row:
            row["state"] = json.loads(row["state"])
        return row

    def create_balloon_game(self, owner_id: int, topic_id: int, topic_name: str, state: dict) -> int:
        now = now_ms()
        cur = self.conn.execute(
            """INSERT INTO balloon_games (owner_id, topic_id, topic_name, status, state, created_at, updated_at)
               VALUES (?, ?, ?, 'active', ?, ?, ?)""",
            (owner_id, topic_id, topic_name, json.dumps(state, ensure_ascii=False), now, now),
        )
        return cur.lastrowid

    def balloon_game(self, game_id: int) -> dict | None:
        return self._balloon_row(self._one("SELECT * FROM balloon_games WHERE id = ?", (game_id,)))

    def save_balloon_game(self, game_id: int, state: dict, status: str) -> None:
        self.conn.execute(
            "UPDATE balloon_games SET state = ?, status = ?, updated_at = ? WHERE id = ?",
            (json.dumps(state, ensure_ascii=False), status, now_ms(), game_id),
        )

    def balloon_games(self, owner_id: int, limit: int = 30) -> list[dict]:
        rows = self._all(
            "SELECT * FROM balloon_games WHERE owner_id = ? ORDER BY updated_at DESC, id DESC LIMIT ?",
            (owner_id, limit),
        )
        return [self._balloon_row(r) for r in rows]

    def delete_balloon_game(self, game_id: int) -> None:
        self.conn.execute("DELETE FROM balloon_games WHERE id = ?", (game_id,))

    # ------------------------------------------------------- sozlamalar
    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # ------------------------------------------------ boshqaruv paneli
    def overview(self, since_ms: int) -> dict:
        """Umumiy statistika: since_ms — "oxirgi hafta" hisobi boshlanadigan vaqt."""
        one = self._scalar
        return {
            "users": {
                "total": one("SELECT COUNT(*) FROM users"),
                "admins": one("SELECT COUNT(*) FROM users WHERE is_admin = 1"),
                "blocked": one("SELECT COUNT(*) FROM users WHERE blocked = 1"),
                "newWeek": one("SELECT COUNT(*) FROM users WHERE created_at >= ?", (since_ms,)),
            },
            "topics": {
                "total": one("SELECT COUNT(*) FROM topics"),
                "questions": one("SELECT COALESCE(SUM(question_count), 0) FROM topics"),
            },
            "duels": {
                "total": one("SELECT COUNT(*) FROM duels"),
                "week": one("SELECT COUNT(*) FROM duels WHERE finished_at >= ?", (since_ms,)),
            },
            "practice": {
                "total": one("SELECT COUNT(*) FROM practice_results"),
                "week": one("SELECT COUNT(*) FROM practice_results WHERE created_at >= ?", (since_ms,)),
            },
            "balloon": {
                "total": one("SELECT COUNT(*) FROM balloon_games"),
                "active": one("SELECT COUNT(*) FROM balloon_games WHERE status = 'active'"),
                "week": one("SELECT COUNT(*) FROM balloon_games WHERE created_at >= ?", (since_ms,)),
            },
        }

    def recent_users(self, limit: int = 6) -> list[dict]:
        return self._all(
            "SELECT id, login, is_admin, blocked, created_at FROM users ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )

    def recent_duels(self, limit: int = 6) -> list[dict]:
        return self._all(
            """SELECT id, topic_name, p1_login, p2_login, p1_correct, p2_correct, total, winner, reason, finished_at
               FROM duels ORDER BY finished_at DESC LIMIT ?""",
            (limit,),
        )

    def recent_balloon_games(self, limit: int = 6) -> list[dict]:
        rows = self._all(
            """SELECT b.id, b.state, b.status, b.updated_at, u.login AS owner
               FROM balloon_games b LEFT JOIN users u ON u.id = b.owner_id
               ORDER BY b.updated_at DESC, b.id DESC LIMIT ?""",
            (limit,),
        )
        return [self._balloon_row(r) for r in rows]
