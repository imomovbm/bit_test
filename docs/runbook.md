# Runbook

How to deploy, roll back and check TestDuel, and what to do when something goes wrong. The architecture is in
[architecture.md](architecture.md) and every setting is in the README table. In short: one process, one SQLite
database. Octagon games live in memory and are saved to disk when the process stops.

## Deploy

1. **CI is green.** It runs:
   - lint, mypy and the tests;
   - `--check-config`;
   - the bundle budget;
   - `pip-audit`;
   - the browser E2E.
2. **Back up the database and test the migration on the copy.** Do this for every release that touches the schema,
   and it is cheap enough to do every time:

   ```bash
   python3 scripts/db_tool.py backup /data/testduel.db /data/backups/testduel-$(date +%F-%H%M).db
   python3 scripts/db_tool.py check  /data/backups/testduel-<that file>.db   # runs the new migrations on the COPY
   ```

   `check` must end with `integrity_check: ok; foreign_key_check: 0`. The v2 release has no schema changes.
3. **Check the new settings:** `python run.py --check-config`. Exit code 2 means a value is invalid, and the server
   would refuse to start with it.
4. **Deploy.**
   - Railway: push to the deployed branch. `railway.json` starts `python run.py`, checks `/healthz` and keeps one
     replica.
   - Plain server: `systemctl restart testduel` (or equivalent) behind nginx. See the README for the WebSocket
     proxy settings.

### What happens during a deploy

1. The old process gets SIGTERM. It stops accepting new Octagon games (503 "server is updating").
2. It writes every running game to `<database>.octagon.json`: mode 0600, next to the database, so on Railway it sits
   on the volume.
3. It closes the Octagon screens with code 1012 ("server is updating — the game continues") and exits.
4. The new process starts. It restores the games if the file is younger than `TD_OCTAGON_RESTORE_MAX_AGE` (10 min),
   then deletes the file. The log says `Octagon: N ta o'yin tiklandi (server X s to'xtab turdi)`.
5. Phones and teacher screens reconnect by themselves: retries back off from 0.4 s to 5 s, forever. They continue in
   the same phase with the same score and avatar.
6. The time the server was down is a **pause**: a question that had 17 s left still has 17 s.

Duels in progress are not saved; their players see "server stopped". Balloon Pop games are stored in the database
and survive.

The restart relies on the old process stopping before the new one starts. That is how Railway handles a service
with a volume. With overlapping (zero-downtime) deploys, the new process would start before the file is written and
the games would be lost. Don't use overlapping deploys for this app.

## Roll back

1. Redeploy the previous release: Railway → Deployments → *Redeploy* on the previous one, or `git checkout` the
   previous tag and restart.
2. **Database:** releases only add columns and indexes (see `MIGRATIONS` in `app/db.py`), so the previous release
   runs on the newer database. Restore a backup only if a release explicitly says it changed data:
   1. stop the server;
   2. `cp /data/backups/<file>.db /data/testduel.db`;
   3. delete `/data/testduel.db-wal` and `-shm` if present;
   4. start the server.
3. **Running Octagon games** survive a rollback the same way as a deploy, as long as the snapshot format
   (`SNAPSHOT_VERSION`) is the same. If it differs, they are dropped and teachers start new games.
4. **Pages left open** on another version get "the site was updated — reload": the protocol version for Octagon,
   the `X-Release` banner for the main app.

## Logs

The default format is text. Use `TD_LOG_FORMAT=json` for one JSON object per line, with the fields `ts, level,
logger, msg, kind, …`.

**Never logged:** student nicknames, logins, tokens, passwords, IP addresses, question or answer text, and request
URLs (the access log is off). Players and teachers appear as ids and PINs. A test enforces this
(`tests/test_observability.py`).

| Logger | Typical lines |
|---|---|
| `testduel.octagon` | `Octagon 482913 yaratildi: mavzu #12, 10 savol, 20 s, o'qituvchi #7` · `… yakunlandi: 28 o'yinchi, 10 savol o'ynaldi` · `… yopildi (closed/expired)` · `N ta o'yin tiklandi` |
| `testduel.errors` | `kind: message` with `kind` = `http` (with the route pattern), `octagon_ws`, `octagon_timer`, `octagon_sweep`, `octagon_restore`, `duel`, `duel_ws`, `loop`, `shutdown`, `health`, `client` (browser) |
| `testduel` / `testduel.api` | Startup, admin actions (by user id), topic changes |

Every `testduel.errors` line also increments `errors_total{kind=…}` and, if `TD_ERROR_WEBHOOK` is set, is POSTed
there at most once per 30 s per kind. The payload is `{kind, message, fields, release, text}`, so it fits
Slack/Discord-style webhooks.

## Metrics and health

- `GET /healthz` returns 200 `{"status":"ok","release":…,"uptimeS":…}`. It returns 503 with `draining` while
  stopping, or `db_error` if the database fails.
- `GET /metrics` returns Prometheus text and needs `Authorization: Bearer $TD_METRICS_TOKEN`; without a token it is
  closed.
