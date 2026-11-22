# Octagon — security & consistency audit

Scope: everything added or changed for the Teacher role, the Games panel and Octagon (`app/octagon.py`, `app/qr.py`,
`app/roles.py`, the Octagon parts of `app/api.py`, `app/ws.py`, `app/server.py`, `app/db.py`, `static/play.html`,
`static/js/play.js`, `static/js/octagon/common.js`, `static/js/views/games.js`, `static/js/views/octagon.js`, the
related CSS and the tests). Baseline: commit `acb5660`.

Method: read the code as an attacker, then **for every suspected issue a test or reproduction was written first and
run against the unchanged code** (it failed), then the fix was made and the test passed. Tests for areas that turned
out to be safe were kept as regression tests too. Line links point to the code as of this report.

**Result:** 14 findings — 0 critical, 0 high, 3 medium, 11 low. All 14 are fixed and covered by tests. Accepted
residual risks are listed at the end; nothing found was left unfixed.

Test suites after the fixes: `python -m pytest` — **169 passed** (130 before the audit); `node e2e/octagon.e2e.js` —
**150 browser checks passed**, no console errors (any console error, including a CSP violation, fails the run).

---

## A1. Spec consistency (`octagon-spec.md`)

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1.1 | Teacher role extends the existing role system, with a migration | PASS | `users.is_teacher` column added through the existing `MIGRATIONS` list [app/db.py:120](../app/db.py#L120); `is_teacher()` [app/roles.py:22](../app/roles.py#L22); `tests/test_octagon_api.py::test_roles_and_permissions` |
| 1.2 | Admins can assign/remove the role in the existing user-management UI | PARTIAL (by design) | Only the **owner** (bosh administrator) can assign/remove it: [app/api.py:1121](../app/api.py#L1121), UI [static/js/views/admin.js:1239](../static/js/views/admin.js#L1239). Regular admins cannot, because user management was made owner-only earlier at your request. Allowing all admins is a one-line change (`require_superadmin` → `require_admin` for this field). Test: `test_roles_and_permissions` (admin → 403, owner → 200) |
| 1.3 | Admins have teacher permissions | PASS | `is_teacher()` is true for admins; `test_roles_and_permissions` (a non-owner admin creates, starts and ends a game) |
| 1.4 | Only teachers/admins create and start games (Octagon and Balloon Pop) | PASS | `require_teacher` [app/api.py:128](../app/api.py#L128) on every `/api/octagon/*` and `/api/balloon/*` endpoint (e.g. [app/api.py:454](../app/api.py#L454)); WebSocket host actions re-check the role in the database on every action; `test_roles_and_permissions`, `tests/test_octagon_security.py::test_player_socket_cannot_send_host_messages` |
| 1.5 | Games panel hidden for regular users, 403 server-side, direct URLs redirect | PASS | Route flag [static/js/app.js:56](../static/js/app.js#L56) and [static/js/app.js:151](../static/js/app.js#L151); E2E §1 (5 direct URLs redirect to `#/duel`); REST 403 / WebSocket 403 tests above |
| 1.6 | Duel and Oʻrganish stay unchanged | PASS | E2E §1; browser regression scripts for duel and practice (see Phase C) |
| 1.7 | Public join page (no login, not in the menu) | PASS | `/play`, `/play/{pin}` served without a session; `test_roles_and_permissions` (guest loads `/play`, main app bundle not loaded) |
| 2.1 | Games panel in the main navigation for teachers/admins | PASS | [static/js/views/games.js:26](../static/js/views/games.js#L26); E2E §0–1 (menu appears/disappears live when the role changes) |
| 2.2 | Balloon Pop moved into it and works as before | PASS | `#/games/balloon`, old `#/balloon` links redirect; `tests/test_balloon.py`; Balloon Pop browser regression scripts |
| 2.3 | Game cards for Balloon Pop and Octagon | PASS | `games.js`; E2E screenshots `games-*.png` |
| 3.1 | Game name in one constant | PASS | `GAME_NAME` [static/js/octagon/common.js:5](../static/js/octagon/common.js#L5) (all UI text uses it; internal names such as `/api/octagon` stay) |
| 3.2 | Topic selection from existing topics | PASS | [app/api.py:550](../app/api.py#L550) (active topics with questions) |
| 3.3 | Time per question: presets 10/20/30/60, custom 5–120, default 20, validated server-side, locked after start | PASS | [app/octagon.py:195](../app/octagon.py#L195), [app/octagon.py:578](../app/octagon.py#L578); `test_clean_settings_validation`, `test_settings_locked_after_start`, `test_configured_timer_is_used`; E2E §3 (custom 7 s used, 200 s rejected) |
| 3.4 | Optional shuffle of questions/answers | PASS | [app/octagon.py:215](../app/octagon.py#L215) |
| 3.5 | 6-digit PIN, unique among active games | PASS | [app/octagon.py:381](../app/octagon.py#L381) (`secrets.randbelow`, checked against running games); `test_pins_are_unique_six_digits` |
| 3.6 | QR code deep-linking to the join page with the PIN | PASS | [app/qr.py:328](../app/qr.py#L328) (own encoder, `tests/test_qr.py`); E2E §3 decodes the QR from a screenshot and follows it |
| 3.7 | Live player list with connected status and count | PASS | `host_state()` [app/octagon.py:817](../app/octagon.py#L817); E2E §4–5 |
| 3.8 | Start button; the quiz never starts by itself | PASS | [app/octagon.py:468](../app/octagon.py#L468); `test_game_waits_in_lobby_until_teacher_starts`; E2E §5 |
| 3.9 | Question → results → top 5 → next → podium; end early | PASS | `_next`, [app/octagon.py:538](../app/octagon.py#L538); `test_full_game_scores_ranks_and_podium`, `test_end_early_and_cancel_in_lobby` |
| 3.10 | PIN always visible at the top (teacher and student) | PASS | [static/js/views/octagon.js:462](../static/js/views/octagon.js#L462), [static/js/play.js:479](../static/js/play.js#L479); E2E checks the PIN in every phase |
| 3.11 | Teacher screen shows question and answer texts with colour and shape | PASS | [static/js/views/octagon.js:633](../static/js/views/octagon.js#L633) |
| 3.12 | Students join by QR or PIN, then only a nickname | PASS | E2E §4 |
| 3.13 | Nickname: trim, 1–20 chars, unique, profanity/HTML sanitising | PASS | [app/octagon.py:145](../app/octagon.py#L145), [app/octagon.py:643](../app/octagon.py#L643); `test_clean_nickname`, `test_bad_nicknames_rejected`, `test_duplicate_nickname_rejected_even_for_disconnected_player`; E2E §17 |
| 3.14 | Late join at any time, 0 points, on the leaderboard | PASS | `test_late_joiner_mid_game`; E2E §9 |
| 3.15 | Student screen = shapes only; tiny payloads; no question/answer text; correct answer never early | PASS | [app/octagon.py:798](../app/octagon.py#L798); engine test `test_student_messages_never_contain_question_or_answer_text`, real WebSocket traffic `test_live_game_over_websocket` (every frame < 300 bytes), browser frames E2E §12 |
| 3.16 | Lightweight student route | PASS | Separate `play.html` / `play.js`; E2E §14 asserts that only the student files load and that they total < 80 KB |
| 3.17 | Colour is never the only signal | PASS | Every option has a shape and an accessible name [static/js/octagon/common.js:8](../static/js/octagon/common.js#L8) |
| 3.18 | 2–4 options; true/false handled; >4 options handled and reported | PASS | Teacher chooses trim (correct + 3 random wrong) or skip: [app/octagon.py:215](../app/octagon.py#L215); `test_long_option_questions_trimmed_or_skipped`, `test_two_option_question`; E2E 2-option layout check |
| 3.19 | Personal result after each question | PASS | `res` in `student_state`; E2E §6 |
| 3.20 | Persistent player ID + secret token, localStorage with cookie fallback, per PIN | PASS | [static/js/play.js:109](../static/js/play.js#L109) |
| 3.21 | Reconnect resumes the same player, never a duplicate | PASS | [app/octagon.py:676](../app/octagon.py#L676); `test_reconnect_resumes_same_player_without_duplicates`; E2E §8 |
| 3.22 | Same token in a second tab/device: newest wins, old one closed gracefully | PASS | `test_same_token_in_second_tab_takes_over`, `test_concurrent_join_same_nick_and_concurrent_resume`; E2E §10 |
| 3.23 | A taken nickname of a disconnected player is not hijacked | PASS | `test_duplicate_nickname_rejected_even_for_disconnected_player` |
| 3.24 | Disconnected players keep their score | PASS | `test_reconnect_resumes_same_player_without_duplicates` |
| 3.25 | Auto-reconnect with backoff; server resends the state | PASS | [static/js/play.js:214](../static/js/play.js#L214); E2E §16 (growing gaps, an answer tapped offline is delivered) |
| 3.26 | Teacher resumes control after a reload | PASS | [app/octagon.py:733](../app/octagon.py#L733); `test_host_reconnect_resumes_control`; E2E §11 |
| 3.27 | Scoring: max 1000, 500 + up to 500, measured on the server, exact, rounded once (half-up) | PASS (see note) | [app/octagon.py:77](../app/octagon.py#L77); scoring tests (≤ 0.5 s → 1000, exactly 0.5 s → 1000, half → 750, full → 500, wrong → 0, 10/20/60 s timers, 1 ms rounding including a case where floating point would be off by one). *Note:* the spec's literal clamp `max(t, 500 ms)` gives 988 at exactly 0.5 s with a 20 s timer, contradicting its own test list; implemented as “≤ 500 ms counts as 0 ms” so all listed tests hold. |
| 3.28 | One answer per question, late answers rejected, latency behaviour documented | PASS | [app/octagon.py:703](../app/octagon.py#L703); `test_one_answer_per_question_first_wins`, `test_answer_after_deadline_is_rejected_by_server_time`; README “Ball” section |
| 3.29 | Pure scoring function `calculateScore(...)` | PASS | `calculate_score(is_correct, response_time_ms, timer_ms, max_points=1000)` (Python naming) |
| 3.30 | Ties: lower total response time, then nickname | PASS | [app/octagon.py:787](../app/octagon.py#L787); `test_ties_broken_by_total_response_time_then_nickname` |
| 3.31 | Real-time over WebSocket; in-memory state with ~2 h cleanup | PASS | [app/octagon.py:906](../app/octagon.py#L906); `test_inactive_games_are_cleaned_up` |
| 3.32 | Everything validated server-side | PARTIAL → **fixed** | The role was re-checked on every teacher action, but the *session* only at connect time (finding F1). Now [app/ws.py:152](../app/ws.py#L152) |
| 3.33 | Per-IP rate limit on join attempts | PASS (+ global limit added, F4) | [app/octagon.py:628](../app/octagon.py#L628), [app/octagon.py:618](../app/octagon.py#L618) |
| 4.1 | 360 px → desktop, no horizontal scroll, ≥ 48 px targets, no hover-only, `dvh`/safe-area, PIN and QR scale | PASS | E2E `noOverflow` + `tapTargets` on every new screen at 360/375/768/1280 px |
| 4.2 | Teacher screens usable on a phone and a projector | PASS | E2E teacher screens at 375 and 1280 px; 1920 px projector check with 30 players |
| 4.3 | Balloon Pop layout not broken by the move | PASS | Balloon Pop browser regression scripts |
| 5.1–5.8 | Tests and final report | PASS | `tests/test_octagon.py`, `tests/test_octagon_api.py`, `tests/test_octagon_security.py`, `e2e/octagon.e2e.js`. The project has no type-check or build step (plain JavaScript, Python); `node --check` runs on every JS file instead |

### Inconsistencies found (client / server / tests)

| # | Inconsistency | Fix |
|---|---|---|
| I1 | The client accepted PINs starting with `0` (`\d{6}`) while the server only issues `[1-9]\d{5}` | Same regex on both sides [static/js/play.js:58](../static/js/play.js#L58); E2E §4 checks that a `0…` PIN is rejected locally and a well-formed unknown PIN gets the server's “not found” |
| I2 | Client hard-coded copies of server defaults (time 20 s, 10 questions, a “3” in the get-ready ring) | The setup form now uses the server's `limits` (`defaultTime`, `defaultQuestions`); the get-ready ring starts from the server's `remainingMs`. The 10/20/30/60 presets are the spec's presets (client-only by design; the server validates the 5–120 range) |
| I3 | Stored student identity: no expiry in localStorage but 12 h in the cookie fallback | 12 h in both; stale entries are removed at start [static/js/play.js:142](../static/js/play.js#L142); E2E §18 |
| I4 | An answer sent before the question opened got the error code `late` | New code `early` [app/octagon.py:713](../app/octagon.py#L713); `test_answer_before_question_opens_is_rejected` |
| I5 | Student UI used ʻ / ʼ (oʻ, gʻ, maʼ) but the Octagon server messages used `'` | Octagon messages normalised. Other app server messages still use `'` (pre-existing, outside this feature) |
| I6 | Dead code: unused `html` (innerHTML) option of the shared `h()` helper — an XSS foot-gun; unused `Player.joined_at` | Both removed |
| I7 | A third-party product name in a code comment (`app/octagon.py`) | Removed. The previous commit message (`acb5660`) also contains it; published history was not rewritten (that needs a force-push) |
| I8 | Duplicated scoring or timer logic? | None: only the server computes points (`calculate_score`); clients only display server values. One timer source: the game's `time_limit_ms` |
| I9 | i18n strings missing in a language? | Not applicable: the app is Uzbek-only and has no i18n framework; Octagon strings are grouped per module in `T` dictionaries, like the existing views |
| I10 | TODO / FIXME markers | None |

---

## A2/A3. Security findings

Severity: **critical** — remote compromise or data loss; **high** — another user's data or control without credentials;
**medium** — abuse that needs some access or disrupts a class; **low** — hardening, robustness, information leaks of
little value.

| ID | Sev. | What was wrong (and how it was reproduced) | Fix | Regression test |
|---|---|---|---|---|
| F1 | Medium | **Teacher WebSocket kept its authority after logout or a password reset.** The session was checked only when the socket opened; an already-open teacher socket (e.g. a stolen or forgotten session) kept controlling the game and receiving question and answer data. Repro: open host socket → `POST /api/auth/logout` (or the owner resets the password) → socket still open, `start` still worked. | The session is re-read from the database on **every** teacher message [app/ws.py:152](../app/ws.py#L152); logout, password reset, block and delete close that user's teacher sockets with 4401 [app/octagon.py:757](../app/octagon.py#L757), [app/api.py:328](../app/api.py#L328) | `tests/test_octagon_security.py::test_host_socket_loses_control_after_logout_or_password_reset` |
| F2 | Medium | **No security headers.** No CSP, no `X-Frame-Options`/`frame-ancestors` (admin and teacher pages could be framed for click-jacking: e.g. “make teacher”, “end game”), no `nosniff`, no `Referrer-Policy`. Repro: `curl -I /`. | Headers on every response [app/server.py:131](../app/server.py#L131); strict CSP — scripts and styles only from the site (the one inline script in `index.html` allowed by its SHA-256), `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'` [app/server.py:58](../app/server.py#L58); HSTS when served over HTTPS | `test_security_headers`; E2E and an every-route crawl as owner, teacher, student and guest show no CSP violations |
| F3 | Medium | **Teacher could not stop unwanted joiners.** A kicked player could rejoin at once with the same nickname; per-IP bans are impossible because a whole class shares one school IP. | Kicked nicknames are reserved for that game [app/octagon.py:655](../app/octagon.py#L655); new **“Qoʻshilish ochiq / yopiq”** (joining open/closed) toggle for the teacher [app/octagon.py:424](../app/octagon.py#L424) — reconnecting players are not affected | `tests/test_octagon.py::test_kicked_nickname_stays_reserved_and_join_lock`; E2E §19 |
| F4 | Low | **PIN guessing limited only per IP** (20 failures / 5 min); many IPs could scan the 900 000-PIN space faster. | Global failure counter: above 300 failed PIN/token attempts per minute across all IPs, each IP is allowed 5 instead of 20; IPs without failures (e.g. other classes) are unaffected [app/octagon.py:618](../app/octagon.py#L618) | `test_global_failure_surge_tightens_per_ip_limit` |
| F5 | Low | **Lookups of finished games were free:** a PIN of an ended game returned “ended” without counting as a failed attempt, so finished games could be enumerated without limit. | Counted as a failed attempt [app/octagon.py:636](../app/octagon.py#L636) | `test_ended_game_pin_checks_count_as_failed_attempts` |
| F6 | Low | **Crash on an invalid token:** `resume` with `tok: "\ud800"` (valid JSON, not encodable as UTF-8) raised `UnicodeEncodeError` — a stack trace in the log for every message (log flooding) and the attempt was not rate-limited. | Token format validated before hashing [app/octagon.py:71](../app/octagon.py#L71) | `test_resume_cannot_impersonate_another_player` |
| F7 | Low | **Unhandled `RecursionError`:** deeply nested JSON (`[[[…]]]`, 30 000 levels) fits in the duel socket's 64 KB limit and killed the connection with an “Error handling request” traceback. The Octagon socket (4 KB) could not reach the limit but shares the code. | Caught and ignored in both socket handlers [app/ws.py:91](../app/ws.py#L91) | `test_deeply_nested_json_is_ignored` |
| F8 | Low | **No global socket cap** — only 500 per IP, so many IPs could exhaust memory. | `TD_OCTAGON_MAX_SOCKETS` (default 5000) [app/octagon.py:333](../app/octagon.py#L333) | `test_socket_caps_per_ip_and_global` |
| F9 | Low | **Finished games could fill the server:** only unfinished games counted against a teacher's limit, so one teacher creating and ending games could reach `MAX_GAMES` (500) and block every other teacher (“server busy”). | At most 5 finished games kept per teacher (oldest closed first) [app/octagon.py:562](../app/octagon.py#L562); at capacity the oldest finished game makes room instead of refusing | `test_finished_games_do_not_exhaust_server_capacity` |
| F10 | Low | **One exception in a timer stopped cleanup for good** (memory leak) or could freeze a game. | Every timer callback is guarded and logged [app/octagon.py:325](../app/octagon.py#L325); cleanup always reschedules [app/octagon.py:906](../app/octagon.py#L906) | `test_sweep_keeps_running_after_an_error` |
| F11 | Low | Answer before the question opened was rejected as `late` (misleading; see I4). | `early` | `test_answer_before_question_opens_is_rejected` |
| F12 | Low | **QR/join link built only from the `Host` header;** no way to pin the public address (some proxies rewrite `Host`). | Optional `TD_PUBLIC_URL` (validated at start-up) [app/api.py:529](../app/api.py#L529); a malformed `Host` never reaches the QR code | `test_join_url_setting_and_host_header_validation` |
| F13 | Low | Student ID + token **never expired** in localStorage (shared school computers); the cookie fallback lacked `Secure` on HTTPS. | 12 h expiry everywhere, stale entries pruned; cookie `Secure; SameSite=Strict` on HTTPS (see I3) | E2E §18. The `Secure` flag is only verified by reading the code: the E2E runs over plain HTTP |
| F14 | Low | Unused `html` (innerHTML) option in the shared DOM helper — one careless use away from XSS (see I6). | Removed | XSS test E2E §17 |

### Checked and found safe (kept as regression tests)

| Area | Result | Evidence |
|---|---|---|
| Non-teacher creates/starts/advances/ends a game (REST and WebSocket, menu hidden or not) | 401/403 | `test_roles_and_permissions`, `test_player_socket_cannot_send_host_messages` |
| Self-assigning the teacher role (mass assignment on register, PATCH own user, forged cookie) | Ignored / 403 / 401; roles live only in the database | `test_roles_cannot_be_self_assigned` |
| IDOR: another teacher or admin controls a game by PIN (REST, WebSocket) | 404; game untouched | `test_teacher_cannot_control_another_teachers_game` |
| Student sends teacher-only message types | 403 for every type | `test_player_socket_cannot_send_host_messages` |
| PIN generation | CSPRNG (`secrets.randbelow`), unique among running games | [app/octagon.py:381](../app/octagon.py#L381) |
| PIN enumeration by message or timing | Same code path (dict lookup); “locked”/“ended” only for real PINs, both counted (F5) | `test_unknown_pin_and_rate_limit` |
| Player token | 192 bits ([app/octagon.py:664](../app/octagon.py#L664)), only its SHA-256 kept, compared with `hmac.compare_digest` ([app/octagon.py:685](../app/octagon.py#L685)), sent only to its owner | `test_player_tokens_never_reach_host_or_other_players` |
| Resume as another player (ID without token, own token + other ID, nickname) | Rejected and counted as a failed attempt | `test_resume_cannot_impersonate_another_player` |
| Races: same nickname at the same moment, same token in 3 tabs at once, reconnect during a question change, join exactly at Start | One winner / newest tab wins, no duplicates / current state resent, old answers rejected / joins the get-ready phase | `test_concurrent_join_same_nick_and_concurrent_resume`, `test_join_at_start_and_reconnect_during_question_change` |
| Forged time, score, correctness; negative, huge, float, string or boolean option index | Server measures time and decides correctness; malformed answers rejected | `test_forged_answer_fields_are_ignored`, `test_malformed_answers_rejected` |
| Double submit, replay, after the timer, previous question, exact deadline | First answer wins; deadline +1 ms rejected; exactly at the deadline accepted (500 points) | `test_one_answer_per_question_first_wins`, `test_answer_after_deadline_is_rejected_by_server_time` |
| Question text / correct answer reaching students early (code, real traffic, HTML/JS bundle) | Never | engine, WebSocket and browser-frame tests (3.15); `/play` is a static page with no question data |
| XSS: `<img src=x onerror=…>`, `<script>`, `"><svg onload=…>` in topic name, question, options, nicknames (also sent raw over WebSocket) | Rendered as text everywhere; no element created, no script run | E2E §17 (teacher lobby, active-games list, question, reveal, leaderboard, podium, student page) |
| SQL injection | All values are bound parameters; dynamic SQL only joins constant fragments and `?` placeholders | `app/db.py` review |
| Command injection | No shell or subprocess use in the app | review |
| Open redirect / PIN parameter | `/play/*` is a static page, never redirects or echoes input; REST PINs validated | `test_pin_parameters_validated_and_no_open_redirect` |
| CSRF on teacher endpoints; cross-site WebSocket; CORS | `Origin` must match ([app/api.py:61](../app/api.py#L61)); JSON-only bodies ([app/api.py:102](../app/api.py#L102)); `SameSite=Lax` session cookie; no CORS headers at all | `test_csrf_and_cors_on_teacher_endpoints`, cross-origin WebSocket → 403 in `test_roles_and_permissions` |
| Message size, message rate, players per game, games per teacher, nickname length, join flood, open sockets | 4 KB; 60 per 10 s (close 4008); 300; 5 unfinished + 5 finished; 20 chars; 200 joins / 10 min / IP; 500 per IP + 5000 total | `test_ws_message_size_and_flood_limits`, `test_player_cap_and_join_flood_limit`, `test_teacher_game_limit`, `test_bad_nicknames_rejected`, `test_socket_caps_per_ip_and_global` |
| One bad client slowing everyone down | 300-player game in the engine: worst single answer 1.6 ms, podium broadcast 11 ms. Slow readers: aiohttp applies back-pressure per socket; the 20 s heartbeat closes dead sockets | benchmark (`scratchpad`, numbers above) |
| Leaks after a game ends / after disconnects | No games, connections, socket counts or timers left (only the shared cleanup timer) | `test_no_state_left_after_game_closed`, `test_inactive_games_are_cleaned_up` |
| Server restart | Running games are lost (memory only). Sockets close with 1001; students see “your place was not found” then “PIN not found”; the teacher sees “Game not found” with a “New game” button. Documented in the README | `test_server_restart_loses_running_games_cleanly` |
| Secrets in logs, URLs, errors, bundle; debug flags | Player tokens never logged or put in URLs (only in WebSocket frames); access log off; errors are generic; no debug mode or endpoints | review |

### Dependency audit

| Tool | Result |
|---|---|
| `pip-audit -r requirements.txt` (aiohttp 3.14.5 and its dependencies) | **No known vulnerabilities** |
| `pip-audit` of the whole sandbox Python | 76 known issues in `pillow`, `pypdf`, `urllib3`, `soupsieve`, `opentelemetry-api` — preinstalled sandbox packages that the app does not use or ship; nothing to upgrade in the project |
| `npm audit` | Not applicable: the repository has no `package.json`; the browser code uses no third-party libraries. Playwright is a developer tool installed outside the repo for the E2E run |

No dependency versions were changed.

---

## Not fixed / accepted risks

1. **PIN guessing from a very large botnet** is slowed (F4) but not impossible — the spec fixes PINs at 6 digits
   (900 000 values). Impact is limited to joining a quiz as an extra player; the teacher can remove them and close
   joining (F3).
2. **Students with app accounts** could open the same topic in Oʻrganish during a game to look up answers (topics are
   shared between modes). This is organisational; Octagon only offers active topics.
3. **State is in memory:** a restart ends running games (documented behaviour above). A multi-instance deployment
   would need shared state (Redis); the app is deployed as a single instance (`numReplicas: 1`).
4. **Network latency counts against the student** — required by the spec (the server's clock decides); the student's
   timer finishes a little early to compensate for the measured delay.
5. **Nickname profanity filter is basic** (Uzbek, Russian, English word lists).
6. **Third-party name in commit `acb5660`'s message** is still in git history (rewriting published history needs a
   force-push; ask if you want it).
