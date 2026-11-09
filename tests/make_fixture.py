"""Builds a small synthetic episode, so the whole pipeline can run without any copyrighted media."""
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sgv.core import run  # noqa: E402

SR = 48000
WORK = Path(__file__).parent / "_work"
# Ground truth the measurement test checks against.
TRUTH = {"bpm": [126.0, 132.0], "switch": 45.714}


def kick(n):
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * (45 * t + 60 * (1 - np.exp(-t * 30)) / 30)) * np.exp(-t * 7)


def hat(n, rng):
    return rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 90) * 0.18


def section(bpm, bars, root, rng, voice=False):
    beat = 60 / bpm
    N = int(bars * 4 * beat * SR)
    x = np.zeros(N)
    for b in range(bars * 4):
        p = int(b * beat * SR)
        k = kick(min(int(0.3 * SR), N - p))
        x[p: p + len(k)] += k * 0.9
        for s in (0.5,):
            q = int((b + s) * beat * SR)
            h = hat(min(int(0.06 * SR), N - q), rng)
            x[q: q + len(h)] += h
    t = np.arange(N) / SR
    x += 0.16 * np.sin(2 * np.pi * root * t)
    x += 0.09 * np.sin(2 * np.pi * root * 4.0 * t + np.sin(2 * np.pi * 0.4 * t))
    if voice:
        x += 0.1 * np.sin(2 * np.pi * root * 8 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 2 * t))
    return x


def make_audio(folder):
    rng = np.random.default_rng(1)
    a = section(126.0, 24, 55.0, rng)
    b = section(132.0, 40, 49.0, rng, voice=True)
    x = np.concatenate([a, b])
    st = np.stack([x, x * 0.92], 1) * 0.5
    sf.write(str(folder / "music.wav"), st.astype(np.float32), SR)
    return TRUTH


def make_video(folder, name, hue, seconds=80):
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=30:d={seconds}",
         "-f", "lavfi", "-i", f"sine=f=330:d={seconds}", "-vf", f"hue=h={hue}:s=0.6,eq=brightness=-0.2",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", folder / name])