- `GET /api/admin/metrics` returns the same as JSON for a logged-in admin.

| Metric | Meaning | Suggested alert |
|---|---|---|
| `testduel_octagon_games`, `_games_running`, `_players`, `_players_connected` | Current load | — (watch the trend) |
| `testduel_octagon_sockets`, `testduel_ws_open` | Open connections | > 80 % of `TD_OCTAGON_MAX_SOCKETS` |
| `testduel_errors_total{kind}` | Unexpected errors | Any increase of `http`, `octagon_*`, `loop`; a spike in `client` |
| `testduel_latency_ms{metric="http_api_ms",quantile="0.95"}` | API p95, last 5 min | > 200 ms |
| `testduel_latency_ms{metric="octagon_handle_ms",quantile="0.95"}` | Time to handle one game message | > 20 ms |
| `testduel_latency_ms{metric="octagon_broadcast_ms",quantile="0.95"}` | Time to prepare a phase change for all players of a game | > 50 ms |
| `testduel_http_requests_total{area,status}` | Requests by page/asset/api and 2xx/4xx/5xx | 5xx rate |
| `testduel_ws_in_total{t}`, `testduel_ws_out_total{ws}` | Messages per type (use `rate()` for messages/s) | — |
| `testduel_octagon_joins_total`, `_answers_total`, `_games_created_total`, `_games_finished_total` | Activity | — |

## Incidents

**The server restarted in the middle of a game.**

- After a normal stop (deploy, `systemctl restart`, Ctrl+C) the games come back by themselves. Check the log for
  `N ta o'yin tiklandi`. If a teacher's screen shows "reconnecting" for more than ~10 s, ask them to reload the
  page: the game is still there.
- After a crash or SIGKILL (out of memory, power loss) nothing was saved. Students see "your place was not found"
  and the teacher sees "game not found", then starts a new game, usually from the next question's topic. Look for
  the cause in the logs and `errors_total`.

**Students can't join ("too many attempts from this network").** A whole school sits behind one NAT address. The
limits are:

| Limit | Default | Setting |
|---|---|---|
| Wrong PINs per IP | 60 per 5 min | `TD_OCTAGON_FAIL_LIMIT` |
| New players per IP | 1000 per 10 min | `TD_OCTAGON_JOIN_LIMIT` |
| Open connections per IP | 500 | `TD_OCTAGON_MAX_SOCKETS_PER_IP` |

Raise the relevant one and restart; the games are kept. If many classes share one address, raise
`TD_OCTAGON_MAX_SOCKETS_PER_IP` above students × classes.

**PIN guessing.** Above 300 wrong PINs per minute across all IPs, every IP gets 5 attempts. Look for a spike in
`testduel_ws_in_total{t="check"}`. Legitimate classes keep working because their students type the right PIN. If it
persists, block the source at the proxy or CDN.

**Slow or high CPU.**

1. Check `octagon_broadcast_ms` and `octagon_handle_ms` p95 and `octagon_players_connected`.
2. Compare with the capacity numbers in [architecture.md](architecture.md#capacity).
3. Lower `TD_OCTAGON_MAX_PLAYERS` / `TD_OCTAGON_MAX_GAMES` to protect the instance, or give it a faster CPU.
   Scaling out is not supported.

**Errors in the log.**

- `errors_total{kind="client"}` comes from browsers. Look at `page`, `src` and `line`. After a deploy, old pages may
  report errors until they reload.
- `kind="http"` names the route pattern; reproduce it with the same request.
- `kind="octagon_timer"` / `"octagon_ws"` means a game-engine bug; the game keeps running. File it with the log line.

**Disk full / database locked.**

- `/healthz` returns `db_error`.
- Free space: old backups, logs.
- SQLite waits up to 5 s for locks (`busy_timeout`).
- Run `scripts/db_tool.py check` on a copy if you suspect corruption.

## Backups

- `scripts/db_tool.py backup SRC DST` uses SQLite's online backup API. It is consistent while the server runs and
  doesn't block writes. Backups are created with mode 0600 and never overwrite an existing file.
- Suggested schedule: daily, keep 14 days, plus one before each deploy. For example, in cron:
  `python3 scripts/db_tool.py backup /data/testduel.db /data/backups/testduel-$(date +\%F).db`.
- Restore: see *Roll back* above. Test restores now and then with `db_tool.py check` on the backup.
- The database holds only what the app needs:
  - accounts (scrypt password hashes);
  - session-token hashes;
  - topics and questions;
  - duel results;
  - practice summaries (totals, no per-answer log);
  - Balloon Pop games.
- Octagon stores nothing per answer. Its results live in memory until the game is closed or expires
  (`TD_OCTAGON_TTL`).

## Configuration changes

1. Set the environment variable (Railway → Variables).
2. Run `python run.py --check-config` locally with the same value if unsure.
3. Restart or redeploy. Running Octagon games are kept.

An invalid value stops the server at startup, with the list of problems in the log. Fix the value and start again.
