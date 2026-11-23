# Performance, caching and device storage

How fast the app is on cheap phones and slow mobile networks, how it behaves under classroom load, what the server
caches and what may be stored on the user's device.

## How it was measured

- **Pages:** `node scripts/perf-routes.js [--json out.json] [--runs 5] [--route teacher]`, using Playwright/Chromium.
  - Lighthouse "Slow 4G" network: 150 ms RTT, 1.6 Mbit/s down, 750 kbit/s up.
  - 4× CPU slowdown (a mid-range phone), 390×800 mobile viewport.
  - Median of 5 runs.
  - **Usable** is the later of two moments: the first animation frame in which the page's main input or button is
    visible, measured inside the page, and the first contentful paint. Playwright's own wait re-checks at intervals of
    up to 500 ms, which made a single number jump by half a second between runs. That was the cause of an apparent
    0.4 s "regression" on the teacher screen, tracked down with request and WebSocket timelines.
  - **Repeat** is a second full navigation in the same browser profile.
- **Load:** `python3 scripts/octagon_load.py [--json out.json]`.
  - 20 games at once: one with 300 players and 19 with 30, for 870 players. All join within 3 s.
  - 5 questions; 10 % of players drop and reconnect during each question.
  - Real WebSockets with one `X-Forwarded-For` address per phone.
  - Server CPU and RSS are read from `/proc`.
  - Final numbers are medians of 5 runs.
- **Baseline:** the pre-v2 code (commit `7e0adf5`).
  - Pages: re-measured with the same script and method as the final numbers.
  - Load: one run with the v1 protocol (`--v1`).

## Targets (spec §3)

| Target | Result | Met |
|---|---|---|
| Student route ≤ 100 KB gzipped JS on first load | **15.1 KB** (`play.js`, `octagon/common.js`, `report.js`; 13.8 KB before the rank-change and podium release) | yes |
| Student route usable in < 3 s on slow 4G, mid-range phone | **0.59 s** `/play`, **0.61 s** `/play/PIN` | yes |
| Student route < 1 s on repeat visits | **0.43–0.46 s** (one network request: the 300-byte HTML revalidation) | yes |
| API p95 < 200 ms | **3.0 ms** during the load test (median of 5 runs) | yes |
| WebSocket action → broadcast p95 < 150 ms, 300 players in one game | **28 ms** (median of 5 runs; 26–44 ms) | yes |

## Pages: before → after (slow 4G, 4× CPU, median of 5)

| Route | JS gzip | Usable (cold) | First paint | Usable (repeat) | Bytes (cold → repeat) | Repeat: requests on the network |
|---|---|---|---|---|---|---|
| Student `/play` | 9.6 → 13.8 KB¹ | 854 → **585 ms** | 608 → 504 ms | 625 → **432 ms** | 49.6 → **22.8 KB**; 1.5 → 0.3 KB | 5 → **1** |
| Student `/play/PIN` | 9.6 → 13.8 KB¹ | 1030 → **606 ms** | 600 → 508 ms | 802 → **455 ms** | 49.6 → **22.8 KB**; 1.5 → 0.3 KB | 5 → **1** |
| Login `/` | 41.2 → 42.9 KB | 2416 → **1228 ms** | 2416 → 1228 ms | 1228 → **848 ms** | 260 → **75 KB**; 4.5 → 1.0 KB | 15 → **3** |
| Teacher game screen | 53.6 → 57.3 KB | 2976 → **1708 ms** | 2288 → 1080 ms | 1592 → **970 ms** | 298 → **90 KB**; 4.8 → 0.7 KB | 16 → **2** |

¹ The JS size column is the gzip size of the files. That is what goes over the wire now; before, nothing was compressed
in transit. The student code grew because of the v2 features: topic intro, reading phase, avatars, clock sync and the
0.5 KB browser error reporter.

**After the rank-change and podium release** ([octagon-rank-podium.md](octagon-rank-podium.md)), same method, median of 5:

| Route | JS gzip | CSS gzip | Usable (cold) | Usable (repeat) |
|---|---|---|---|---|
| Student `/play` | 15.1 KB (+1.3) | 8.1 KB (+1.3) | 565 ms | 366 ms |
| Student `/play/PIN` | 15.1 KB (+1.3) | 8.1 KB (+1.3) | 610 ms | 393 ms |
| Login `/` | 42.9 KB | 29.4 KB | 1236 ms | 764 ms |
| Teacher game screen | 60.8 KB (+3.5) | 29.4 KB | 1707 ms | 968 ms |

The new screens use CSS animations and the Web Animations API, with no library.

Before that release, CSS was 6.8 KB gzipped on the student page and 26.9 KB in the main app. Layout shift (CLS) is 0 on the student pages
(worst of 5 runs) and 0.002 on the teacher screen. The baseline showed 0.042 on the student pages in its worst run.

## Realtime and backend: before → after (load test)

