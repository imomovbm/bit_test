# Octagon v2 — bug inspection

Scope: the whole Octagon feature after the v2 changes: the topic intro, the 5 s reading phase, absolute server
timestamps with clock sync, emoji avatars and protocol v2. That covers `app/octagon.py`, `app/octagon_flow.py`,
`app/octagon_scoring.py`, `app/security.py` (rate limiter), `static/js/play.js`, `static/js/octagon/common.js`,
`static/js/views/octagon.js`, the related CSS and the tests. Baseline: commit `e539249`. The first audit
([octagon-audit.md](octagon-audit.md)) covered v1; its protections were re-checked and are still in place.

Method: work through the checklist in §2 of the v2 spec, thinking as a tester and as an attacker. **For every
suspected bug, a test or browser check was written first and run against the unchanged code.** It failed; then the
fix was made and the test passed. Checks for areas that turned out to be correct were kept as regression tests. The
server-side tests are in `tests/test_octagon_v2_audit.py`. The browser checks for F8–F10 run in
`e2e/octagon.e2e.js`. Line links point to the code as of this report.

**Result: 10 findings, all fixed and covered by tests.**

- **1 high.** F6 was introduced during the v2 work and caught by the browser smoke run before the commit.
- **4 medium.** F1, F2, F4, F9.
- **5 low.** F3, F5, F7, F8, F10.

Limitations that remain by design are listed at the end; no known bug is left unfixed.

## Findings

