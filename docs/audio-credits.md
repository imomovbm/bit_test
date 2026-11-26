# Audio credits and licensing

**Every sound in TestDuel's Octagon game is synthesized in code by the Web Audio API.** No audio files ship with the
app and none are downloaded at runtime. There are no samples, no recordings, no third-party tracks and nothing that
needs attribution.

| What | Where it is made | Source | Licence |
|---|---|---|---|
| 5 question-music loops | `static/js/octagon/audio.js` (`TRACKS`): note patterns written for this project, played by oscillators and filtered noise | Original, written for this project | Same as the rest of the repository's code |
| Result sounds (cheer, hmm, oops, soft) | same file (`SFX`): short note sequences, pitch slides and envelopes | Original | same |
| Leaderboard whoosh, podium drum roll and three fanfares | same file (`SFX`) | Original | same |
| Last-5-seconds tick | same file (`DRUM.tick`) | Original | same |

How they are made:

- **Instruments.**
  - Square, triangle, sine and sawtooth oscillators with short gain envelopes.
  - "Marimba": a sine plus its 4th harmonic, decaying quickly.
  - "Brass": two slightly detuned sawtooth waves through an opening and closing low-pass filter.
  - Drums: a sine pitch-drop kick; snare, hats, shaker and clap from a 2-second buffer of white noise generated in the
    browser and passed through band-pass or high-pass filters.
- **Melodies.**
  - Four-bar patterns over common chord progressions, such as I–V–vi–IV and I–vi–ii–V. Chord progressions on their
    own are not protected material.
  - The melodies were written for this project as simple arpeggios and scale figures. They are not transcriptions or
    adaptations of existing songs or game themes.

If recorded files are ever added instead, the rule is:

- CC0 or public domain only;
- each file ≤ 150 KB, compressed;
- the source URL and licence of each file listed in this document.
