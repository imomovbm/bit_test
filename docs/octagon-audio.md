# Octagon: music and result sounds (teacher screen)

Audio is presentation only. The server stays the source of truth: it computes the share of correct answers from the
real answers and sends a threshold table. The teacher screen picks the sound. Nothing about audio changes the game.

- **Where it plays.** Only on the teacher/projector screen. Student phones stay silent: the student page never loads
  the audio code.
- **How it is made.** Everything is synthesized with the Web Audio API in `static/js/octagon/audio.js`: no files, and
  original by construction ([audio-credits.md](audio-credits.md)).
- **Browser rule.** The `AudioContext` is created or resumed only on a click or key press. That is normally the
  Start click; after a reload it is the "Ovozni yoqish" (Enable sound) button or any other click.

## What plays when

| Phase | Sound |
|---|---|
| `lobby`, `topic_intro` | Nothing |
| `question_read` | The question's music starts with the question text |
| `question_active` | The same music continues without a restart. In the **last 5 s** the tempo rises 6 %, a light tick sounds on every beat and the hi-hats double |
| `question_result` | The music **fades out over 300 ms**. This happens when the timer ends, or as soon as the result arrives if everyone answered. Then the **result sound** plays, starting after the fade so the two never overlap |
| `leaderboard` | A short "whoosh" and two pops |
| `podium_intro` | A drum roll that grows louder until the first place is revealed (4 s at most) |
| `reveal_3rd`, `reveal_2nd`, `reveal_1st` | Fanfares: "ta-daa", then "ta-ta-daa", then the big one with a chord, a cymbal and sparkles |
| `final_results` | Everything stops; a fanfare still playing is cut within 80 ms |

**Event sounds play only on a phase change this page saw itself.** These are the result, whoosh, roll and fanfares.

- After a reload or a late reconnect, the current step is silent, and the music resumes on the same track.
- A timed step that began more than 2.5 s ago is also silent.
- On every phase change the previous event sound is cut over 80 ms, and the next sound starts after that, so a fast
  double click on "Next" never stacks sounds.
- "End" during a question first closes and scores the question, then goes straight to the winners. Its result sound
  is cut before it starts, and the roll plays.

## The 5 tracks

All five are four-bar loops of 64 sixteenth notes in bright major or mixolydian keys. Each loops without a gap because
notes are scheduled on the audio clock about 0.3 s ahead.

| # | Name | Tempo | Key and chords | Instruments and feel |
|---|---|---|---|---|
| 1 | hopscotch | 126 BPM | C major, I–V–vi–IV | Plucky square-wave lead, triangle bass, kick on every beat, offbeat hats |
| 2 | lollipop | 108 BPM, swing | F major, I–vi–ii–V | Flute-like triangle lead with held notes, round sine bass, rim and shaker |
| 3 | zoom | 138 BPM | G mixolydian, I–♭VII–IV–I | Staccato square lead, 8-bit square bass, sixteenth-note triangle arpeggio |
| 4 | marimba | 100 BPM | D major, I–IV–vi–V | Sine "marimba" (fundamental plus 4th harmonic), sine bass, shaker |
| 5 | bubbles | 132 BPM | B♭ major, I–iii–IV–V | Plucked triangle with an octave square, 8-bit bass, syncopated kick, clap |

**Track choice (`trackOrder`, `trackFor`).**

- The seed is the game's PIN plus its creation time (FNV-1a hash, then the mulberry32 generator).
- Every block of 5 questions plays each track once, in a shuffled order.
- At block boundaries the first track is swapped if it equals the previous one, so the same track never plays twice
  in a row.
- The track depends only on (game, question index), so a teacher reload mid-question resumes the same track.

## Result sounds

The server sends two values in `question_result`, both whole percents rounded down:

- `correctPct`: the share of correct answers among the players who answered;
- `answerRate`: the share of players who answered.

Rounding down keeps integer thresholds exact (⌊x⌋ ≥ 60 ⇔ x ≥ 60, so 59.9 % is not "≥ 60 %"). The thresholds and the
mapping are in `app/config.py`:

| Setting | Default | Meaning |
|---|---|---|
| `TD_OCTAGON_SOUND_CHEER` | 60 | `correctPct ≥ 60` → **cheer** |
| `TD_OCTAGON_SOUND_HMM` | 30 | `30 ≤ correctPct < 60` → **hmm**; below 30 → **oops** (`HMM ≤ CHEER`, checked at startup) |
| `TD_OCTAGON_SOUND_NOBODY` | `soft` | Nobody answered → **soft**, or `silent` |

`OCTAGON_RESULT_SOUNDS = ((CHEER, "cheer"), (HMM, "hmm"), (0, "oops"))` is sent to the teacher once per connection
(`sounds` in `HOST_STATIC`). The client's `pickResultSound` walks it top-down. No threshold numbers live in the client.

