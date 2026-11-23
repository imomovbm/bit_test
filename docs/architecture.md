# Architecture

TestDuel is one Python process: aiohttp serves the pages, the REST API and two WebSocket endpoints, with SQLite in
WAL mode for storage. Live game state lives in that process's memory. This note covers the Octagon live quiz: its
phases, message protocol, configuration, what the browser may store, capacity and observability. Other parts are
described in [scaling.md](scaling.md) (duel lobby and topic rankings) and the README.

```
 phones (/play)                       teacher (/#/games/octagon/PIN)          other users (duel, practice, admin)
      │  /ws/octagon (JSON, v2)              │  REST + /ws/octagon                     │  REST + /ws
      ▼                                      ▼                                         ▼
┌──────────────────────────── aiohttp process (app/server.py) ───────────────────────────────────────────────┐
│ assets (app/assets.py)   middlewares: metrics → HTTP cache/gzip → errors → CSRF/size guard → session      │
│ OctagonHub (app/octagon.py) ── octagon_flow.py (phases) ── octagon_scoring.py (points, ranking)           │
│ DuelHub (app/hub.py)      catalog (app/catalog.py)      ops (health, metrics, shutdown/restore)          │
│ config (app/config.py — every limit, validated at start)    observability (logs, counters, error hook)     │
└──────────────────────────────────────────┬────────────────────────────────────────────────────────────────┘
                                           ▼
                         SQLite: users, sessions (token hashes), topics, questions,
                         duels, practice and Balloon Pop results  (Octagon writes nothing during a game)
```

## Octagon phases

The server owns the state. Transitions are enforced by `app/octagon_flow.py`: a pure module where every transition is
tested, and an illegal transition raises an error rather than being silently accepted.

| Phase (wire index) | Duration | Teacher screen | Student screen | Answers |
|---|---|---|---|---|
| `lobby` (0) | until Start | PIN, QR, players with avatars, settings | own avatar and name, can change the avatar | — |
| `topic_intro` (1) | `TD_OCTAGON_INTRO`, 5 s, once | topic name, countdown, Skip | topic name, countdown | rejected (`early`) |
| `question_read` (2) | `TD_OCTAGON_READ`, 5 s | question text, countdown, "open answers now" | coloured shapes, countdown, disabled | rejected (`early`) |
| `question_active` (3) | question time (5–120 s) | question, options, answered count | shape buttons | accepted until the deadline; time measured from the start of this phase |
| `question_result` (4) | until Next | answer distribution, correct answer | correct / wrong, points, rank | late |
| `leaderboard` (5) | until Next | top 5 | own score and rank | — |
| `podium` (6) | until closed | final ranking | top 3 and own place | — |

How the phases connect:

```
lobby ─start─▶ topic_intro ─timer/skip─▶ question_read ─timer/skip─▶ question_active ─timer/all answered/skip─▶
question_result ─next─▶ leaderboard ─next─▶ question_read (next question) … or podium (last question / End)
```

- **End** from any phase goes to `podium`, counting only questions that were opened.
- **Close** removes the game.
- Repeated `next`/`skip`/`end` messages, from one window or two, carry the phase and question they refer to.
  A stale one is ignored, so actions are idempotent.

**Time.** Decisions use the server's monotonic clock: deadlines, "too late" and points. Clients receive each phase's
start and end as Unix milliseconds (`ps`/`pe`, `phaseStart`/`phaseEnd`). They measure the clock offset once per
connection (`sync`, keeping the sample with the lowest round trip) and use it only to draw countdowns.

**Scoring** (`app/octagon_scoring.py`, unchanged from v1):

- A correct answer within 0.5 s scores 1000. Otherwise it scores `round((1 − t/T / 2) × 1000)`, computed with exact
  fractions and rounded once.
- A wrong answer or no answer scores 0.
- Ties are broken by lower total answer time, then by name.

## Protocol

Messages are JSON objects `{"t": type, "d": data}` on `/ws/octagon`: 4 KB maximum, 60 messages per 10 s.

**Versioning.** The handshake messages `check`, `join`, `resume` and `host` must carry `v: 2`.

- On a mismatch the server answers `reload {v}` and the page shows "the site was updated — reload".
- A version-less (v1) page also gets an error in the old format that it can display.
- Unknown message types get a harmless `e {c: "bad"}` and change nothing.
- REST responses carry `X-Release`. The main app shows a reload banner when it differs from the release it was
  loaded with.

| Client → server | Fields | Notes |
|---|---|---|
| `check` | `v, pin` | Does the PIN exist and accept joins? Wrong PINs are rate-limited per IP and globally |
| `join` | `v, pin, nick, av` | `av` is the avatar index into the fixed list of 30 (`AVATARS`); anything else is rejected |
| `resume` | `v, pin, id, tok` | Reconnect. The token is compared by hash. A second tab with the same token takes over (the old one is closed with 4001) |
| `av` | `i` | Change avatar, in the lobby only |
| `a` | `q, o` | Answer: question index and option index. Every other field is ignored |
| `sync` | `c` | Client clock sample; the reply is `{c, s: server Unix ms}` |
| `ping` | — | Keep-alive |
| `host` | `v, pin` | Teacher screen; requires the owner's session, re-checked against the database on every action |
| `start`, `next`, `skip`, `end`, `kick {id}`, `lock {locked}`, `settings {…}`, `close` | `phase, q` (stale check) | Teacher actions |

