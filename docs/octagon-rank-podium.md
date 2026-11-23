# Octagon: rank changes and the podium reveal

This note covers two features:

- the rank change shown after every question;
- the step-by-step reveal of the winners that replaced the old immediate `podium` screen.

Phases, protocol fields and configuration are also listed in [architecture.md](architecture.md).

## Rules (server side, pure functions)

| Function | Where | What it decides |
|---|---|---|
| `rank_order`, `rank_changes(before, after)` | `app/octagon_scoring.py` | Ranks before and after a question. Order: score (high first), total answer time (low first), name, id. `delta = previous − new` |
| `biggest_jump(changes)` | same | The largest climb of at least 2 places; on a tie, the higher new rank wins |
| `podium(ranked, has_points, ended_early)` | same | Who is revealed: the top 3, or fewer if there are fewer players. Nobody if nobody is left, or if the game was ended early before anyone scored |
| `reveal_steps`, `after_timer`, `on_next`, `on_skip`, `finish_phase` | `app/octagon_flow.py` | The reveal sequence for 0–3 places, plus Next and Skip |
| `revealed_places(phase, places)` | same | The only rule for which places may be sent in a phase |

**When a question closes:**

- "Before" contains the players who were in the previous ranking (`first_q < question`).
- Players who joined while this question was being read or answered are not in it: they show **NEW** (`late` and
  `first_q == question`). A player who joins during the result or leaderboard is NEW on that board, then gets normal
  changes from the next question.
- Question 1 has no "before": no arrows.
- Disconnected players stay ranked. Non-answerers add 0 points and the full question time.

**When the questions end:**

- The podium is frozen in `Game.podium`.
- Scores can no longer change, and kicking is refused (409).
- Players who join during the reveal (`after_end`) are ranked after everyone who played, so they never enter the podium
  and the announced places stay true.

## What each screen receives

| Phase | Teacher (`h`) | Student (`s`) |
|---|---|---|
| `question_result` / `leaderboard` (not the last question) | `leaderboard` (top 5: `gained`, `d`, `new`) and `jump` | own `k`, `pl`, `dk`, `nw`, and `bh` (`[points, nick]` of the player just above, if within 1000 points) |
| `question_result` of the last question | answer distribution only, no `leaderboard` | `res` only: no rank, change or neighbour |
| `podium_intro` | `places` (count only) | `top: []` |
| `reveal_3rd` / `reveal_2nd` / `reveal_1st` | `podium`: announced places only | `top`: announced places only; `k` only when the student's own place has been announced |
| `final_results` | `podium`, full `ranking`, `played` | `k`, `pl`, `nc`, `top` |

**No leaks.**

- The last question has no leaderboard, and its result carries no ranks. Otherwise the top 5, and every phone's rank,
  would give the podium away before the reveal.
- An early **End** reveals the current scores. If the class saw a leaderboard just before, it already showed those
  scores. That is not a leak by the server: it was the interim result at the time.

**Message size.** A student message during the reveal is about 100 bytes: three entries at most, sent to everyone.
A result message is under 160 bytes even in a 30-player game.

## Screens

**Teacher leaderboard**

- Each row shows: rank, avatar, name (ellipsis, full name in `title`), `+points this question`, total, and the change.
- Change markers: `▲ N` (green), `▼ N` (red), `–` (no change), `YANGI` ("new"; amber badge). The arrow and number are
  always there, so colour is never the only cue.
- Rows slide from their previous place with a FLIP animation, using the Web Animations API on `transform` and
  `opacity` only:
  - 700 ms, after a 450 ms pause so the old order is seen first.
  - Rows entering the top 5 come up from below the list.
  - With `prefers-reduced-motion: reduce` the movement is skipped.
- A "Biggest jump ▲ N" line appears when someone climbs at least 2 places.

**Reveal (teacher)**

- One podium stage for all steps. Each new place:
  - its bar grows (CSS keyframes on `height`, 1.2 s);
  - then the avatar, name (two lines, then an ellipsis) and score land.
- 1st place gets a light CSS-only confetti burst: 18 empty `<i>` elements with directions set in CSS. It is hidden
  with reduced motion.
- Next (Space/Enter) advances one step; "Natijalarga oʻtish" ("Go to results") jumps to the final results.
- A reload in the middle of a step shows the earlier places already landed.

**Final results (teacher)**