| Sound | When | How it sounds |
|---|---|---|
| cheer | ≥ 60 % correct | A fast rising C-major arpeggio (square), a bright triangle chord, then high sparkles (~1.3 s) |
| hmm | 30–59 % | Two soft hummed notes rising like a question (A3 → C4), a filtered sawtooth with light vibrato (~1 s) |
| oops | < 30 % | A slide-whistle drop, then a springy "boing". Funny, not harsh (~1 s) |
| soft | Nobody answered | One quiet bell (~1.3 s), or silence with `silent` |

## Controls and settings

- **Bar (every teacher screen).**
  - Mute/unmute button (also the **M** key) and a volume slider.
  - Below 640 px wide the slider moves out of the bar into the lobby.
- **Setup page.**
  - "Ovoz (faqat shu ekranda)" field with the same toggle, the slider and a **Test** button. Test plays the cheer at
    the chosen volume, which is the moment to check the projector speakers.
- **Defaults and storage.**
  - Sound on, volume 60 %. Gain is (volume/100)², so the slider's middle sounds like the middle.
  - Stored on the device only: `td-octagon-sound` (on/off) and `td-octagon-volume` (0–100). This is a UI preference
    that never reaches the server.
  - Moving the slider while muted also unmutes.
- **Blocked audio.**
  - When the browser has not allowed audio yet (a reload, a tab opened in the background, autoplay blocked), the game
    stays silent and a floating **Ovozni yoqish** button appears.
  - The button is `position: fixed`, so nothing on the page moves.
  - Any click or key press on the page also enables sound.
- **Hidden tab.** The `AudioContext` is suspended (no late or glitchy sounds) and resumed on return. The current event
  sound is cut.
- **Leaving the page** (another route, or the game is closed or ended): the engine is disposed.
  - The `AudioContext` is closed.
  - The scheduler interval, timeouts and listeners are removed.
  - Faded buses are disconnected.
  - `pagehide` also stops all sound.

## Performance

| Bundle (gzip, `scripts/bundle_budget.py`) | Before | After |
|---|---|---|
| Student page JS (`/play`) | 15.1 KB | **15.1 KB (unchanged)** |
| Student page CSS | 8.1 KB | **8.1 KB (unchanged)** |
| `js/views/octagon.js` (teacher, lazy) | 15.0 KB | 17.2 KB (controls, setup field, Enable button, deferred load) |
| `js/octagon/audio.js` (new, lazy, teacher only) | — | 10.7 KB |
| Main app CSS | 29.5 KB | 30.0 KB |
| Main app JS (login, duel, …) | 42.9 KB | 42.9 KB (unchanged) |

- `audio.js` is fetched with `import()` on the teacher's game screen, from an idle callback after its first screen is
  drawn so it does not compete with the lobby on slow networks. The setup page fetches it only on a Test click. Other
  pages, including Duel and the student page, never request it. The E2E checks the network log, and
  `bundle_budget.py` fails if the student page ever loads it.
- **Page speed** (`scripts/perf-routes.js`: slow 4G, 4× CPU, median of 5):

  | Route | Before | After |
  |---|---|---|
  | Teacher game screen, cold | 1707 ms | 1743 ms |
  | Teacher game screen, repeat | 968 ms | 955 ms |
  | Student pages | — | Unchanged files; differences are run-to-run noise ([performance.md](performance.md)) |
- **Main thread.**
  - A 100 ms interval schedules notes 0.3 s ahead on the audio clock. That is a few `OscillatorNode`s per sixteenth
    note, and the browser frees them when they stop.
  - The context uses `latencyHint: 'playback'` (larger buffers) for low-end projector laptops.
- **Measured** (E2E, 4× CPU throttling, 4 s of music):
  - no long tasks (> 50 ms);
  - no note scheduled late;
  - the largest gap between beats is 0.28 s (as written in the score);
  - no layout shift caused by audio elements.

## Tests