| Metric | Before (v1, 1 run) | After (median of 5 runs) |
|---|---|---|
| Broadcast p95, 300-player game / 30-player games | 24.1 / 3.4 ms | 28.2 / 3.6 ms (300-player range 26–44 ms) |
| Answer acknowledgement p95 | 1.4 ms | 1.4 ms |
| Join p95 / reconnect p95 | 1.5 / 1.3 ms | 1.5 / 1.4 ms |
| API p95 | 3.0 ms | 3.0 ms |
| Student state message, average | 99 B | 85 B |
| Teacher-screen traffic, all 20 games | 5.4 MB | **1.0 MB** (−82 %) |
| Teacher-screen traffic, 300-player game | 449 KB in 85 messages | **100 KB in 38 messages** |
| Server CPU (one core) / peak RSS | 13 % / 90.7 MB | 9 % / 93 MB |
| Errors / server tracebacks | 0 / 0 | 0 / 0 (in all 5 runs) |

- The teacher-traffic comparison is the same script run against the code just before and just after the change.
- The after column includes the per-message metrics counters added for `/metrics`.
- Broadcast latency in the 300-player game varies by about ±10 ms between runs on the same code, and stays far below
  the target.
- One early run showed a game stalling: the load script sent a teacher action before its own copy of the teacher state
  had caught up. The server correctly ignores a stale action (double-click protection). The script now waits for the
  teacher screen's state first.

## What was done

1. **Static files** ([app/assets.py](../app/assets.py)).
   - All JS, CSS and the SVG logo are read once at startup and served from memory, with gzip level 9 precomputed.
     This uses the standard library only.
   - Pages refer to `/assets/<release>/…`, where `<release>` is a hash of every static file. These URLs are
     `public, max-age=31536000, immutable`, so repeat visits don't even revalidate them.
   - Any change to any file creates a new release, so old and new code never mix.
   - The HTML shell is `no-cache` with an ETag, so a deployment is live on the next page load.
   - Old URLs (`/js/…`, `/css/…`, `/img/…`) still work, with `no-cache`, for pages opened before a deployment.
   - `TD_DEV=1` serves straight from disk with no caching, for development.
2. **No request waterfall.**
   - Each page gets a `<link rel="modulepreload">` for every module its entry script imports statically. The
     student page fetches `play.js` and `common.js` in parallel; the main app fetches its 9 modules in parallel.
   - Views loaded on demand (admin, Octagon teacher screen, Balloon Pop) stay out of the first load. The Games
     panel prefetches the Octagon teacher module while the browser is idle.
3. **Faster join link.** `/play/PIN` shows the nickname form at once and checks the PIN in the background. The
   join checks the PIN again on the server, and an invalid or ended game sends the student back to the PIN screen
   with the error. This saves a round trip before the page is usable.
4. **API responses** ([app/server.py](../app/server.py), `http_cache_middleware`).
   - The default is `private, no-store`.
   - Four read-only lists are the same for every user and contain nothing personal: `/api/topics`,
     `/api/topics/browse`, `/api/octagon/topics` and `/api/stats/leaderboard`. These get `private, no-cache`
     plus an ETag, so an unchanged list costs a 304 with no body.
   - No `max-age` or `stale-while-revalidate` is used: the lists carry live counts and must reflect an admin's
     edits immediately.
   - JSON over 1 KB is gzipped.
5. **Realtime payloads** ([app/octagon.py](../app/octagon.py)).
   - Student messages carry only what that screen needs: phase index, question index, option count, server times,
     own answer, score and rank.
   - The QR code (about 3 KB), the join link and the topic name go to a teacher screen once per connection; later
     updates leave them out.
   - In games with more than 40 players, teacher-screen updates (lobby list, answered count) are throttled to at
     most one per second. Smaller classes keep 4 per second. Phase changes are always sent at once.
   - WebSocket messages are compressed with permessage-deflate: on by default in aiohttp, and negotiated by every
     current browser.
6. **Backend.**
   - A game's questions are read once, when the game is created. During a game the only database access is a
     primary-key lookup per teacher action, which re-checks the role. Nothing is written per answer, and results
     are kept in memory only.
   - Query plans for the Octagon queries use indexes. `long_option_counts` on a bank of 60,000 questions takes
     6.7 ms per teacher setup-page load, so it is not cached.
   - SQLite uses one WAL connection per process: queries take well under a millisecond and the event loop is
     single-threaded, so a connection pool would add nothing.

## Cache headers

| Response | `Cache-Control` | Validator |
|---|---|---|
| `/assets/<current release>/…` (JS, CSS, SVG) | `public, max-age=31536000, immutable` | ETag |
| `/assets/<other release>/…`, `/js/…`, `/css/…`, `/img/…` | `no-cache` | ETag → 304 |
| HTML: `/`, `/play`, `/play/PIN` | `no-cache` | ETag → 304 |
| `/api/topics`, `/api/topics/browse`, `/api/octagon/topics`, `/api/stats/leaderboard` | `private, no-cache` | ETag → 304 |
| Every other `/api/…` response, including errors and login/logout | `private, no-store` | — |
| `/d/CODE` (invite page) | `no-store` | — |