- A compact podium and the full ranking, with the top 10 highlighted.
- A name search for large classes.
- Buttons: CSV download, Games panel, New game.
- CSV columns: name, avatar, score, rank, correct answers. It is UTF-8 with a BOM. Cells starting with `= + - @` get a
  leading apostrophe so a spreadsheet never runs them as a formula.

**Student**

- Result card:
  - avatar and total;
  - "▲ 3 → 5-oʻrin · 24" with "3 oʻringa koʻtarildingiz" ("you moved up 3 places");
  - "Ali sizdan 120 ball oldinda" ("Ali is 120 points ahead of you") when that player is within 1000 points.
- During the reveal:
  - everyone sees "Kim podiumga chiqdi?" ("Who made the podium?") and the list of places announced so far;
  - a podium student gets a personal card at the moment their place is announced (confetti for 1st);
  - everyone else sees their rank only in `final_results`.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `TD_OCTAGON_PODIUM_INTRO` | 3 s | "And the winners are…" |
| `TD_OCTAGON_REVEAL_STEP` | 3.5 s | 3rd and 2nd place on screen |
| `TD_OCTAGON_REVEAL_WINNER` | 6 s | 1st place on screen before the full results |

## Compatibility

- **Protocol 3.** Student phase indexes 6–10 are new, and index 6 used to be `podium`. A page still on protocol 2 gets
  `reload` ("the site was updated") instead of misreading the indexes.
- **Restart file version 2.** It adds the podium and the join markers. A version-1 file from the previous release is
  upgraded on load: `podium` → `final_results`, with the podium taken from the ranking.

## Bugs found while building and testing

**R-1: "null" on the teacher's 1st-place step.**

- **Cause:** the Skip button is not shown on the last step, so the action list held `null`. `replaceChildren()` turns
  `null` into the text "null".
- **Found by:** reading the reveal screenshots.
- **Test (failed first):** `e2e/podium.e2e.js` checks that no finale screen contains the text `null`, `undefined` or
  `NaN`. It failed on `reveal_1st`.
- **Fix:** filter empty entries.

**R-2: the teacher leaderboard and final list at 360 px.**

- **Cause:**
  - on the leaderboard, the empty "points gained" and arrow slots reserved width, so two-word names were squeezed
    and clamped;
  - the arrow badges and "+points" were scaled down with the row font, to 10–11.9 px;
  - on the final list, the correct-answers column did the same.
- **Tests (failed first):** three checks in the design section of `e2e/octagon.e2e.js`, all at 360 px:
  - the clipping check on "leaderboard-arrows";
  - the minimum 12 px text check on "leaderboard-arrows";
  - the clipping check on "final".
- **Fix:**
  - question 1 boards have no arrow column;
  - below 480 px the score and "+points" are stacked, and the correct-answers count moves under the name;
  - empty "+points" cells take no room;
  - the arrow badges and "+points" have a 12–13 px minimum.

**R-3: the final screen would redraw whenever a student disconnected.**

- **Cause:** the screen's change key included the online flag. Every disconnect would have redrawn the full ranking
  and dropped the search text.
- **Found by:** code review before the first browser run.
- **Fix:** removed the flag from the key. The final list does not show online status.
- **Test:** a regression test was added afterwards (`e2e/podium.e2e.js` B3: after a student leaves, the ranking list
  is still the same DOM element). It was not written first. With the bug put back temporarily, the test fails.

**R-4: the 1st-place confetti made the page 23 px wider at 360 px.**

- **Cause:** the pieces fly up to about 195 px sideways. Their final transform was kept after the animation
  (`fill-mode: both`), so the invisible pieces stretched the page sideways.
- **Tests (failed first):**
  - teacher: the design section of `e2e/octagon.e2e.js`, `reveal_1st` at 360 px;
  - phone: a new check in `e2e/podium.e2e.js` (the winner on a 360 px phone), written and seen failing before the fix.
- **Fix:**
  - the pieces return to their origin, invisible, when the animation ends (`fill-mode: backwards`);
  - the podium stand and the phone's winner card clip horizontally (`overflow-x: clip`). Only those two: an earlier
    version clipped the whole finale screen and hid a cut-off button (R-5).

**R-5: the podium and its buttons at narrow widths.**

- **Cause:**
  - the place medal on an unrevealed placeholder hung below the short dashed pedestal;
  - on the compact podium of the final results, the 3rd-place medal was taller than its bar and spilled into the list;
  - at 360 px, "Madinabonu Rahimova" was broken in the middle of a word ("Madinabon u…"), on the reveal and on the
    compact podium;
  - the "Natijalarga oʻtish" ("go to results") button and the final-results buttons were cut off. On narrow screens
    every action button had `flex: 1` (zero basis), so the row never wrapped.