- **Unit, `node --test 'tests/js/*.test.js'`** (41 tests, Node's built-in runner, no new dependency):
  - **Track order:**
    - no immediate repeats for 400 seeds × 100 questions;
    - every block of 5 is a permutation;
    - shuffled per game;
    - deterministic per question.
  - **Result picker:** 29/30/59/60 %, 0 and 100 %, nobody (soft/silent), one player, thresholds from config, missing
    table.
  - **Phase → plan:** music only in read/active; the stop time is the timer end; tension 5 s before the end; event
    sounds only on observed, fresh transitions.
  - **Config:** 5 distinct tracks, valid pattern lengths, upbeat tempos, loop length unchanged by swing, 300 ms fade.
  - **Engine with a fake `AudioContext` and fake timers:**
    - no context before a click; context created on the first click;
    - a continuous read → active transition; a 300 ms fade at the timer (notes keep playing during the fade, none
      after);
    - the result sound after the fade;
    - the same track after a reload; no replay of the result after a reload;
    - quick double phase changes cut the previous sound first;
    - mute, unmute and volume; muted-from-start never creates a context;
    - blocked autoplay; a background tab shown later; a hidden tab;
    - early end; the podium; dispose (context closed, no timers or listeners);
    - every sound exists.
- **Server, `tests/test_octagon_audio.py`** (pytest, 37 tests):
  - floor percentages at 29/30/59/60 %, 59.9 % and 29.9 %;
  - nobody answered; one player right or wrong; answer rate;
  - values come from real answers (a second answer is ignored; a kicked player is not counted; a late joiner is
    counted);
  - students get no new fields; `sounds` is sent once;
  - config defaults, env overrides and invalid values; snapshots older than this change.
- **Browser, `node e2e/audio.e2e.js`** (Playwright, real Chromium Web Audio).
  - **Instrumentation:**
    - A spy wraps `AudioContext`, `start()`, `linearRampToValueAtTime` and `setTargetAtTime`.
    - It records whether the page had a user activation when each context was created.
    - Engine events arrive over `console.debug`.
  - **Covered (81 checks):**
    - lazy loading;
    - setup-page Test, volume and toggle persistence;
    - the context created on Start;
    - music start and track per question;
    - fade on "everyone answered" and on timer end (the ramp on the real `AudioParam`);
    - cheer, hmm, oops and soft from the server's real percentages;
    - quick double phase changes; hidden tab;
    - mute (gain 0, no notes), volume 30 % → gain 0.09, persisted across a reload;
    - reload mid-question (silent and no context until the click, then the same track);
    - early end (roll, then the fanfares, then all quiet);
    - leaving the page (all contexts closed, no more notes);
    - blocked autoplay → floating button (no layout move), then music after allowing;
    - 360 / 375 / 768 px layouts;
    - 4× slower CPU;
    - five student pages: no `AudioContext`, no audio code requested;
    - **no console errors and no autoplay warnings.**

## Bugs found and fixed

Each bug had a failing test first.

| # | Bug | Test | Fix |
|---|---|---|---|
| A-1 | A game opened in a **background tab** never showed "Ovozni yoqish" when the tab became visible. The visibility handler returned early because there was no `AudioContext` yet. Any click still worked | `tests/js/octagon-audio.test.js` "fon oynada ochilgan sahifa…" | Re-check the status on every visibility change |
| A-2 | The setup page's labelled sound toggle had an accessible name ("Ovozni oʻchirish (M)") that did not contain its visible text ("Musiqa va effektlar"), so voice control could not "click" it | E2E `getByRole('button', {name: 'Musiqa va effektlar'})` | The labelled variant uses its visible text as the name; state is in `aria-pressed` |
| A-3 | At the **timer end** the scheduler stopped adding notes at once. The drums cut off and only note tails faded, which is not a real fade-out | E2E and unit "notes keep playing during the fade, none after" | Notes continue through the 300 ms fade; nothing after it |
| A-4 | The Enable button's pulse animated the button's own `transform`, so it was never "stable" and Playwright could not click it. A permanently moving target is also harder to hit | E2E click on `[data-enable-sound]` | The pulse is a ring on `::after` (transform/opacity only); the button stays still |

Two test-harness findings, documented in `e2e/audio.e2e.js` so later tests do not repeat them:

- Playwright's `page.evaluate`, locators and `exposeBinding` replies all give the page a user activation, which would
  hide the "silent until click" behaviour. After a reload the test reads only `console.debug` events until it clicks.
- The app's general click-sound context (`lib.js`, created on the first click anywhere in the app) is separate from
  Octagon's. The spy tells them apart by `latencyHint: 'playback'`.

## Not verified

- **Real speaker output.** Headless Chromium renders audio to a null device. The tests prove which nodes, notes and
  gain ramps are scheduled and when, but nobody listened. Loudness balance, how "playful" the loops feel and whether
  anything sounds harsh on a real projector still need a person in a classroom.
- **Safari, Firefox and iOS** were not run. The code follows their rules (create or resume only on a gesture,
  fallback without `latencyHint`, `navigator.userActivation` only when present). Safari's "interrupted" state is
  treated like blocked: the button appears.
- **A real low-end laptop** was not used. It was emulated with 4× CPU throttling.
- **Two teacher tabs on the same game** both play audio. This was out of scope.
- **Late fade edge case.** If everyone answers in the last 0.3 s before the timer, the fade can start up to 0.3 s
  late. The scheduler has already queued the timer-end fade.
