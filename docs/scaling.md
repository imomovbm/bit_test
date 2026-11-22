# Duel at scale — topic activity, ranking, lobby and admin tools

This document describes how the duel side of TestDuel stays fast with thousands of topics and hundreds of
simultaneous players: what is stored, how rankings are computed, how the lobby pairs players, which admin tools
exist, what was measured under load, and what is deliberately **not** supported. Octagon and the Games panel are
untouched by this work (their E2E suite still passes: 323 checks).

Contents: [Activity tracking](#1-activity-tracking) · [Schema & migration](#2-schema-migration-and-backfill) ·
[Ranking](#3-main-page-ranking) · [Lobby](#4-lobby-and-matchmaking) · [Admin](#5-admin-tools) ·
[Scaling](#6-scaling-and-limits) · [Security](#7-security) · [Load test](#8-load-test) ·
[EXPLAIN](#9-query-plans) · [Tests](#10-how-to-run-the-tests) · [Limitations](#11-limitations)

---

## 1. Activity tracking

A duel counts as **started** when the 3-second countdown ends (`DuelHub._begin`). A pair that falls apart during
the countdown (disconnect or "leave") is cancelled and recorded nowhere, so cancelled handshakes never inflate
popularity. At that moment `Database.record_duel_start()` runs **one short transaction**:

| Write | Statement | Why it is race-safe |
|---|---|---|
| topic counters | `UPDATE topics SET total_duels = total_duels + 1, last_played_at = MAX(COALESCE(last_played_at,0), :now)` | relative `+1` inside `BEGIN IMMEDIATE`; `MAX` keeps the newest time even if two writes interleave |
| daily aggregate | `INSERT … ON CONFLICT(topic_id, day) DO UPDATE SET duels_started = duels_started + 1` | upsert, no read-modify-write in Python |
| unique players | `INSERT OR IGNORE INTO topic_day_players(topic_id, day, user_id)` and `unique_players += rowcount` | the primary key makes "first time today" exact |

`tests/test_activity.py::test_counters_are_exact_under_concurrency` runs 8 threads × 50 starts on one topic and
expects exactly 400. The write is a handful of primary-key operations (well under a millisecond) and happens at the
end of the countdown, not when the user clicks "Find opponent", so it does not slow down starting a duel.

**Popularity is never computed from `duels` rows.** Rankings read only `topic_activity_daily` and the topic
counters. The leaderboard ("Reyting") also stopped scanning `duels`: it now reads `user_duel_stats`, updated in the
same transaction that saves a finished duel (see §8 — it was the biggest hotspot).

"Day" is the local calendar day: `TD_TZ_OFFSET_HOURS` (default `5`, Tashkent, UTC+5).

## 2. Schema, migration and backfill

New columns and tables (`app/db.py`):

```sql
ALTER TABLE topics ADD COLUMN last_played_at INTEGER;                     -- ms of the last duel start, NULL = never
ALTER TABLE topics ADD COLUMN total_duels INTEGER NOT NULL DEFAULT 0;     -- all-time duel starts

CREATE TABLE topic_activity_daily (topic_id, day TEXT 'YYYY-MM-DD', duels_started, unique_players,
                                   PRIMARY KEY (topic_id, day)) WITHOUT ROWID;
CREATE INDEX idx_activity_day ON topic_activity_daily(day, topic_id, duels_started);   -- covering, for the 30-day window
CREATE TABLE topic_day_players (topic_id, day, user_id, PRIMARY KEY (topic_id, day, user_id)) WITHOUT ROWID;
                                                                        -- helper, only today + yesterday are kept
CREATE TABLE topic_status_log (id, topic_id, topic_name, active, changed_by, changed_by_login, reason, changed_at);
CREATE TABLE user_duel_stats (user_id PRIMARY KEY, played, wins, losses, draws, correct, questions);
CREATE INDEX idx_user_stats_rank ON user_duel_stats(wins DESC, played);

-- topics: (active, name_key), (active, last_played_at), (last_played_at), (active, total_duels), (total_duels),
--         (active, COALESCE(last_played_at, created_at)), (COALESCE(last_played_at, created_at))
-- duels:  (finished_at)  — admin overview and "recent duels"
```

**Migration is automatic** when the new app version opens the database:

1. missing columns are added (`MIGRATIONS`), then the indexes (`INDEXES`);
2. if `topics.total_duels` was just added, `backfill_activity()` fills the counters and the daily aggregate from the
   existing duel history;
3. if `user_duel_stats` did not exist, `backfill_user_stats()` fills it.

Each backfill is **one transaction** and **idempotent** (it deletes and rebuilds the derived data, so running it twice
gives the same result). Measured on the load-test database (547k duels, 5,000 topics, 20,000 users): activity backfill
**2.9 s**, user-stats backfill + `duels(finished_at)` index **1.75 s**. The first version of the activity backfill
took **300 s** at that size (per-topic correlated subqueries over `duels`, which has no `topic_id` index); it now reads
`duels` once with `GROUP BY` into an indexed temp table.

History contains only *finished* duels, so the backfill counts finished duels by their `started_at`. Duels that were
started but never finished (server restart mid-duel) are counted live but not by a later backfill.

### Running the backfill safely

Normally nothing has to be run by hand. To check the result on production data first:

```bash
# 1) dry run on a consistent copy (SQLite backup API, the source is opened read-only; safe while the app runs)
python -m app.backfill --db data/testduel.db --dry-run
# 2) or work on your own copy and inspect it
sqlite3 data/testduel.db ".backup '/tmp/copy.db'"   # or: cp with the app stopped
python -m app.backfill --db /tmp/copy.db
# 3) apply to the real file (stop the app or run during a quiet period; it is one transaction)
python -m app.backfill --db data/testduel.db
```

The dry run prints duels counted, topics played, days, daily rows, players in the leaderboard, the time taken and the
top 5 topics, and deletes the copy. Tests: `tests/test_activity.py` (correctness, idempotency, old-schema migration,
dry run does not touch the original) and `tests/test_leaderboard_stats.py` (aggregate = old `GROUP BY` result, old
database backfilled on open, deleted users).

## 3. Main page ranking

Tabs (`GET /api/topics/browse?period=hot|today|week|month|all&q=&offset=&limit=`):

| Tab | Count used | Notes |
|---|---|---|
| **Qizgʻin** (Hot, default) | `hot` score | trending: recent days weigh more, plus live activity |
| **Bugun** (Today) | duels started today | local day |
| **Hafta** (This week) | last 7 days incl. today | |
| **Oy** (This month) | last 30 days incl. today | also shown as "30 kunda" in admin |
| **Hammasi** (All time) | `topics.total_duels` | |

**Hot formula** — one place, `app/config.py` (+ `hot_score()` in `app/catalog.py`):

```
hot = Σ_{d = 0 … HOT_WINDOW_DAYS-1}  duels_started(today − d) · 0.5^(d / HOT_HALF_LIFE_DAYS)
      + HOT_LIVE_WEIGHT · (players waiting now + duels in progress now)
```

Defaults: `TD_HOT_WINDOW_DAYS=14`, `TD_HOT_HALF_LIFE_DAYS=2` (yesterday ≈ 0.71, 2 days ago 0.5, 4 days ago 0.25),
`TD_HOT_LIVE_WEIGHT=3`.

**Order inside every tab:** count for that tab (desc) → hot score (desc) → last played (newest first) → name.
Topics with **zero** activity in the tab follow all active ones, ordered by last played, then name. Inactive
topics and topics without questions are not shown (main page, lobby, practice).

**Cards** show the name, a hint for the tab ("Bugun 12 ta duel", "Shu hafta 30 ta duel"…) plus "oxirgi oʻyin:
5 daqiqa oldin" / "hali oʻynalmagan", the question count and the live "N kutmoqda · M oʻynamoqda" badge.

**Search** is debounced (300 ms), case-insensitive substring on the normalised name, server-side. **Paging**: 24 per
request (`limit` ≤ 60), infinite scroll (IntersectionObserver) with a "Yana yuklash (N)" button as fallback.
**No page loads all topics** any more: the duel main page and the Oʻrganish (practice) page share
`static/js/topic-browser.js`.

### Caching and accepted staleness

`TopicCatalog` (`app/catalog.py`) keeps the ranked id lists of all five tabs in memory; a page request is a slice of
a list (≈0.02 ms; search ≈0.8 ms over 5,000 names) and runs **no SQL**. The cache is rebuilt:

* immediately when topics change (create, rename, activate/deactivate, questions added/removed);
* at most every `TD_RANKING_REFRESH` = **5 s** after new duel activity;
* at the latest every `TD_RANKING_TTL` = **30 s**.

Accepted staleness: tab **order and counts may be up to 30 s old** (≤ 5 s after a new duel). The live
"waiting / playing" badges are **not** cached: visible cards are subscribed through the lobby channel and update
within ~1 s. A rebuild reads only the 30-day window through `idx_activity_day` (13k rows here) and takes ~30 ms for
5,000 topics.

## 4. Lobby and matchmaking

All in `app/hub.py` (`DuelHub`), state in memory, one asyncio event loop.

* **Seeks list**: nickname, topic (or "Istalgan mavzu"), a ticking wait time and a one-click **Qoʻshilish** (Join)
  button; newest first, capped at **50** (`LOBBY_LIMIT`), optional **topic filter** (server-side).
* **"Hozir faol mavzular"**: up to 12 topics with someone waiting or playing, with live counts; a click seeks on that
  topic.
* **Find opponent on a topic** (clicking a topic card): if someone already waits on that topic, or waits for "any
  topic", the duel starts immediately (oldest seek first); otherwise a seek is opened.
* **"Istalgan mavzuda raqib topish"** (any topic) — the documented rule:
  1. join the longest-waiting seek on one of **your 5 most recently played topics**, otherwise
  2. the **longest-waiting seek on any topic**;
  3. if only other "any topic" seekers wait, pair with the oldest of them on the **hottest** topic;
  4. otherwise wait (others can join you; joining an "any" seek uses the hottest topic).
* **Avoid repeat pairing**: if there is a choice, the previous opponent is skipped (`_prefer`).
* **Atomic join**: `seek:join` checks and flips the seek `open → taken` in one synchronous step (no `await` in
  between), so of two simultaneous clicks exactly one starts a duel; the other receives
  `error {code: "taken"}` ("…allaqachon boshqa raqib bilan juftlandi…"), the row is removed at once and the client
  re-requests a fresh lobby snapshot.
* **Rules**: no self-join (`own`); one open seek per user (a new one replaces the old); no seeking/joining while in
  a duel (`busy`); seeks on inactive/empty topics are refused (`topic`).
* **Expiry and cleanup**: a seek expires after `TD_SEEK_TTL` = **120 s** (the waiting screen shows the countdown and
  an "extend" button in the last 30 s); it is removed on cancel, when the last tab closes / the socket drops, when the
  user starts another duel, or when an admin closes the topic (with a message); a background sweep every 10 s
  removes anything left over. Hourly maintenance prunes `topic_day_players` and runs auto-deactivation if enabled.
* **Handshake**: if a player disconnects or leaves during the 3 s countdown, the other gets `duel:cancel`
  ("Raqibning aloqasi uzildi — duel bekor qilindi") and nothing is recorded.
* **Real time**: WebSocket. A client sends `lobby:sub {topicId?, watch:[≤60 topic ids]}` and gets one snapshot,
  then only `lobby:diff {add, del, counts, live, waiting, online}` — **at most once per second** (`LOBBY_FLUSH`) and
  only to subscribed clients (the lobby and waiting screens subscribe; the duel screen unsubscribes). The online
  counter in the header comes as `stats` at most every 15 s. There is no polling fallback: the client reconnects
  with backoff and re-subscribes.

Protocol summary — client → server: `seek:create {topicId|null}`, `seek:cancel {seekId?}`, `seek:join {seekId}`,
`lobby:sub`, `lobby:unsub`, `presence:sub` / `presence:unsub` (admins only). Server → client: `hello`, `stats`,
`lobby`, `lobby:diff`, `queue` (own seek or null), `duel:start`, `duel:cancel`, `topics`, `presence`,
`presence:diff`, `error {message, code}`.

## 5. Admin tools

«Boshqaruv» → «Test mavzulari» (admin only; every endpoint uses `require_admin` → 401/403):

* **Barcha mavzular** — server-side list (`GET /api/admin/topic-activity`): columns last played, total duels, duels in
  the last 30 days, status (switch), plus edit/export/delete; sortable by name, status, last played, total, 30 days,
  created (on phones: a sort dropdown); filters: status (all/active/closed with counts), name search,
  "not played for 30/60/90/180+ days" (never-played topics count from their creation date); 25 per page.
  Checkboxes (kept across pages) + a bulk bar "Yopish (N)" / "Ochish (N)" with a **count confirmation**.
* **Oʻchirishga tavsiya** — active topics not played for **N days** (default **90**: `TD_SUGGEST_IDLE_DAYS`, or the
  "Standart qilib saqlash" setting), oldest first; **one-click "Yopish"** per row and **"Hammasini yopish (N)"** with a
  count confirmation (`/suggested/ids` + `POST /status`, ≤ 2,000 ids per call).
* **Jurnal** — every status change: time, topic, opened/closed, who (or "tizim"), reason (manual / bulk /
  suggestion / `auto:N`).
* **Avtomatik yopish** — optional, **OFF by default**; when set to N ≥ 7 days, active topics idle for N days are
  closed by the hourly maintenance and logged with reason `auto:N`.

Deactivation is **soft and reversible** (`topics.active = 0`): questions, duel history and counters stay; the topic
disappears from the main page, lobby and practice; open seeks on it are cancelled with "Siz kutayotgan mavzu
yopildi"; duels already in progress finish normally. Reopening is the same switch.

The admin **Users** list keeps its live "online" dot through the admin-only `presence:sub` channel (online user ids
to subscribed admins only, ≤ 1 diff/s) instead of the old presence list that was broadcast to every client.

## 6. Scaling and limits

* **Indexes + EXPLAIN** for the main page, lobby queries, admin list, suggestions and leaderboard: see §9. No page
  load scans `duels`; the remaining scans are bounded by the number of topics or users (admin overview counts).
* **No N+1**: admin pages fetch the page ids first, then all rows in one `IN (…)` query with the author join.
* **Counters in memory**: waiting/playing per topic, open seeks, subscribers — O(1) updates.
* **Diffs** only to subscribed clients, at most 1 per second per client; topic-change signals at most every 5 s.
* **Caps**: browse `limit` ≤ 60, `offset` ≤ 1e6, search ≤ 100 chars; lobby list 50; live topics 12; watched topics
  ≤ 60; admin page size 5–100; bulk ≤ 2,000 ids; WebSocket message ≤ **16 KB**, ≤ **120 messages / 10 s** per
  connection (else closed with code 4008).
* **Rate limits** for seek create/cancel/join: **30 / min per user** and **300 / min per IP** (`error {code:"rate"}`).
* **Single instance (stated limitation).** Seeks, duels, subscriptions and counters live in one process; the atomic
  join relies on the single event loop. Running several app instances behind a load balancer would split the
  lobby — **not supported**. A multi-instance version would move seeks/counters to Redis (atomic `SET NX` / Lua
  compare-and-set for joins, pub/sub for diffs) and pin each duel to one instance. SQLite (WAL, one writer) is also
  single-host; all writes here are short primary-key transactions.

## 7. Security

* Only the owner can cancel a seek (another user's id → `forbidden`); only admins change topic status or settings
  (REST 401/403, tested); joining or seeking on an inactive topic is refused.
* Forged ids are rejected: seek ids must match `^[0-9a-f]{16}$`, topic ids must be positive integers, bulk lists
  are validated and capped; unknown ids are ignored.
* Lobby messages contain only `{seek id, nickname, topic id, topic name, since, mine}` — no user ids, no IPs (checked
  in the E2E). Online user ids go only to admins.
* Logs written by this code contain ids, never passwords, tokens or IP addresses (duel lines log `#user_id`; admin
  actions log `admin #id`). Older admin-action logs elsewhere (role changes, blocking) still name the acting admin.
* Escaping: all user-provided text (topic names, nicknames) is inserted as DOM text nodes, never as HTML; the E2E
  creates a topic named `<img src=x onerror=…>` and checks it renders as text on the main page and in the admin list;
  the CSP forbids inline scripts.

## 8. Load test

`python3 scripts/loadtest.py` seeds (once) **5,000 topics** (4% inactive, ~28% never played, Zipf popularity, seasonal
and new topics), **20,000 users** and **one year of duels** (~1,500/day → **546,822 duels**), then starts the server on
that separate database and runs, for 90 s on one machine (4 cores):

* **500 concurrent lobby clients** over WebSocket: subscribe, seek on a topic (10% "any topic") or join one of the 8
  newest seeks (deliberate races), play the duel (5 questions, instant answers), repeat; each has its own
  `X-Forwarded-For` address so per-IP limits behave as in production;
* **25 main-page clients** browsing tabs/offsets/searches back to back, **2 admins** on the topic list,
  suggestions and log, plus the leaderboard, admin overview and the legacy all-topics endpoint at ~1 req/s each.

It verifies atomicity end-to-end: every duel has exactly 2 players, no seek is won by two joiners, the seek owner is
in the joiner's duel, and nobody is in two duels at once.

| Measure (ms) | first run p50 / p95 / p99 | **after fixes** p50 / p95 / p99 |
|---|---|---|
| Main page `GET /api/topics/browse` | 3.0 / 2,956 / 3,177 | **1.6 / 25.6 / 54.8** (280 req/s) |
| Lobby snapshot (`lobby:sub` → `lobby`) | 47.7 / 105.9 / 114.8 | **3.9 / 16.8 / 39.5** |
| Join click → `duel:start` | — | **1.6 / 27.6 / 67.2** |
| Admin topic list (sort/filter/page) | 13.8 / 3,022 / 3,178 | **2.7 / 29.9 / 53.1** (10 req/s) |
| Leaderboard (Reyting) | 2,858 / 3,122 / 3,208 | **2.5 / 27.2 / 42.2** |
| Admin overview | 2,617 / 3,206 / 3,248 | **14.9 / 30.3 / 55.9** |
| Server CPU (one core) | 86.7 % | **47.5 %**, RSS ≈ 88 MB |

Final run (finished code): **0 errors**; 3,720 join attempts → 1,077 won, 2,643 lost a race and got "taken" (expected
with deliberate contention); **0 atomicity violations over 1,777 duels**; every resolved seek was paired (time to pair
p50 0.6 s, p95 18.2 s); a new seek reached the other 499 clients in p50 397 ms / p99 995 ms (bounded by the 1 s diff
throttle). Gaps between diffs as received by a client: median 1.00 s, 1st percentile 0.93 s, minimum 0.87 s — the
server flushes at most once per second, the spread is delivery jitter on the client side. Lobby fan-out with 500
subscribers and 300 open seeks costs ~24 ms per one-second flush; the first ranking build after start-up took 40 ms. (The first run's pairing numbers are not shown: its client had a 2 s timeout that
desynchronised under the overload.)

Hotspots found and fixed: the leaderboard `GROUP BY` over all duels (2.5 s per request, blocking the event loop) →
`user_duel_stats` (0.13 ms); the activity backfill (300 s → 2.9 s); `duels(finished_at)` index for the overview
(recent duels 43 ms → 0.02 ms); the ranking rebuild now reads only the 30-day window; pairing no longer sends a
`queue: null` before `duel:start` (it made every client redraw the lobby and resubscribe for one frame per match).
The final run's raw numbers are in the JSON written with `--json`.

## 9. Query plans

`python3 scripts/loadtest.py --explain` prints `EXPLAIN QUERY PLAN` for every statement these pages run, captured from
the real code paths on the 5,000-topic database. Key lines:

```
Main page — ranking rebuild (every ≤30 s, never per request)
  SELECT topic_id, SUM(CASE …) … FROM topic_activity_daily INDEXED BY idx_activity_day WHERE day >= ? GROUP BY topic_id
    SEARCH topic_activity_daily USING COVERING INDEX idx_activity_day (day>?)
  SELECT … FROM topics WHERE active = 1 AND question_count > 0
    SEARCH topics USING INDEX idx_topics_idle (active=?)
Admin list — sort by last played / total / status / name
  SELECT t.id FROM topics t ORDER BY t.last_played_at DESC, t.name_key LIMIT 25   SCAN t USING INDEX idx_topics_played
  SELECT t.id FROM topics t ORDER BY t.total_duels DESC, t.name_key LIMIT 25      SCAN t USING INDEX idx_topics_total
  SELECT t.id FROM topics t ORDER BY t.name_key LIMIT 25                          SCAN t USING COVERING INDEX sqlite_autoindex_topics_1
  page rows: … WHERE t.id IN (…)            SEARCH t USING INTEGER PRIMARY KEY; SEARCH u USING INTEGER PRIMARY KEY
Admin list — "not played for 90+ days", suggestions, bulk ids
  … WHERE t.active = 1 AND COALESCE(t.last_played_at, t.created_at) < ?
    SEARCH t USING COVERING INDEX idx_topics_idle (active=? AND <expr><?)
Lobby — "any topic": the player's recent topics
  SEARCH duels USING INDEX idx_duels_p1 (p1_id=?)  UNION ALL  SEARCH duels USING INDEX idx_duels_p2 (p2_id=?)
Duel start — activity write
  UPDATE topics … WHERE id = ?                     SEARCH topics USING INTEGER PRIMARY KEY (rowid=?)
  UPDATE topic_activity_daily … WHERE topic_id = ? AND day = ?   SEARCH … USING PRIMARY KEY (topic_id=? AND day=?)
Leaderboard
  SCAN s USING INDEX idx_user_stats_rank; SEARCH u USING INTEGER PRIMARY KEY; USE TEMP B-TREE FOR LAST 3 TERMS OF ORDER BY
Admin overview
  SELECT COUNT(*) FROM duels WHERE finished_at >= ?   SEARCH duels USING COVERING INDEX idx_duels_finished (finished_at>?)
  … FROM duels ORDER BY finished_at DESC LIMIT 6      SCAN duels USING INDEX idx_duels_finished
```

Name search in the admin list (`LIKE '%…%'`) scans the `name_key` index (5,000 entries, < 5 ms); total-count queries
scan a covering index of `topics`.

## 10. How to run the tests

```bash
python -m pytest                      # 227 tests (activity, catalog, lobby, admin, leaderboard, existing suites)
node e2e/lobby.e2e.js                 # 59 checks: live seek → join → duel → Today ranking, race, cancel, admin, 360–1280 px
node e2e/octagon.e2e.js               # 323 checks: Octagon / Games regression
python3 scripts/loadtest.py           # load test (the first run seeds a ~100 MB database in the temp dir, ~20 s)
python3 scripts/loadtest.py --explain # query plans
```

Unit/integration tests added: `tests/test_activity.py` (8), `tests/test_catalog.py` (8), `tests/test_lobby.py`
(19, incl. a real-WebSocket simultaneous join and the presence channel), `tests/test_admin_topics.py` (4, incl. 401/403
for every endpoint), `tests/test_leaderboard_stats.py` (3). Screenshot grid (main page, catalog, waiting screen, admin
list × 360/375/768/1280 px): [screenshots/duel-lobby.jpg](screenshots/duel-lobby.jpg); full-size images are written to
`e2e/screenshots/` (`main-*.png`, `main-catalog-*.png`, `lobby-waiting-*.png`, `admin-topics-*.png`) by every E2E run.

## 11. Limitations

* **Single process** (see §6): no horizontal scaling of the lobby; SQLite single writer.
* **Staleness**: tab order/counts up to 30 s (5 s after a new duel); the live boost of the hot score uses counts
  from the last rebuild.
* **Unique players** per day are exact only for today and yesterday (older days keep the stored number; the
  backfill recomputes them exactly from history).
* The **Games/Octagon setup** pages still load the full topic list (`GET /api/topics`, ~30 ms for 5,000 topics in the
  load test); they are teacher-only and were intentionally left unchanged.
* The admin **Users** list still loads all users client-side (unchanged by this work).
* Load numbers come from one 4-core machine with the clients on the same host; production latency adds network RTT.
* The load test uses 5-question duels and instant answers to maximise pairing cycles; real duels are longer and put
  less load on pairing.
