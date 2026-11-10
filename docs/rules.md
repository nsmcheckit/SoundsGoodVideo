# What each check protects

| Rule | Comes from |
|---|---|
| `music.no_replay`, `video.no_replay` | Episode 3: background kept restarting from the first section |
| `music.bar_cut`, `music.crossfade` | Lion-dance v1: jump cuts in the music |
| `music.switch` | Episode 3: the bed ran across the track's section switch |
| `audio.no_stems` | Episode 3: separated vocals sounded muddy |
| `mix.vo_balance`, `mix.vocal_masking` | Episode 3: narration masked the voices in the source |
| `mix.cut_jump`, `mix.dropout`, `mix.loudness`, `mix.peak` | Lion-dance v1: level swings and sudden silence |
| `duration` | Episode 3 v1 ran almost a minute long |
| `voice.digits`, `voice.latin`, `voice.reading` | 808, 大镲, 丑角, 嗔 |
| `script.timecode` | Jee: tell it as a story, no timestamps in narration |
| `script.names` | Jee: do not name other creators |
| `script.earlier` | Jee: do not refer to earlier episodes |
| `script.spec_density` | Nether Flame Meteor v2: Jee found the arrangement details too fine-grained (Hz, note names, octaves, stereo width, sixteenths). The story carries the episode; at most three hard specs, BPM not counted. An episode can raise the cap with `max_specs` |
| `script.unconfirmed`, `script.ear_claim` | Suona and electric guitar confused; guqin or guzheng disputed in comments |
| `script.ending`, `end.card`, `end.owners` | Series format and rights lines |
| `license.pending` | Third-party footage needs a decision from Jee |
| `layout.subtitle_clash`, `layout.offscreen`, `layout.safe_zone`, `layout.over_full` | Captions colliding with subtitles; Xiaohongshu 3:4 crop |
| `gate.listening`, `gate.script` | The order Jee set: confirm by ear, then script, then video |

`voice.reading` matches syllables first and tones second. A third tone spoken as a second tone before another third tone (底鼓 → dí gǔ) is allowed to come back as a first tone, because the recogniser cannot tell them apart and prefers the commoner word (低谷). Checked on 2026-11-10 by pitch: the take rose about 2 semitones, like the reference 底鼓 and 笛鼓 readings, while 低谷 stayed level or fell.

Thresholds for `mix.vocal_masking` have not been calibrated against an approved mix yet. Treat it as a prompt to listen.