| ID | Severity | What was wrong | Fix | Test |
|---|---|---|---|---|
| F1 | Medium | **A full class behind one school network could not join.** New joins were limited to 200 per IP per 10 minutes, but a game allows 300 players (`MAX_PLAYERS`). Schools put every pupil behind one NAT address, so the 201st pupil, or the second class in the same 10 minutes, got "too many join attempts". | 1000 joins per IP per 10 minutes [app/octagon.py:67](../app/octagon.py#L67). The per-game player cap, per-socket flood limits and the global socket cap still apply. | `test_f1_full_class_behind_one_school_nat_can_join` (failed at the 200th join) |
| F2 | Medium | **PIN typos in one class locked out the whole school.** After 20 failed PIN attempts per IP in 5 minutes, every check from that IP was refused for everyone. 30 children typing a 6-digit PIN reach that easily. | 60 failures per IP per 5 minutes [app/octagon.py:64](../app/octagon.py#L64). The global surge guard is unchanged: above 300 failures/min across all IPs, each IP gets 5. Trade-off below. | `test_f2_pin_typos_in_a_big_class_do_not_lock_out_the_whole_school` (the correct PIN was refused after 40 typos) |
| F3 | Low | **The rate limiter never forgot old IPs.** It removed a key only when its bucket was empty, but a bucket empties only when that same key is used again. Every distinct IP stayed in memory forever. Above 20,000 keys, each call scanned the whole dict (O(n) per request). | Above 2,048 keys, keys whose last hit is outside the window are dropped, at most once per window [app/security.py:58](../app/security.py#L58). Memory is bounded by about two windows of distinct IPs; the cost is amortised. | `test_f3_rate_limiter_forgets_stale_keys` (20,000 stale keys remained) |
| F4 | Medium (privacy) | **Personal data in the logs.** The "game finished" line listed the top students' nicknames (often real names) with scores; the "game created" line named the teacher's login. | Logs carry only the PIN, the topic id, the teacher's user id and counts [app/octagon.py:389](../app/octagon.py#L389), [app/octagon.py:588](../app/octagon.py#L588). | `test_f4_logs_contain_no_student_nicknames_or_teacher_login` (log contained `Zulfiya Karimova 1000, Sardorbek 0`) |
| F5 | Low | **Pages left open from before the deploy broke silently.** A v1 student or teacher page ignores the new `reload` message, so it just stopped responding. | A handshake without a version also gets an error in the v1 format, with code `pin`/`gone`/`reload` and the text "the site was updated — reload the page", which the old pages display [app/octagon.py:626](../app/octagon.py#L626). | `test_f5_v1_student_page_gets_a_visible_reload_message[check/join]`, `test_f5_v1_teacher_page_gets_a_visible_reload_message`, `test_old_or_unknown_protocol_version_gets_reload_not_silent_breakage` |
| F6 | High | **The server did not start.** During the v2 work, the hub read the event-loop clock in its constructor, which runs before any loop exists in `run.py`. The unit tests use a fake clock, so they passed. | The epoch for Unix-ms timestamps is taken lazily on first use [app/octagon.py:324](../app/octagon.py#L324). Fixed in `e539249` before it was pushed. | `test_app_can_be_created_outside_a_running_event_loop`; found by the browser smoke run |
| F7 | Low | **Kicking the last student who had not answered left the question open** until the timer ran out. | After a kick, the question closes if every remaining connected player has answered [app/octagon.py:798](../app/octagon.py#L798), [app/octagon.py:598](../app/octagon.py#L598). | `test_f7_kicking_the_last_unanswered_player_closes_the_question` |
| F8 | Low (UX) | **The typed nickname was lost.** On the join screen, the name field was redrawn from the last saved nickname. The name the student had just typed vanished while the join was in flight, and after a "name taken" error they had to retype it. | The draft is kept in state; after an error the field is focused with the text selected for a quick correction [static/js/play.js:645](../static/js/play.js#L645). The chosen avatar was already kept. | Browser: field empty after "band" (taken) error before the fix, `ali` after; E2E check in `e2e/octagon.e2e.js` |
| F9 | Medium | **Holding Space or Enter skipped the topic intro and the reading time.** The teacher shortcuts did not ignore keyboard auto-repeat. A slightly long press on Start went lobby → intro → reading → answers within about a second, which defeats the 5 s intro and 5 s reading this version adds. | Auto-repeated key events are ignored; one press is one action [static/js/views/octagon.js:872](../static/js/views/octagon.js#L872). | Browser: before, teacher and students were in `question_active` after one held key; after, still in `topic_intro`. E2E check in `e2e/octagon.e2e.js` |
| F10 | Low (UI) | **Long topic names pushed the controls off-screen.** The intro always used the full display size. With a 120-character topic name (the maximum), on a phone-width teacher screen the countdown and Skip button ended up 250 px below the fold at 360 px (214 px at 375 px). | Topic names over 40 or 80 characters use a smaller size, on both screens [static/js/play.js:684](../static/js/play.js#L684), [static/css/app.css:1582](../static/css/app.css#L1582), [static/css/play.css:446](../static/css/play.css#L446). The big countdown ring is smaller on narrow teacher screens [static/css/app.css:1671](../static/css/app.css#L1671). | Browser, 360/375/768/1280 px: no horizontal scroll, nothing clipped, countdown and Skip visible without scrolling, PIN visible. Before: Skip 250 px below the fold; after: 46 px above it. E2E check in `e2e/octagon.e2e.js` |

## Checklist coverage (§2 of the v2 spec)

| Area | Checked | Result | Tests |
|---|---|---|---|
| Phase transitions | Double advance (two teacher windows, repeated next/skip/end); next/start during intro/reading; ending early in every phase; teacher reconnect in all 7 phases; timers after the game ended; timers left running; two games at once | OK, plus F7 and F9 | `test_double_skip_or_next_from_two_windows_never_double_advances`, `test_every_transition_is_either_allowed_or_rejected`, `test_illegal_transition_is_a_bug_not_silently_accepted`, `test_end_during_intro_or_reading_plays_no_unopened_question`, `test_end_early_and_cancel_in_lobby`, `test_teacher_and_student_reconnect_in_every_phase[7 phases]`, `test_closing_in_any_phase_leaves_no_timers_and_nothing_fires_later[7 phases]`, `test_two_games_at_once_do_not_interfere`, `test_stale_host_action_is_ignored` |
| Boundaries | Answer at exactly the timer end (accepted) and 1 ms later (rejected); answer during `question_read` (`early`, rejected); answer for a previous or future question; double answer; late join and reconnect at each phase change | OK | `test_answer_exactly_at_timer_end_is_accepted_one_ms_later_rejected`, `test_answer_before_question_opens_is_rejected`, `test_answers_for_previous_or_future_questions_never_count`, `test_one_answer_per_question_first_wins`, `test_late_join_and_reconnect_in_each_timed_phase_land_in_the_right_place`, `test_join_at_start_and_reconnect_during_question_change` |
| Reconnection | Same token in two tabs (the newer one takes over); reconnect in every phase; no duplicate players; avatar and score kept | OK | `test_same_token_in_second_tab_takes_over`, `test_concurrent_join_same_nick_and_concurrent_resume`, `test_reconnect_resumes_same_player_without_duplicates`, `test_teacher_and_student_reconnect_in_every_phase`, `test_avatar_changes_only_in_lobby_and_persists_across_reconnect` |
| Scoring | Exact values with the unchanged formula; rounding at 1 ms edges; clamps (≤ 500 ms = 1000 points, over the timer rejected); tie-break (score, then total time, then nickname); timing from the start of `question_active`, not from reading | OK (formula moved unchanged into `app/octagon_scoring.py`) | `test_score_*` (8 tests), `test_ties_broken_by_total_response_time_then_nickname`, `test_answer_timing_starts_at_active_not_at_reading`, `test_full_game_scores_ranks_and_podium` |
| Information leaks | No question text, answer text or correct answer in student payloads before the reveal; avatars sent as indexes; tokens never reach the teacher or other players; real WebSocket frames checked in the browser | OK | `test_student_messages_never_contain_question_or_answer_text`, `test_only_indexes_go_over_the_wire_to_students`, `test_player_tokens_never_reach_host_or_other_players`; E2E captures every frame a student receives |
| Input safety | Nickname rules; avatar allowlist (index only; strings, emoji, floats, booleans and out-of-range values rejected); forged answer fields; message size, nesting and flood limits; max players; rate limits; XSS: everything is rendered as text nodes, and no `innerHTML`-style sink exists in the Octagon UI code | OK, plus F1 and F2 | `test_clean_nickname`, `test_bad_nicknames_rejected`, `test_invalid_avatar_values_are_rejected`, `test_join_requires_a_valid_avatar_index_and_never_trusts_strings`, `test_forged_answer_fields_are_ignored`, `test_malformed_answers_rejected`, `test_ws_message_size_and_flood_limits`, `test_deeply_nested_json_is_ignored`, `test_player_cap_and_join_flood_limit`, `test_octagon_ui_code_has_no_html_injection_sinks`; E2E (a nickname made only of HTML tags is rejected, a nickname with markup is shown as text) |
| Memory / cleanup | Games, sockets, connection info and timers gone after the game ends (in every phase), after inactivity and after the teacher leaves; finished games do not use up capacity; rate-limiter memory | OK, plus F3 | `test_no_state_left_after_game_closed`, `test_closing_in_any_phase_leaves_no_timers_and_nothing_fires_later`, `test_inactive_games_are_cleaned_up`, `test_finished_games_do_not_exhaust_server_capacity`, `test_sweep_keeps_running_after_an_error`, `test_f3_rate_limiter_forgets_stale_keys` |
| UI | Every screen at 360/375/768/1280 px; no clipped text; PIN always visible; strings present | OK, plus F8 and F10 | E2E (no horizontal scroll, PIN visible on every screen, tap targets); the F10 browser check; `tests/test_i18n_strings.py` (every `T.key` used exists, no empty strings, one avatar name per avatar) |
| Logs and privacy | No nicknames, logins or tokens in log lines | F4 | `test_f4_logs_contain_no_student_nicknames_or_teacher_login` |
| Deploy compatibility | Old open pages after a deploy; unknown message types | F5 | `test_f5_*`, `test_unknown_message_types_are_ignored_safely` |

i18n note: the app has one UI language (Uzbek). Every module keeps its strings in its own `T` table, and the
server sends error texts. "Strings present in every language" is therefore checked as "every key used exists".
`tests/test_i18n_strings.py` covers all three Octagon UI modules and would run per language if one is added.

## Not fixed / accepted limitations

1. **Teacher reading screen at phone width with a maximum-length question.** A question of about 400 characters on
   a 360 px teacher screen needs an 80 px scroll to reach "open answers now". Nothing is clipped and the timer runs
   on its own; teacher screens are meant for a projector or laptop. Realistic lengths fit at every width.
2. **The lobby is open to anyone with the PIN.** After F1, one IP may add up to 1000 players per 10 minutes, so a
   script inside the classroom could fill a game up to `MAX_PLAYERS`. The teacher can lock the lobby and kick
   players; a kicked nickname stays reserved. A per-IP cap per game would bring back the NAT problem from F1.
3. **PIN guessing (F2 trade-off).** The per-IP failure budget went from 20 to 60 per 5 minutes. The global surge
   guard (300 failures/min across all IPs, then 5 per IP) is unchanged, so a distributed guessing attack is capped
   as before. The residual risk from a very large botnet, accepted in the first audit, is unchanged.
4. **A disconnect does not count as an answer.** The question closes early only when every *connected* player has
   answered. A student whose phone drops can reconnect and still answer until the timer ends; the timer bounds the
   wait. This is deliberate.
5. **Single instance.** Game state lives in one process; a restart ends the running games (the clients are told).
   See the scaling and runbook notes.

## Failing-first evidence (before the fixes)

- **Server.** `python -m pytest tests/test_octagon_v2_audit.py` → `8 failed, 8 passed`. The failures were F1, F2,
  F3, F4, F5 ×3 and F7; the passing tests were the checks of areas that were already correct. After the fixes all
  pass. The outdated expectations in two older tests were updated to the new limits and legacy messages:
  `test_unknown_pin_and_rate_limit` now uses `FAIL_LIMIT`, and the protocol test expects the legacy error for
  version-less handshakes.
- **F6.** The browser smoke run failed at startup. `test_app_can_be_created_outside_a_running_event_loop` was
  written, failed, and passes after the fix.
- **F8.**
  ```
  {"valueAfterTakenError":"","avatarKept":"true"}
  FAIL
  ```
- **F9.**
  ```
  {"student":"pl-view-game pl-phase-question_active","teacher":"active"}
  FAIL
  ```
- **F10.** Skip button 250 px below the fold at 360 px and 214 px at 375 px.

## Test totals

`python -m pytest`: **358 passed**. That is 326 at commit `e539249` plus 32 new from this audit: 25 in
`tests/test_octagon_v2_audit.py`, 8 of which failed before the fixes, and 7 in `tests/test_i18n_strings.py`.
Browser checks: see `e2e/octagon.e2e.js`.
