"""SQLite ma'lumotlar bazasi bilan ishlash."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    login       TEXT NOT NULL,
    login_key   TEXT NOT NULL UNIQUE,
    pass_hash   TEXT NOT NULL,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    is_teacher  INTEGER NOT NULL DEFAULT 0,   -- o'qituvchi: o'yinlar (Balloon Pop, Octagon) yarata oladi
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
    active          INTEGER NOT NULL DEFAULT 1,
    question_count  INTEGER NOT NULL DEFAULT 0,
    source_file     TEXT,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      INTEGER NOT NULL,
    last_played_at  INTEGER,                    -- oxirgi duel boshlangan payt (ms); NULL — hali o'ynalmagan
    total_duels     INTEGER NOT NULL DEFAULT 0  -- shu mavzuda boshlangan duellar soni (hamma vaqt)
);

-- Mavzular faolligi: kunlik yig'indi (reytinglar faqat shu kichik jadvaldan hisoblanadi, duels jadvali sanalmaydi).
-- day — mahalliy kun (config.TZ_OFFSET_HOURS), 'YYYY-MM-DD'.
CREATE TABLE IF NOT EXISTS topic_activity_daily (
    topic_id       INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    day            TEXT NOT NULL,
    duels_started  INTEGER NOT NULL DEFAULT 0,
    unique_players INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (topic_id, day)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_activity_day ON topic_activity_daily(day, topic_id, duels_started);

-- Kunlik noyob o'yinchilarni sanash uchun yordamchi jadval (faqat oxirgi 2 kun saqlanadi).
CREATE TABLE IF NOT EXISTS topic_day_players (
    topic_id INTEGER NOT NULL,
    day      TEXT NOT NULL,
    user_id  INTEGER NOT NULL,
    PRIMARY KEY (topic_id, day, user_id)
) WITHOUT ROWID;

-- Mavzu holati (faol/yopilgan) o'zgarishlari jurnali: kim, qachon, qaysi mavzu.
CREATE TABLE IF NOT EXISTS topic_status_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id         INTEGER,
    topic_name       TEXT NOT NULL,
    active           INTEGER NOT NULL,
    changed_by       INTEGER,
    changed_by_login TEXT,
    reason           TEXT NOT NULL DEFAULT '',
    changed_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status_log_time ON topic_status_log(changed_at);

-- Savollar banki: har bir savol alohida saqlanadi va bir nechta mavzuga biriktirilishi mumkin.
CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    options     TEXT NOT NULL,
    correct     INTEGER NOT NULL,
    fingerprint TEXT NOT NULL DEFAULT '',
    source_file TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS topic_questions (
    topic_id    INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    PRIMARY KEY (topic_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_topic_questions_q ON topic_questions(question_id);

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
    ("topics", "active", "INTEGER NOT NULL DEFAULT 1"),
    ("users", "is_teacher", "INTEGER NOT NULL DEFAULT 0"),
    ("topics", "last_played_at", "INTEGER"),
    ("topics", "total_duels", "INTEGER NOT NULL DEFAULT 0"),
)

# Yangi ustunlarga tayanadigan indekslar (eski bazada ustunlar qo'shilgandan keyin yaratiladi).
INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_topics_active_name ON topics(active, name_key)",
    "CREATE INDEX IF NOT EXISTS idx_topics_active_played ON topics(active, last_played_at)",
    "CREATE INDEX IF NOT EXISTS idx_topics_played ON topics(last_played_at)",
    "CREATE INDEX IF NOT EXISTS idx_topics_active_total ON topics(active, total_duels)",
    "CREATE INDEX IF NOT EXISTS idx_topics_total ON topics(total_duels)",
    # "N kundan beri o'ynalmagan": oxirgi o'yin, hech o'ynalmagan bo'lsa — yaratilgan payt
    "CREATE INDEX IF NOT EXISTS idx_topics_idle ON topics(active, COALESCE(last_played_at, created_at))",
    "CREATE INDEX IF NOT EXISTS idx_topics_idle_all ON topics(COALESCE(last_played_at, created_at))",
)


def now_ms() -> int:
    return int(time.time() * 1000)


def day_key(ms: int) -> str:
    """Mahalliy kun (config.TZ_OFFSET_HOURS, standart — Toshkent UTC+5): 'YYYY-MM-DD'."""
    tz = timezone(timedelta(hours=config.TZ_OFFSET_HOURS))
    return datetime.fromtimestamp(ms / 1000, tz).strftime("%Y-%m-%d")


def day_back(day: str, days: int) -> str:
    """'YYYY-MM-DD' dan `days` kun oldingi kun."""
    return (date.fromisoformat(day) - timedelta(days=days)).isoformat()


def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def fingerprint(q: dict) -> str:
    """Bir xil savolni (bo'shliqlar va katta-kichik harflardan qat'i nazar) aniqlash uchun."""
    data = json.dumps([_norm(q["text"]), [_norm(o) for o in q["options"]], q["correct"]], ensure_ascii=False)
    return hashlib.sha1(data.encode("utf-8")).hexdigest()


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
        added = set()
        for table, column, ddl in MIGRATIONS:
            columns = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                added.add((table, column))
        for sql in INDEXES:
            self.conn.execute(sql)
        self._migrate_question_bank()
        if ("topics", "total_duels") in added:
            # faollik ustunlari endi qo'shildi: mavjud duellar tarixidan bir marta to'ldiriladi
            self.backfill_activity()

    def _migrate_question_bank(self) -> None:
        """Eski sxema: har bir savol bitta mavzuga tegishli edi (questions.topic_id).
        Yangi sxema: savollar banki + mavzu-savol bog'lanishlari. Savollar identifikatorlari saqlanadi."""
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(questions)")}
        if "topic_id" in columns:
            self.conn.execute("PRAGMA foreign_keys=OFF")
            try:
                with self.tx():
                    self.conn.execute("""CREATE TABLE questions_bank (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, options TEXT NOT NULL,
                        correct INTEGER NOT NULL, fingerprint TEXT NOT NULL DEFAULT '', source_file TEXT,
                        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at INTEGER NOT NULL DEFAULT 0)""")
                    self.conn.execute("""INSERT INTO questions_bank (id, text, options, correct, source_file, created_by, created_at)
                        SELECT q.id, q.text, q.options, q.correct, t.source_file, t.created_by, COALESCE(t.created_at, 0)
                        FROM questions q LEFT JOIN topics t ON t.id = q.topic_id""")
                    self.conn.execute("""INSERT OR IGNORE INTO topic_questions (topic_id, question_id, position)
                        SELECT topic_id, id, position FROM questions""")
                    self.conn.execute("DROP TABLE questions")
                    self.conn.execute("ALTER TABLE questions_bank RENAME TO questions")
            finally:
                self.conn.execute("PRAGMA foreign_keys=ON")
        rows = self.conn.execute("SELECT id, text, options, correct FROM questions WHERE fingerprint = ''").fetchall()
        if rows:
            with self.tx():
                self.conn.executemany(
                    "UPDATE questions SET fingerprint = ? WHERE id = ?",
                    [(fingerprint(self._question(r)), r["id"]) for r in rows],
                )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_fp ON questions(fingerprint)")

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

    def create_user(self, login: str, pass_hash: str, is_admin: bool, is_teacher: bool = False) -> int:
        cur = self.conn.execute(
            "INSERT INTO users (login, login_key, pass_hash, is_admin, is_teacher, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (login, login.casefold(), pass_hash, int(is_admin), int(is_teacher), now_ms()),
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
            SELECT u.id, u.login, u.is_admin, u.is_teacher, u.blocked, u.created_at, u.last_seen_at,
                   (SELECT COUNT(*) FROM duels d WHERE d.p1_id = u.id OR d.p2_id = u.id) AS duels,
                   (SELECT COUNT(*) FROM practice_results p WHERE p.user_id = u.id) AS practices,
                   (SELECT COUNT(*) FROM balloon_games b WHERE b.owner_id = u.id) AS balloon_games
            FROM users u ORDER BY u.created_at
            """
        )

    def set_admin(self, user_id: int, flag: bool) -> None:
        self.conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(flag), user_id))

    def set_teacher(self, user_id: int, flag: bool) -> None:
        self.conn.execute("UPDATE users SET is_teacher = ? WHERE id = ?", (int(flag), user_id))

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
            SELECT u.id, u.login, u.is_admin, u.is_teacher FROM sessions s JOIN users u ON u.id = s.user_id
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
            SELECT t.id, t.name, t.shuffle_options, t.active, t.question_count, t.source_file, t.created_at,
                   u.login AS author
            FROM topics t LEFT JOIN users u ON u.id = t.created_by
            ORDER BY t.created_at DESC, t.id DESC
            """
        )

    def get_topic(self, topic_id: int) -> dict | None:
        return self._one(
            "SELECT t.*, u.login AS author FROM topics t LEFT JOIN users u ON u.id = t.created_by WHERE t.id = ?",
            (topic_id,),
        )

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
                   VALUES (?, ?, ?, 0, ?, ?, ?)""",
                (name, name_key(name), int(shuffle), source_file, user_id, now_ms()),
            )
            topic_id = cur.lastrowid
            self._link([self._bank_insert(q, source_file, user_id) for q in questions], topic_id)
        return topic_id

    # ---------------------------------------------------- savollar banki
    def _bank_insert(self, q: dict, source_file: str | None, user_id: int | None) -> int:
        """Savolni bankka qo'shadi; aynan shunday savol bor bo'lsa — o'shasi qaytariladi (takrorlanmaydi)."""
        fp = fingerprint(q)
        row = self.conn.execute("SELECT id FROM questions WHERE fingerprint = ? ORDER BY id LIMIT 1", (fp,)).fetchone()
        if row:
            return row[0]
        cur = self.conn.execute(
            """INSERT INTO questions (text, options, correct, fingerprint, source_file, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (q["text"], json.dumps(q["options"], ensure_ascii=False), q["correct"], fp, source_file, user_id, now_ms()),
        )
        return cur.lastrowid

    def _link(self, question_ids: list[int], topic_id: int | None) -> int:
        """Savollarni mavzu oxiriga biriktiradi (allaqachon biriktirilganlari o'tkaziladi). Yangi bog'lanishlar soni."""
        if topic_id is None:
            return 0
        pos = self._scalar("SELECT COALESCE(MAX(position), -1) + 1 FROM topic_questions WHERE topic_id = ?", (topic_id,))
        added = 0
        for qid in dict.fromkeys(question_ids):  # tartibni saqlab, takrorlarni olib tashlash
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO topic_questions (topic_id, question_id, position) VALUES (?, ?, ?)", (topic_id, qid, pos)
            )
            if cur.rowcount:
                added += 1
                pos += 1
        self._recount(topic_id)
        return added

    def _recount(self, topic_id: int) -> None:
        self.conn.execute(
            "UPDATE topics SET question_count = (SELECT COUNT(*) FROM topic_questions WHERE topic_id = ?) WHERE id = ?",
            (topic_id, topic_id),
        )

    def add_questions(self, questions: list[dict], topic_ids: list[int] = (), source_file: str | None = None,
                      user_id: int | None = None) -> dict:
        """Savollarni bankka qo'shadi va ko'rsatilgan mavzularga biriktiradi."""
        with self.tx():
            before = self.bank_count()
            ids = [self._bank_insert(q, source_file, user_id) for q in questions]
            created = self.bank_count() - before
            for tid in topic_ids:
                self._link(ids, tid)
        return {"ids": ids, "created": created, "reused": len(ids) - created}

    def append_questions(self, topic_id: int, questions: list[dict], source_file: str | None = None,
                         user_id: int | None = None) -> list[int]:
        """Mavzu oxiriga savollar qo'shadi (bank orqali); savollar identifikatorlarini qaytaradi."""
        return self.add_questions(questions, [topic_id], source_file, user_id)["ids"]

    def link_questions(self, topic_id: int, question_ids: list[int]) -> int:
        """Bankdagi mavjud savollarni mavzuga biriktiradi."""
        with self.tx():
            marks = ",".join("?" * len(question_ids)) or "NULL"
            existing = {r[0] for r in self.conn.execute(f"SELECT id FROM questions WHERE id IN ({marks})", question_ids)}
            return self._link([q for q in question_ids if q in existing], topic_id)

    def unlink_question(self, topic_id: int, question_id: int) -> bool:
        """Savolni mavzudan olib tashlaydi — savol bankda qoladi."""
        with self.tx():
            cur = self.conn.execute("DELETE FROM topic_questions WHERE topic_id = ? AND question_id = ?", (topic_id, question_id))
            self._recount(topic_id)
        return cur.rowcount > 0

    def update_question(self, question_id: int, q: dict) -> bool:
        """Bankdagi savolni tahrirlaydi — o'zgarish u biriktirilgan barcha mavzularda ko'rinadi."""
        cur = self.conn.execute(
            "UPDATE questions SET text = ?, options = ?, correct = ?, fingerprint = ? WHERE id = ?",
            (q["text"], json.dumps(q["options"], ensure_ascii=False), q["correct"], fingerprint(q), question_id),
        )
        return cur.rowcount > 0

    def delete_bank_question(self, question_id: int) -> list[int] | None:
        """Savolni bankdan butunlay o'chiradi; u biriktirilgan mavzular ro'yxatini qaytaradi (topilmasa — None)."""
        with self.tx():
            topics = [r[0] for r in self.conn.execute("SELECT topic_id FROM topic_questions WHERE question_id = ?", (question_id,))]
            cur = self.conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
            if not cur.rowcount:
                return None
            for tid in topics:
                self._recount(tid)
        return topics

    def delete_bank_questions(self, question_ids: list[int]) -> tuple[int, int]:
        """Bir nechta savolni bankdan o'chiradi; (o'chirilganlar, ta'sirlangan mavzular) sonini qaytaradi."""
        ids = list(dict.fromkeys(question_ids))
        deleted, topics = 0, set()
        with self.tx():
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                topics.update(r[0] for r in self.conn.execute(
                    f"SELECT DISTINCT topic_id FROM topic_questions WHERE question_id IN ({marks})", chunk))
                deleted += self.conn.execute(f"DELETE FROM questions WHERE id IN ({marks})", chunk).rowcount
            for tid in topics:
                self._recount(tid)
        return deleted, len(topics)

    def replace_topic_questions(self, topic_id: int, questions: list[dict], source_file: str | None,
                                user_id: int | None = None) -> None:
        """Mavzu savollarini yangi fayldagilar bilan almashtiradi; eski savollar bankda qoladi."""
        with self.tx():
            self.conn.execute("DELETE FROM topic_questions WHERE topic_id = ?", (topic_id,))
            self._link([self._bank_insert(q, source_file, user_id) for q in questions], topic_id)
            if source_file:
                self.conn.execute("UPDATE topics SET source_file = ? WHERE id = ?", (source_file, topic_id))

    def bank_count(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM questions")

    def _bank_where(self, search: str, topic_id: int | None, unassigned: bool) -> tuple[str, list]:
        where, args = [], []
        if search:
            like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(q.text LIKE ? ESCAPE '\\' OR q.options LIKE ? ESCAPE '\\')")
            args += [like, like]
        if topic_id is not None:
            where.append("EXISTS (SELECT 1 FROM topic_questions tq WHERE tq.question_id = q.id AND tq.topic_id = ?)")
            args.append(topic_id)
        if unassigned:
            where.append("NOT EXISTS (SELECT 1 FROM topic_questions tq WHERE tq.question_id = q.id)")
        return (" WHERE " + " AND ".join(where)) if where else "", args

    def bank_page(self, search: str = "", topic_id: int | None = None, unassigned: bool = False,
                  offset: int = 0, limit: int = 50) -> tuple[int, list[dict]]:
        where, args = self._bank_where(search, topic_id, unassigned)
        total = self._scalar(f"SELECT COUNT(*) FROM questions q{where}", args)
        rows = self.conn.execute(
            f"""SELECT q.id, q.text, q.options, q.correct, q.source_file, q.created_at, u.login AS author
                FROM questions q LEFT JOIN users u ON u.id = q.created_by{where}
                ORDER BY q.id DESC LIMIT ? OFFSET ?""",
            [*args, limit, offset],
        ).fetchall()
        items = [{**self._question(r), "sourceFile": r["source_file"], "createdAt": r["created_at"], "author": r["author"]} for r in rows]
        self._attach_topics(items)
        return total, items

    def bank_ids(self, search: str = "", topic_id: int | None = None, unassigned: bool = False, limit: int = 5000) -> list[int]:
        where, args = self._bank_where(search, topic_id, unassigned)
        return [r[0] for r in self.conn.execute(f"SELECT q.id FROM questions q{where} ORDER BY q.id DESC LIMIT ?", [*args, limit])]

    def _attach_topics(self, items: list[dict]) -> None:
        if not items:
            return
        marks = ",".join("?" * len(items))
        by_q: dict[int, list] = {}
        for r in self.conn.execute(
            f"""SELECT tq.question_id, t.id, t.name FROM topic_questions tq JOIN topics t ON t.id = tq.topic_id
                WHERE tq.question_id IN ({marks}) ORDER BY t.name""",
            [i["id"] for i in items],
        ):
            by_q.setdefault(r[0], []).append({"id": r[1], "name": r[2]})
        for i in items:
            i["topics"] = by_q.get(i["id"], [])

    def long_option_counts(self, limit: int = 4) -> dict[int, int]:
        """Har bir mavzuda nechta savolda `limit` tadan ko'p variant bor (Octagon'da ko'pi bilan 4 ta shakl)."""
        rows = self.conn.execute(
            """SELECT tq.topic_id, COUNT(*) FROM topic_questions tq JOIN questions q ON q.id = tq.question_id
               WHERE json_array_length(q.options) > ? GROUP BY tq.topic_id""",
            (limit,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def update_topic(self, topic_id: int, name: str | None = None, shuffle: bool | None = None, active: bool | None = None) -> None:
        if active is not None:
            self.conn.execute("UPDATE topics SET active = ? WHERE id = ?", (int(active), topic_id))
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
            """SELECT q.id, q.text, q.options, q.correct,
                      (SELECT COUNT(*) FROM topic_questions x WHERE x.question_id = q.id) AS topic_count
               FROM topic_questions tq JOIN questions q ON q.id = tq.question_id
               WHERE tq.topic_id = ? ORDER BY tq.position""",
            (topic_id,),
        ).fetchall()
        return [{**self._question(r), "topicCount": r["topic_count"]} for r in rows]

    def question_ids(self, topic_id: int) -> list[int]:
        return [r[0] for r in self.conn.execute(
            "SELECT question_id FROM topic_questions WHERE topic_id = ? ORDER BY position", (topic_id,))]

    def question_by_id(self, question_id: int, topic_id: int | None = None) -> dict | None:
        """Savol (topic_id berilsa — faqat shu mavzuga biriktirilgan bo'lsa)."""
        if topic_id is None:
            row = self.conn.execute("SELECT id, text, options, correct FROM questions WHERE id = ?", (question_id,)).fetchone()
        else:
            row = self.conn.execute(
                """SELECT q.id, q.text, q.options, q.correct FROM topic_questions tq JOIN questions q ON q.id = tq.question_id
                   WHERE tq.question_id = ? AND tq.topic_id = ?""",
                (question_id, topic_id),
            ).fetchone()
        return self._question(row) if row else None

    def pick_questions(self, topic_id: int, limit: int | None, random_order: bool = True) -> list[dict]:
        order = "RANDOM()" if random_order else "tq.position"
        sql = f"""SELECT q.id, q.text, q.options, q.correct FROM topic_questions tq JOIN questions q ON q.id = tq.question_id
                  WHERE tq.topic_id = ? ORDER BY {order}"""
        args: list = [topic_id]
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
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

    # ---------------------------------------------------- mavzular faolligi
    def record_duel_start(self, topic_id: int, user_ids, at_ms: int | None = None) -> None:
        """Duel boshlandi: mavzu hisoblagichlari va kunlik yig'indi bitta qisqa tranzaksiyada (atomik +1, yo'qolmaydi)."""
        at_ms = at_ms or now_ms()
        day = day_key(at_ms)
        with self.tx():
            cur = self.conn.execute(
                "UPDATE topics SET total_duels = total_duels + 1, last_played_at = MAX(COALESCE(last_played_at, 0), ?) WHERE id = ?",
                (at_ms, topic_id),
            )
            if not cur.rowcount:
                return  # mavzu o'chirilgan
            self.conn.execute(
                """INSERT INTO topic_activity_daily (topic_id, day, duels_started, unique_players) VALUES (?, ?, 1, 0)
                   ON CONFLICT(topic_id, day) DO UPDATE SET duels_started = duels_started + 1""",
                (topic_id, day),
            )
            new_players = 0
            for uid in dict.fromkeys(u for u in user_ids if u is not None):
                new_players += self.conn.execute(
                    "INSERT OR IGNORE INTO topic_day_players (topic_id, day, user_id) VALUES (?, ?, ?)", (topic_id, day, uid)
                ).rowcount
            if new_players:
                self.conn.execute(
                    "UPDATE topic_activity_daily SET unique_players = unique_players + ? WHERE topic_id = ? AND day = ?",
                    (new_players, topic_id, day),
                )

    def backfill_activity(self) -> dict:
        """Mavzu hisoblagichlari va kunlik yig'indini duellar tarixidan qaytadan hisoblaydi (bitta tranzaksiya).

        Idempotent: necha marta ishga tushirilsa ham natija bir xil. Tarixda faqat tugagan duellar bor: ular
        boshlangan payt (duels.started_at) bo'yicha hisoblanadi. O'chirilgan mavzular (topic_id NULL) o'tkazib yuboriladi.
        """
        offset = int(config.TZ_OFFSET_HOURS * 3600)
        today = day_key(now_ms())
        with self.tx():
            self.conn.execute("""
                UPDATE topics SET
                    total_duels = (SELECT COUNT(*) FROM duels d WHERE d.topic_id = topics.id),
                    last_played_at = (SELECT MAX(started_at) FROM duels d WHERE d.topic_id = topics.id)
            """)
            self.conn.execute("DELETE FROM topic_activity_daily")
            self.conn.execute("DELETE FROM topic_day_players")
            self.conn.execute("CREATE TEMP TABLE IF NOT EXISTS backfill_players (topic_id INTEGER, day TEXT, user_id INTEGER)")
            self.conn.execute("DELETE FROM backfill_players")
            self.conn.execute(
                """INSERT INTO backfill_players (topic_id, day, user_id)
                   SELECT topic_id, date(started_at / 1000 + :o, 'unixepoch'), p1_id FROM duels
                   WHERE topic_id IS NOT NULL AND p1_id IS NOT NULL
                   UNION
                   SELECT topic_id, date(started_at / 1000 + :o, 'unixepoch'), p2_id FROM duels
                   WHERE topic_id IS NOT NULL AND p2_id IS NOT NULL""",
                {"o": offset},
            )
            self.conn.execute(
                """INSERT INTO topic_activity_daily (topic_id, day, duels_started, unique_players)
                   SELECT c.topic_id, c.day, c.n, COALESCE(u.n, 0)
                   FROM (SELECT topic_id, date(started_at / 1000 + ?, 'unixepoch') AS day, COUNT(*) AS n
                         FROM duels WHERE topic_id IS NOT NULL GROUP BY 1, 2) c
                   LEFT JOIN (SELECT topic_id, day, COUNT(*) AS n FROM backfill_players GROUP BY 1, 2) u
                     ON u.topic_id = c.topic_id AND u.day = c.day""",
                (offset,),
            )
            # bugun va kecha o'ynaganlar: yangi duellarda noyob o'yinchilar qayta sanalmasligi uchun
            self.conn.execute(
                "INSERT OR IGNORE INTO topic_day_players SELECT topic_id, day, user_id FROM backfill_players WHERE day >= ?",
                (day_back(today, 1),),
            )
            self.conn.execute("DROP TABLE backfill_players")
            summary = {
                "duels": self._scalar("SELECT COUNT(*) FROM duels WHERE topic_id IS NOT NULL"),
                "topicsPlayed": self._scalar("SELECT COUNT(*) FROM topics WHERE total_duels > 0"),
                "days": self._scalar("SELECT COUNT(DISTINCT day) FROM topic_activity_daily"),
                "dailyRows": self._scalar("SELECT COUNT(*) FROM topic_activity_daily"),
            }
        return summary

    def prune_day_players(self, keep_days: int = 2) -> int:
        """Noyob o'yinchilar jadvalidan eski kunlarni o'chiradi (faqat bugun va kecha kerak)."""
        cutoff = day_back(day_key(now_ms()), keep_days - 1)
        return self.conn.execute("DELETE FROM topic_day_players WHERE day < ?", (cutoff,)).rowcount

    def activity_since(self, since_day: str) -> list[tuple[int, str, int]]:
        """Kunlik yig'indi qatorlari (mavzu, kun, boshlangan duellar) — since_day dan boshlab (indeks: idx_activity_day)."""
        return [tuple(r) for r in self.conn.execute(
            "SELECT topic_id, day, duels_started FROM topic_activity_daily WHERE day >= ?", (since_day,)
        ).fetchall()]

    def playable_topics(self) -> list[dict]:
        """Bosh sahifa va lobbi uchun: faol va savoli bor mavzular (reyting keshi shundan quriladi)."""
        return self._all(
            """SELECT id, name, name_key, question_count, last_played_at, total_duels, created_at
               FROM topics WHERE active = 1 AND question_count > 0"""
        )

    # ------------------------------------------- boshqaruv: mavzular faolligi
    ADMIN_SORTS = {  # ustun -> ORDER BY (indekslar: idx_topics_active_name, idx_topics_played, idx_topics_total ...)
        "name": "t.name_key",
        "lastPlayed": "t.last_played_at",
        "total": "t.total_duels",
        "status": "t.active",
        "created": "t.id",
    }

    @staticmethod
    def _idle_cutoff(days: int) -> int:
        return now_ms() - days * 86_400_000

    def _admin_where(self, status: str, search: str, idle_days: int) -> tuple[str, list]:
        where, args = [], []
        if status in ("active", "inactive"):
            where.append("t.active = ?")
            args.append(1 if status == "active" else 0)
        if search:
            like = "%" + name_key(search).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("t.name_key LIKE ? ESCAPE '\\'")
            args.append(like)
        if idle_days > 0:  # "N kundan beri o'ynalmagan": oxirgi o'yin (hech o'ynalmagan bo'lsa — yaratilgan payt)
            where.append("COALESCE(t.last_played_at, t.created_at) < ?")
            args.append(self._idle_cutoff(idle_days))
        return (" WHERE " + " AND ".join(where)) if where else "", args

    def admin_topic_page(self, status: str = "all", search: str = "", idle_days: int = 0, sort: str = "name",
                         desc: bool = False, offset: int = 0, limit: int = 25, recent: dict | None = None) -> dict:
        """Boshqaruv paneli: sahifalangan mavzular ro'yxati (saralash va filtrlar serverda, indekslar bilan).

        recent — oxirgi 30 kundagi duellar (katalog keshidan, mavzu -> son); "recent" bo'yicha saralashda faqat
        identifikatorlar o'qiladi, so'ng tanlangan sahifa qatorlari olinadi."""
        recent = recent or {}
        where, args = self._admin_where(status, search, idle_days)
        total = self._scalar(f"SELECT COUNT(*) FROM topics t{where}", args)
        direction = "DESC" if desc else "ASC"
        if sort == "recent":
            rows = self.conn.execute(f"SELECT t.id, t.name_key FROM topics t{where}", args).fetchall()
            rows.sort(key=lambda r: (recent.get(r[0], 0), r[1]), reverse=desc)
            ids = [r[0] for r in rows[offset:offset + limit]]
            items = self._admin_rows(ids)
        else:
            order = self.ADMIN_SORTS.get(sort, "t.name_key")
            tie = "" if order == "t.name_key" else ", t.name_key"
            ids = [r[0] for r in self.conn.execute(
                f"SELECT t.id FROM topics t{where} ORDER BY {order} {direction}{tie} LIMIT ? OFFSET ?", [*args, limit, offset])]
            items = self._admin_rows(ids)
        for item in items:
            item["duels30"] = recent.get(item["id"], 0)
        counts = dict(self.conn.execute("SELECT active, COUNT(*) FROM topics GROUP BY active").fetchall())
        return {"total": total, "items": items, "counts": {"active": counts.get(1, 0), "inactive": counts.get(0, 0)}}

    def _admin_rows(self, ids: list[int]) -> list[dict]:
        """Tanlangan mavzular (bitta so'rov, N+1 yo'q), berilgan tartibda."""
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = {r["id"]: r for r in self._all(
            f"""SELECT t.id, t.name, t.active, t.question_count, t.last_played_at, t.total_duels, t.created_at,
                       t.source_file, t.shuffle_options, u.login AS author
                FROM topics t LEFT JOIN users u ON u.id = t.created_by WHERE t.id IN ({marks})""", ids)}
        return [rows[i] for i in ids if i in rows]

    def suggested_topics(self, days: int, offset: int = 0, limit: int = 25) -> dict:
        """O'chirishga tavsiya: faol, lekin `days` kundan beri o'ynalmagan mavzular (eng uzoq o'ynalmagani oldin)."""
        cutoff = self._idle_cutoff(days)
        cond = "WHERE t.active = 1 AND COALESCE(t.last_played_at, t.created_at) < ?"
        total = self._scalar(f"SELECT COUNT(*) FROM topics t {cond}", (cutoff,))
        ids = [r[0] for r in self.conn.execute(
            f"SELECT t.id FROM topics t {cond} ORDER BY COALESCE(t.last_played_at, t.created_at), t.id LIMIT ? OFFSET ?",
            (cutoff, limit, offset))]
        return {"total": total, "items": self._admin_rows(ids)}

    def suggested_ids(self, days: int, limit: int = 5000) -> list[int]:
        cutoff = self._idle_cutoff(days)
        return [r[0] for r in self.conn.execute(
            """SELECT id FROM topics WHERE active = 1 AND COALESCE(last_played_at, created_at) < ?
               ORDER BY COALESCE(last_played_at, created_at) LIMIT ?""", (cutoff, limit))]

    def set_topics_active(self, topic_ids, active: bool, user: dict | None, reason: str) -> list[dict]:
        """Mavzular holatini o'zgartiradi (yumshoq: savollar va duellar tarixi saqlanadi) va jurnalga yozadi.
        Faqat haqiqatan o'zgarganlar qaytariladi."""
        ids = list(dict.fromkeys(topic_ids))
        if not ids:
            return []
        changed = []
        at = now_ms()
        with self.tx():
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                rows = self.conn.execute(
                    f"SELECT id, name FROM topics WHERE id IN ({marks}) AND active != ?", [*chunk, int(active)]).fetchall()
                for r in rows:
                    changed.append({"id": r["id"], "name": r["name"]})
                if rows:
                    self.conn.execute(f"UPDATE topics SET active = ? WHERE id IN ({','.join('?' * len(rows))})",
                                      [int(active), *[r["id"] for r in rows]])
            self.conn.executemany(
                """INSERT INTO topic_status_log (topic_id, topic_name, active, changed_by, changed_by_login, reason, changed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(t["id"], t["name"], int(active), user["id"] if user else None, user["login"] if user else None, reason, at)
                 for t in changed],
            )
        return changed

    def status_log(self, offset: int = 0, limit: int = 25) -> dict:
        total = self._scalar("SELECT COUNT(*) FROM topic_status_log")
        items = self._all(
            "SELECT * FROM topic_status_log ORDER BY changed_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset))
        return {"total": total, "items": items}

    def auto_deactivate(self, days: int) -> list[dict]:
        """Avtomatik yopish (sozlamada yoqilgan bo'lsa, standart — o'chiq): `days` kundan beri o'ynalmagan mavzular."""
        return self.set_topics_active(self.suggested_ids(days), False, None, f"auto:{days}")

    def recent_topics(self, user_id: int, limit: int = 5) -> list[int]:
        """Foydalanuvchi oxirgi o'ynagan (tugatgan) duellar mavzulari, eng yangisi oldin."""
        rows = self.conn.execute(
            """SELECT topic_id, MAX(finished_at) AS t FROM (
                   SELECT topic_id, finished_at FROM duels WHERE p1_id = :u AND topic_id IS NOT NULL
                   UNION ALL
                   SELECT topic_id, finished_at FROM duels WHERE p2_id = :u AND topic_id IS NOT NULL)
               GROUP BY topic_id ORDER BY t DESC LIMIT :n""",
            {"u": user_id, "n": limit},
        ).fetchall()
        return [r[0] for r in rows]

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

    def count_balloon_games(self, owner_id: int) -> int:
        return self._scalar("SELECT COUNT(*) FROM balloon_games WHERE owner_id = ?", (owner_id,))

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
                "teachers": one("SELECT COUNT(*) FROM users WHERE is_teacher = 1 AND is_admin = 0"),
                "blocked": one("SELECT COUNT(*) FROM users WHERE blocked = 1"),
                "newWeek": one("SELECT COUNT(*) FROM users WHERE created_at >= ?", (since_ms,)),
            },
            "topics": {
                "total": one("SELECT COUNT(*) FROM topics"),
                "questions": one("SELECT COUNT(*) FROM questions"),
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
            "SELECT id, login, is_admin, is_teacher, blocked, created_at FROM users ORDER BY created_at DESC, id DESC LIMIT ?",
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