All of this is covered by `tests/test_http_cache.py`, including path traversal attempts against the asset routes.

## Not done, and why

- **Brotli.** It would need a third-party package (`brotli`), and dependencies are only added when needed. The app
  serves gzip-9. A CDN in front (below) adds Brotli by itself.
- **HTTP/2 and HTTP/3.** aiohttp speaks HTTP/1.1. TLS and HTTP/2/3 belong at the proxy or CDN (Railway's edge,
  Cloudflare, nginx). After the changes above a repeat visit makes one request, so multiplexing matters little.
- **Service worker.** Skipped on purpose. With immutable assets, a repeat visit already costs a single ~300-byte
  revalidation (0.45 s on slow 4G). The game needs the network anyway. A worker would add a real risk of a stale
  app shell after a deployment, plus update prompts and cache clean-up code, for no measurable gain.
- **Images and fonts.** There is nothing to convert: icons and answer shapes are inline SVG, the only image is
  the SVG logo, and the UI uses system fonts.
- **Diffs for the teacher lobby list.** After throttling and leaving out the static fields, the 300-player lobby
  costs about 1 update/s of 20 KB, about 4.5 KB after deflate, sent to one or two teacher screens. A diff protocol
  isn't worth the complexity.

## Adding a CDN

Put any CDN (e.g. Cloudflare) in front of the app with WebSockets enabled. The headers above already tell it what
to do: cache `/assets/*` at the edge for a year, and pass HTML and `/api/*` through. HTML is revalidated, and the
API is `private`, so a shared cache never stores it. Recommended rules:

1. "Cache everything" for `/assets/*`.
2. "Bypass cache" for `/api/*`, `/ws` and `/ws/octagon`.
3. Respect the origin headers everywhere else.
4. Brotli and HTTP/3 on.
5. Set `TD_TRUST_PROXY=1` (automatic on Railway) so client IPs and HTTPS are taken from `X-Forwarded-*`.

## What may be stored on the user's device

The server decides and re-checks everything. Nothing below is trusted for scores, answers, timers, roles, game
state or correct answers.

| Where | Key | Content | Lifetime | Why it is allowed |
|---|---|---|---|---|
| `localStorage` (student page) | `oct:<PIN>` | `{v: 2, id, tok, nick, av, at}`: the reconnect record for that one game | Deleted when the game ends, when the student is removed, or after 12 h | The per-game reconnect token, scoped to the PIN. The server accepts it only together with the matching player id in that running game |
| cookie `oct_<PIN>` (`path=/play`, `SameSite=Strict`, `Secure` on HTTPS) | | The same record, only when `localStorage` is unavailable (private mode on old browsers) | 12 h | Fallback for the above |
| `localStorage` (student page) | `oct:last` | `{v: 2, nick, av}`: last nickname and avatar, to prefill the form | Until replaced | Convenience, not secret |
| `localStorage` (main app) | `td-theme`, `td-sound`, `td-octagon-sound`, `td-topic-tab`, `td-practice-tab`, `td-octagon-setup`, `td-balloon-setup` | UI settings and the last game-setup choices (form prefill) | Until changed | Not personal. Each value is checked before use (unknown or invalid values fall back to the defaults), and the server validates every game setting when a game is created |
| `sessionStorage` (main app) | `td-practice` | The practice session in progress (questions and the user's own answers) | The tab; **deleted on logout or session expiry**; ignored if a different user logs in | Self-study mode. Practice results are self-reported by design and appear only on the user's own stats and to admins. They never affect duel ratings, leaderboards or Octagon |
| `sessionStorage` (main app) | `td-invite` | A duel invite code from the URL, to continue after login | The tab | Not personal |
| cookie `td_sid` | | The session token | 30 days | `HttpOnly`, `SameSite=Lax`, `Secure` on HTTPS; the database stores only its hash |

Rules that hold across the app:

- Stored records are versioned (`v: 2`). A record in an older format is ignored and deleted, never misread.
- No secrets other than the student's own per-game token, no tokens of other users and no personal data are stored.
  API responses with user data are `no-store`, so nothing user-specific stays in the HTTP cache after logout.

Tamper tests prove that changed storage changes nothing:

- `tests/test_tamper.py`
  - A forged reconnect record carrying a score, name, avatar or role.
  - Another player's token.
  - Fake client time in clock sync and in answers.
- `tests/test_octagon_security.py::test_roles_cannot_be_self_assigned` and `test_player_socket_cannot_send_host_messages`.
- `tests/test_octagon.py::test_forged_answer_fields_are_ignored`.
- The browser E2E, which edits `localStorage` and the clock in a real page.
