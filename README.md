# SoundsGood video pipeline

One `episode.yaml` in, reviewed videos out. Code only: episode media, build output and API keys never enter this repo.

## Setup in a new session

```
pip install --break-system-packages -r requirements.txt
mkdir -p .models && cd .models
curl -sSL -o m.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
tar xjf m.tar.bz2 && rm m.tar.bz2
```

The voice key is read from a file named `elevenlabs.key` (attached to the chat, or staged from Jee's folder and passed with `ELEVENLABS_KEY_FILE`). Never put it in a command, a chat message, or a project instruction.

## Order of work

| Step | Command | Who decides |
|---|---|---|
| Measure the music | `python3 -m sgv measure EP` | machine |
| Build the listening sheet | `python3 -m sgv sheet EP` | Jee answers |
| Record the answers | `python3 -m sgv answers EP --file a.json` | machine |
| Check the edit before spending anything | `python3 -m sgv plan EP` | machine |
| Sign off the script | `python3 -m sgv approve EP --gate script` | Jee |
| Voice, two takes, best one kept | `python3 -m sgv voice EP` | machine |
| Mix | `python3 -m sgv mix EP` | machine |
| Graphics, picture, checks, export | `python3 -m sgv render EP` | machine |
| Final listen, using `build/review.md` | | Jee |
| Covers and publishing text | `python3 -m sgv pack EP` | Jee picks and posts |
| Stage files for Jee's 成片 folder | `python3 -m sgv deliver EP`, then write each pair to the device | machine |

`render` refuses to export if a check fails. `--force` writes a file marked `_DRAFT`. Changing any word of narration voids the script approval.

## Jee's folders

`~/Documents/SoundsGood/<视频名>/素材` holds the source footage Jee records; `<视频名>/成片` receives the finished videos, covers and publishing text. Earlier episodes (醉剑千笑, 师尊归位, 嗔恨修罗) only have finished files at the top of their folder. Episode media is linked into `episodes/<id>/assets/` and never committed.

## Tests

```
python3 tests/test_pipeline.py       # plants real past mistakes and asserts each one is stopped
python3 tests/test_voice_offline.py  # take cutting and reading check, API stubbed
python3 tests/gallery.py             # one frame of every scene, for checking by eye
```

See `docs/episode-format.md` for the manifest and `docs/rules.md` for what each check protects.
