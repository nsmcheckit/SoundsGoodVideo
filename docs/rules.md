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
| `script.unconfirmed`, `script.ear_claim` | Suona and electric guitar confused; guqin or guzheng disputed in comments |
| `script.ending`, `end.card`, `end.owners` | Series format and rights lines |
| `license.pending` | Third-party footage needs a decision from Jee |
| `layout.subtitle_clash`, `layout.offscreen`, `layout.safe_zone`, `layout.over_full` | Captions colliding with subtitles; Xiaohongshu 3:4 crop |
| `gate.listening`, `gate.script` | The order Jee set: confirm by ear, then script, then video |

Thresholds for `mix.vocal_masking` have not been calibrated against an approved mix yet. Treat it as a prompt to listen.
