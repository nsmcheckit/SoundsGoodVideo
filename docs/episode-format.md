# episode.yaml

Every edit decision lives in this file. Timing is written against the narration, so it survives script changes.

```yaml
id: ep04_minghuo
title: 冥火流星
target_seconds: 330
target_tolerance: 0.08        # share of the target allowed either way
lufs: -16                     # -14 for the English cut
owners: ["游戏画面与音乐版权归 S-GAME 所有"]   # must also appear on the end card

speech: {speed: 1.2, seeds: [7, 19]}   # voice defaults to the confirmed Chinese voice
lexicon:
  replace: {"G1": 低音G}      # display text → what the voice is given
  listen: [磷火]              # always on the final listening list

sources:
  music:
    A: {path: assets/ost.wav, hard_boundaries: [168.5]}   # switch points the bed may not cross
  video:
    A01: {path: assets/A01_boss.mp4}
    B01: {path: assets/B01_city.mp4, license: pending}     # pending blocks export

structure:                    # the song-structure bar
  source: A
  segments: [{start: 0, end: 91, label: 一阶段}, {start: 91, end: 205, label: 二阶段}]

listening:                    # one card per open question
  - {id: q1, src: A, in: 271, out: 290, question: 这段主奏是什么？, options: [二胡, 高胡, 京胡, 合成器]}

sections:
  - id: open
    chapter: 开场             # becomes a chapter in the publishing text
    pre: 2.0                  # music-only seconds before the first line
    post: 1.0                 # music-only seconds after the last line
    gap: 0.3                  # pause between paragraphs
    paras:
      - id: p01
        text: 很贴，对吧？
        en: ["Fits, right?"]  # one English sentence per Chinese sentence
        claim: measured       # measured | official | quote | ear | opinion
        optional: true        # offered first if the cut runs long
    music:
      - {src: A, in: 181.0, at: start}   # omit `in` or use continue to carry on from where the source left off
    video:
      - {src: A01, in: 12.0, at: start, look: raw}   # looks: raw, zoom14, fit, gray
      - {src: A01, in: 40.0, at: "p01@对吧"}
    clips:                    # original sound and picture, the bed resumes after
      - {src: B01, in: 4.0, dur: 7.0, at: p01, video: true}
    gfx:
      - {type: tag, at: start+0.3, dur: 4, params: {text: 冥火流星, en: NETHER FLAME METEOR}}
      - {type: steps, at: p01, until: end, full: true, params: {title: 四拍底鼓, rows: [...]}}
```

**Anchors** for `at` and `until`: `start`, `end`, a paragraph id, a phrase in a paragraph (`p03@胡琴`), each with an optional offset (`p03+1.2`).

**Scenes**: `tag` `ask` `title` `big` `stamps` `quote` `compare` `layers` `steps` `curve` `number` `spectro` `loops` `roles` `end`. Add `full: true` for a full-screen scene. One-off scenes go in `sgv/gfx/engine.html`; keep one or two per episode so the series does not turn into a template.

**Exceptions** must state a reason: `reuse: "..."` to replay source material, `through: "..."` to cross a switch point. `free: true` lets a cut ignore the bar grid. `lock: true` keeps a music entry at its exact anchor.