| Server → client | Fields |
|---|---|
| `w` (welcome) | `v, pin, id, nick, av, tn` (topic name), `n` (question count), `tok` (only in the first welcome after joining) |
| `s` (student state) | `p` (phase index), `q`, `o` (option count), `ps`/`pe` (phase start/end, Unix ms), `a` (own answer), `sc` (score), plus `k`/`pl` (rank/players, result, leaderboard and podium only), `res {ok, pts, co}` (after the question closes), `top` (`[nick, score, av]` ×3, podium only). Never question text, option text or the correct answer before the reveal |
| `h` (teacher state) | `v, pin, phase, index, total, timeLimit, settings, playerCount, connectedCount, locked, phaseStart/phaseEnd`, plus per phase: `players`, `question`, `answered`, `counts`, `leaderboard`, `ranking`. `qr, joinUrl, joinBase, topicName, createdAt` are sent once per connection (`HOST_STATIC`) |
| `e` | `c` (code: `pin`, `rate`, `nick`, `taken`, `full`, `locked`, `avatar`, `early`, `late`, `gone`, `started`, `bad`, …), `m` (Uzbek text), `status` |
| `k` | `r`: `kicked` / `ended` / `replaced` |
| `reload` | `v`: the server's protocol version |
| `sync` | `c, s` |

WebSocket close codes:

| Code | Meaning | Client reaction |
|---|---|---|
| 4001 | Opened in another window | Shows a message, does not reconnect |
| 4002 | Removed by the teacher | Shows a message, does not reconnect |
| 4003 | Game closed | Shows a message, does not reconnect |
| 4008 | Flood limit | Reconnects |
| 4401 | Teacher session ended | Reconnects |
| 1012 | Server restarting; the game was saved | Shows "server is updating", reconnects |
| 1001 | Server stopping | Reconnects |

## Configuration

Every timing, limit and threshold is defined in `app/config.py`, with an environment override, a type, an allowed
range and a description. The full table is in the README. Startup refuses invalid values and contradictory
combinations, and lists every problem at once. Examples of rejected combinations:

- a join limit lower than the player cap;
- a default question time outside its min/max.

`python run.py --check-config` prints the effective values with secrets masked. Product rules that the client code
depends on stay as constants in `app/octagon.py`: 4 answer shapes, 20-character names, protocol version 2.

## What the browser may store

See [performance.md](performance.md#what-may-be-stored-on-the-users-device) for the full table. In short:

- Static assets.
- The per-game reconnect token: scoped to the PIN, deleted when the game ends or after 12 h.
- Last nickname and avatar; UI settings.
- The in-progress practice session, deleted on logout.

Nothing stored is trusted; tamper tests prove that changing it alters nothing (`tests/test_tamper.py`).

## Capacity

Octagon runs on **one instance**. Game state and fan-out live in this process's memory, and Railway is configured
with `numReplicas: 1`. Running several instances would need sticky routing by PIN plus shared state (e.g. Redis)
for reconnects and teacher screens. That is not implemented.

Measured on one instance with `scripts/octagon_load.py`: 20 games at once (one with 300 players, 870 players in
total), 5 questions, 10 % of players reconnecting during each question.

| Metric | Value |
|---|---|
| Server CPU | about 9 % of one core over the whole run |
| Peak RSS | 93 MB |
| Broadcast p95, 300-player game | 28 ms (median of 5 runs; 26–44 ms) |
| Answer acknowledgement p95 | 1.4 ms |
| API p95 | 3 ms |
| Errors | 0 (in all 5 runs) |

CPU scales roughly linearly with the number of connected players, so one core would carry several thousand. The
default limits stop well before that:

- 5,000 open Octagon sockets in total (`TD_OCTAGON_MAX_SOCKETS`);
- 300 players per game;
- 500 games in total;
- 5 running games per teacher.

Raise them deliberately and watch `octagon_handle_ms` and `octagon_broadcast_ms` p95 on `/metrics`.

**Restarts.** On SIGTERM the running games are written next to the database and restored by the next process,
together with their timers. The downtime counts as a pause. Clients reconnect by themselves. See
[runbook.md](runbook.md).

## Observability

| Source | What it gives |
|---|---|
| `/healthz` | Status, release and uptime; returns 503 while draining or if the database fails |
| `/metrics` (Prometheus) and `/api/admin/metrics` (JSON) | Gauges (games, running games, players, connected players, sockets, duels, users online), counters (HTTP requests by area and status, WebSocket messages in by type and out, games created/finished, joins, answers, errors by kind), latency p50/p95/p99 over 5 minutes (`http_api_ms`, `octagon_handle_ms`, `octagon_broadcast_ms`) |
| Logs (`TD_LOG_FORMAT=json` for one JSON object per line) | Identifiers and counts only. No nicknames, logins, tokens, IP addresses or question text, and the access log is off |
| Error hook | Every unexpected error (HTTP handler, WebSocket message, timer, event loop, restore, browser) is counted and logged with context. Optionally it is POSTed to `TD_ERROR_WEBHOOK`, at most once per 30 s per kind |

## Security

The protections from the first audit ([octagon-audit.md](octagon-audit.md)) are unchanged:

- role checks on every request and teacher action;
- CSRF and origin checks on writes and WebSockets;
- CSP and security headers;
- rate limits;
- text-only rendering of user data.

The v2 changes are covered by [octagon-v2-audit.md](octagon-v2-audit.md):

- versioned protocol;
- avatar allowlist sent as an index only;
- no personal data in logs;
- immutable assets kept separate from `private, no-store` API responses;
- the restart file is readable by the owner only, holds token hashes rather than tokens, and is deleted after use.

The dependency audit (`pip-audit`) runs in CI. The minimum aiohttp version is pinned to the first release with no
known advisories.
