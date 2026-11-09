"""Exercises take cutting and the speech-recognition check on a real speech recording, with the voice API stubbed out."""
import shutil
import subprocess
import sys
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_fixture import MANIFEST, fresh  # noqa: E402
from sgv import voice  # noqa: E402
from sgv.core import ASR_MODEL, Episode, read_json, write_json  # noqa: E402

wav = ASR_MODEL / "test_wavs" / "zh.wav"
engine = voice.asr_engine()
y, sr = sf.read(str(wav), dtype="float32")
heard = voice.transcribe(engine, y)
print("recording says:", heard)
from sgv.core import clean_text  # noqa: E402
text = clean_text(heard)
half = len(text) // 2
A, B = text[:half], text[half:]
m = {**MANIFEST, "sections": [{"id": "s", "paras": [{"id": "p1", "text": A}, {"id": "p2", "text": B}], "music": [], "video": []}], "speech": {"speed": 1.0, "seeds": [1]}}
folder = fresh("offline", m)
ep = Episode(folder)
ep.approve("script")


def fake_take(txt, voice_id, model, seed, base):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-ar", "44100", str(base.with_suffix(".mp3"))], check=True)
    n = len(txt)
    dur = len(y) / sr
    write_json(base.with_suffix(".json"), {"text": txt, "alignment": {
        "characters": list(txt),
        "character_start_times_seconds": [i * dur / n for i in range(n)],
        "character_end_times_seconds": [(i + 1) * dur / n for i in range(n)]}})


voice.request_take = fake_take
best = voice.build(ep)
report = read_json(ep.build / "vo" / "reading.json")
print("score", report["score"], [(r["id"], r["ratio"]) for r in report["report"]])
print("files", [p["file"][-12:] for p in read_json(ep.build / "vo" / "paras.json")])
assert report["score"] > 0.6, report
shutil.rmtree(folder)
print("offline voice path ok")