MANIFEST = {
    "id": "t01", "title": "测试曲", "target_seconds": 40, "target_tolerance": 0.5,
    "owners": ["测试画面与音乐版权归 SoundsGood 所有"],
    "sources": {"music": {"A": {"path": "assets/music.wav", "hard_boundaries": [45.714]}},
                "video": {"A01": {"path": "assets/a01.mp4"}, "A02": {"path": "assets/a02.mp4"}, "B01": {"path": "assets/b01.mp4"}}},
    "structure": {"source": "A", "segments": [{"start": 0, "end": 22.857, "label": "一阶段"}, {"start": 22.857, "end": 45.714, "label": "铺垫"}, {"start": 45.714, "end": 118.45, "label": "二阶段"}]},
    "cover": {"images": ["assets/cover.png"], "zh": {"title": "测试曲", "sub": "管线验证", "kicker": "BOSS 战音乐拆解", "game": "SOUNDSGOOD 测试"}, "en": {"title": "TEST", "sub": "PIPELINE CHECK", "kicker": "BOSS THEME BREAKDOWN"}, "seal": "曲"},
    "publish": {"B站": {"titles": ["测试标题"], "body": "简介\n\n{chapters}\n\n{owners}", "tags": ["测试"]}},
    "listening": [{"id": "q1", "src": "A", "in": 2.0, "out": 8.0, "question": "这一段的底鼓是四拍吗？", "options": ["是", "不是"]}],
    "sections": [
        {"id": "open", "chapter": "开场", "pre": 2.0, "post": 0.6, "paras": [
            {"id": "p01", "text": "这首曲子一开口，就是满能量。", "en": ["The track starts at full energy."], "claim": "measured"},
            {"id": "p02", "text": "在我听来，这是一条不肯停下的底鼓。", "en": ["To my ears, this is a kick that refuses to stop."], "claim": "ear"}],
         "music": [{"src": "A", "in": 0, "at": "start"}],
         "video": [{"src": "A01", "in": 2.0, "at": "start"}, {"src": "A02", "in": 4.0, "at": "p02"}],
         "gfx": [{"type": "tag", "at": "start+0.3", "dur": 4.5, "params": {"text": "冥火流星", "en": "NETHER FLAME METEOR"}},
                 {"type": "stamps", "at": "p02@底鼓", "until": "end-0.05", "params": {"glyphs": ["鼓"]}}]},
        {"id": "title", "pre": 3.0, "paras": [],
         "gfx": [{"type": "title", "at": "start", "dur": 3.0, "full": True, "params": {"title": "冥火流星", "sub": "Techno 进了武侠", "kicker": "BOSS THEME BREAKDOWN", "seal": "曲"}}]},
        {"id": "body", "chapter": "二阶段", "post": 0.5, "paras": [
            {"id": "p03", "text": "速度从每分钟一百二十六拍，提到一百三十二拍。", "en": ["The tempo rises from 126 to 132."], "claim": "measured"},
            {"id": "p04", "text": "底鼓踩了将近一分钟，这才是 Techno。", "en": ["The kick runs for nearly a minute. This is techno."], "claim": "measured", "optional": True}],
         "music": [{"src": "A", "in": 22.857, "at": "start"}],
         "video": [{"src": "A01", "in": 30.0, "at": "start"}],
         "gfx": [{"type": "steps", "at": "p03", "until": "end", "full": True, "params": {"title": "四拍底鼓", "kicker": "FOUR ON THE FLOOR", "bpm": 132, "rows": [{"name": "底鼓", "hits": [0, 4, 8, 12], "hot": True}, {"name": "踩镲", "hits": [2, 6, 10, 14]}]}}]},
        {"id": "clip", "chapter": "先例", "pre": 0.2, "post": 3.2, "paras": [
            {"id": "p05", "text": "用这种声音写失控，早有先例。", "en": ["There is precedent for this sound."], "claim": "official"}],
         "music": [{"src": "A", "in": "continue", "at": "start"}],
         "video": [{"src": "A02", "in": 30.0, "at": "start"}],
         "clips": [{"src": "B01", "in": 4.0, "dur": 5.0, "at": "p05", "video": True}],
         "gfx": [{"type": "quote", "at": "start", "dur": 3.0, "params": {"text": "以中式音乐为骨，西式音乐为肉。", "source": "薄彩生，采访"}}]},
        {"id": "outro", "chapter": "收尾", "post": 3.0, "paras": [
            {"id": "p06", "text": "更多游戏声音拆解，关注 SoundsGood。", "en": ["More game audio breakdowns: follow SoundsGood."]}],
         "music": [{"src": "A", "in": 75.0, "at": "start"}],
         "gfx": [{"type": "end", "at": "start", "until": "end", "full": True, "params": {"owners": ["测试画面与音乐版权归 SoundsGood 所有"]}}]},
    ],
}


def fresh(name="ep", manifest=MANIFEST):
    """A new episode folder sharing one set of media."""
    media = WORK / "media"
    if not (media / "music.wav").exists():
        media.mkdir(parents=True, exist_ok=True)
        make_audio(media)
        make_video(media, "a01.mp4", 20)
        make_video(media, "a02.mp4", 140)
        make_video(media, "b01.mp4", 260)
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "gradients=s=1600x1200:d=1:c0=0x552211:c1=0x112244", "-frames:v", 1, media / "cover.png"])
    ep = WORK / name
    if ep.exists():
        shutil.rmtree(ep)
    (ep / "assets").mkdir(parents=True)
    for f in media.iterdir():
        (ep / "assets" / f.name).symlink_to(f)
    (ep / "episode.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ep


if __name__ == "__main__":
    print(fresh())