- **Tests, all in `e2e/octagon.e2e.js`:**
  - `medalsInside`: every visible medal sits inside its bar. Written first; it failed on `podium_intro` at 360 px.
  - The clipping check now covers podium names on every reveal step and the final results. With the old CSS it fails
    on `reveal_2nd` at 360 px.
  - The clipping check now also covers the finale and final-results buttons. Written first; it failed on
    `podium_intro` and then on `final`, at 360 px.
  - `wordsWhole`: no word of a name is split across lines, checked with text ranges. Written first; it failed on the
    compact podium at 360 px.
- **Fix:**
  - unrevealed pedestals have no medal;
  - the compact podium has smaller medals and taller bars;
  - narrow podium columns use 14 px names (13 px on the compact podium), up to three lines;
  - the finale and final-results buttons keep their natural width and wrap to the next line.

The browser test runs also turned up several mistakes in the tests themselves, which were fixed in the tests: expected
orders that depended on near-equal speed points from different questions, and counters that counted a late joiner
twice. They were not product bugs.

## Tests

**Pure rules: `tests/test_octagon_ranks.py`**

- rank and change: ties, tie-break order, late joiners, removed players, zero scores, question 1, unchanged rank, big
  jumps, non-answerers;
- biggest jump;
- the podium for 0, 1, 2, 3 and many players, and the early-end zero case;
- the reveal sequence for 0–3 places;
- `revealed_places` never runs ahead of the step.

**Phase machine: `tests/test_octagon_flow.py`**

- every transition, including the new phases;
- durations from config (`timings()`);
- timer, Next and Skip rules;
- joining is refused only in `final_results`.

**Engine: `tests/test_octagon_podium.py`**

- arrows on both screens; NEW for late joiners; disconnected players; zero scores; payload size and contents;
- the last result without ranks;
- order and timings of the reveal; config timings;
- a message-by-message no-leak check with two teacher windows, a late join and a reconnect;
- 2, 1 and 0 players; ties; early end with and without points;
- a late join that cannot enter a short podium; joining refused after the end;
- student and teacher reconnect in every reveal phase;
- idempotent Next and Skip; kick refused after the end;
- restart in every reveal phase; restoring a version-1 file;
- server-side scores only.

**Every phase: `tests/test_octagon_v2_audit.py`, `tests/test_octagon_restart.py`**

- reconnect, close and restart in all 11 phases.

**Browser: `e2e/podium.e2e.js` (real WebSocket frames)**

- 7 players with changing ranks:
  - the teacher's arrows and numbers match the API, and the rows slide from their old place (recorded animation
    calls);
  - each phone shows the right change and points-ahead line.
- The reveal on every screen in the right order and timing.
- No leaks in any frame or on any screen before each step.
- A late join during the reveal.
- A reload of a student and of the teacher in every reveal phase.
- Reduced motion; a 20-character name with no spaces; CSV safety.

**Browser: `e2e/octagon.e2e.js`**

- Screenshots at 360, 375, 768 and 1280 px of:
  - the leaderboard with arrows;
  - every reveal step;
  - the final results, on the teacher and student screens.

## Screenshots

Taken by the browser tests with CI-like fonts. Each sheet shows the teacher and student screens at 360, 375, 768 and
1280 px, all in `docs/screenshots/octagon-rank-podium/`:

| Screen | File |
|---|---|
| Leaderboard with arrows and the biggest jump | `leaderboard-arrows.jpg` |
| Result: rank change on the phone | `result-rank-change.jpg` |
| "And the winners are…" | `podium-intro.jpg` |
| Reveal steps | `reveal-3rd.jpg`, `reveal-2nd.jpg`, `reveal-1st.jpg` |
| Final results | `final-results.jpg` |
| Reduced motion, a 20-character name, the winner's phone | `reduced-motion-and-long-name.jpg` |

## Bundle size (gzip, `scripts/bundle_budget.py`)

| Bundle | Before | After | Budget |
|---|---|---|---|
| Student page JS | 13.8 KB | 15.1 KB | 20 KB |
| Student page CSS | 6.8 KB | 8.1 KB | 10 KB |
| Teacher Octagon view (loaded on demand) | 11.5 KB | 15.0 KB | 16 KB |
| Main app CSS | 26.9 KB | 29.5 KB | 34 KB |

No libraries were added: animations are CSS keyframes and the Web Animations API.
