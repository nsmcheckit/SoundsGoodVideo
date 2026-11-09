"""Narration: one continuous take, retakes with different seeds, per-paragraph cuts, and a speech-recognition check."""
import base64
import difflib
import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from pypinyin import Style, lazy_pinyin

from .core import ASR_MODEL, SR, TTS_MODEL, TTS_SPEED, VOICE_ZH, clean_text, probe_duration, read_json, run, write_json


def _config(ep):
    s = ep.data.get("speech") or {}
    return {"voice": s.get("voice", VOICE_ZH), "model": s.get("model", TTS_MODEL), "speed": float(s.get("speed", TTS_SPEED)),
            "seeds": s.get("seeds", [7, 19])}


def api_key():
    """The key lives in a file Jee controls, so it never appears in a command, a chat or this repo."""
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"].strip()
    roots = [Path(os.environ["ELEVENLABS_KEY_FILE"])] if os.environ.get("ELEVENLABS_KEY_FILE") else []
    roots.append(Path.home() / ".sgv" / "elevenlabs.key")
    roots += sorted(Path("/mnt/user-data/uploads").glob("**/elevenlabs.key")) if Path("/mnt/user-data/uploads").exists() else []
    for f in roots:
        if f.is_file():
            return f.read_text(encoding="utf-8").strip()
    raise SystemExit("No voice API key. Put it in a file named elevenlabs.key in the connected folder or attach it to the chat.")


def request_take(text, voice, model, seed, out_base):
    key = api_key()
    body = {"text": text, "model_id": model, "seed": seed}
    r = subprocess.run(
        ["curl", "-sS", "-m", "600", "-X", "POST",
         f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128",
         "-H", "xi-api-key: " + key, "-H", "Content-Type: application/json",
         "--data-binary", json.dumps(body, ensure_ascii=False)],
        capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"voice API returned something unreadable: {r.stdout[:200]} {r.stderr[:200]}")
    if "audio_base64" not in d:
        raise SystemExit(f"voice API error: {str(d)[:300]}")
    out_base.with_suffix(".mp3").write_bytes(base64.b64decode(d["audio_base64"]))
    write_json(out_base.with_suffix(".json"), {"text": text, "alignment": d.get("alignment") or d.get("normalized_alignment")})


def generate(ep, seeds=None):
    if not ep.approved("script"):
        raise SystemExit("The script has not been approved, or it changed after approval. Run approve once Jee signs off.")
    cfg = _config(ep)
    folder = ep.build / "vo"
    folder.mkdir(parents=True, exist_ok=True)
    text = "\n\n".join(ep.spoken(p) for p in ep.paras)
    done = []
    for seed in (seeds or cfg["seeds"]):
        base = folder / f"take_{ep.script_hash()}_{seed}"
        if not base.with_suffix(".mp3").exists():
            request_take(text, cfg["voice"], cfg["model"], seed, base)
        done.append(base)
    return done


def asr_engine():
    import sherpa_onnx
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(ASR_MODEL / "model.int8.onnx"), tokens=str(ASR_MODEL / "tokens.txt"), use_itn=False, language="zh")


def transcribe(engine, y16):
    s = engine.create_stream()
    s.accept_waveform(16000, y16)
    engine.decode_stream(s)
    return s.result.text


def _py(s):
    return lazy_pinyin(s, style=Style.TONE3, neutral_tone_with_five=True, errors="ignore")


def compare_reading(expected, heard):
    """Compares by pronunciation, tones included, so a homophone typed by the recogniser is not a false alarm."""
    a, b = _py(clean_text(expected)), _py(clean_text(heard))
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    issues = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            issues.append({"expected": " ".join(a[i1:i2]), "heard": " ".join(b[j1:j2])})
    return round(sm.ratio(), 3), issues


def _cut(ep, base, speed):
    """Speeds the take up, then cuts paragraph files from the character timing."""
    folder = base.parent
    wav = base.with_suffix(".wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", base.with_suffix(".mp3"), "-af", f"atempo={speed}", "-ar", SR, "-ac", 1, wav])
    A = read_json(base.with_suffix(".json"))["alignment"]
    ch = A["characters"]
    st = [x / speed for x in A["character_start_times_seconds"]]
    en = [x / speed for x in A["character_end_times_seconds"]]
    text = "".join(ch)
    x, _ = sf.read(str(wav), dtype="float32")
    paras, pos, out = ep.paras, 0, []
    spoken = [ep.spoken(p) for p in paras]
    tail = int(0.012 * SR)
    for n, (p, s) in enumerate(zip(paras, spoken)):
        i = text.find(s, pos)
        if i < 0:
            raise SystemExit(f"take does not contain paragraph {p['id']}: the model changed the text")
        j = i + len(s)
        pos = j
        idx = [k for k in range(i, j) if re.match(r"\w", ch[k])]
        a = max(st[idx[0]] - 0.06, (en[i - 1] + 0.02) if i > 0 else 0.0)
        b = en[idx[-1]] + 0.12
        if n + 1 < len(paras):
            nx = text.find(spoken[n + 1], j)
            first = [k for k in range(nx, nx + len(spoken[n + 1])) if re.match(r"\w", ch[k])][0]
            b = min(b, st[first] - 0.04)
        seg = x[int(a * SR): int(b * SR)].copy()
        seg[:tail] *= np.linspace(0, 1, tail)
        seg[-tail:] *= np.linspace(1, 0, tail)
        tag = f"{base.name}_{p['id']}.wav"
        sf.write(str(folder / tag), seg, SR)
        out.append({"id": p["id"], "file": tag, "dur": round(len(seg) / SR, 3), "text": s,
                    "chars": [[ch[k], round(st[k] - a, 3), round(en[k] - a, 3)] for k in range(i, j) if not ch[k].isspace()]})
    return out


def score_take(ep, paras, engine):
    folder = ep.build / "vo"
    report, total = [], 0.0
    for p in paras:
        y, _ = sf.read(str(folder / p["file"]), dtype="float32")
        y16 = np.interp(np.arange(0, len(y), 3), np.arange(len(y)), y).astype(np.float32)
        heard = transcribe(engine, y16)
        ratio, issues = compare_reading(p["text"], heard)
        report.append({"id": p["id"], "ratio": ratio, "heard": heard, "issues": issues})
        total += ratio * len(p["text"])
    return total / max(1, sum(len(p["text"]) for p in paras)), report


def build(ep, seeds=None):
    """Generates takes, scores each one and installs the best as the episode narration."""
    bases = generate(ep, seeds)
    speed = _config(ep)["speed"]
    engine = asr_engine()
    results = []
    for b in bases:
        paras = _cut(ep, b, speed)
        score, report = score_take(ep, paras, engine)
        results.append({"take": b.name, "score": round(score, 4), "seconds": round(sum(p["dur"] for p in paras), 1),
                        "paras": paras, "report": report})
    best = max(results, key=lambda r: r["score"])
    write_json(ep.build / "vo" / "paras.json", best["paras"])
    write_json(ep.build / "vo" / "reading.json", {
        "take": best["take"], "score": best["score"], "report": best["report"],
        "others": [{"take": r["take"], "score": r["score"], "seconds": r["seconds"]} for r in results]})
    voiced = sum(len(clean_text(p["text"])) for p in best["paras"])
    write_json(ep.build / "vo" / "pace.json", {"chars_per_second": round(voiced / best["seconds"], 2), "seconds": best["seconds"]})
    return best


def install_placeholder(ep):
    """Silent-but-timed stand-in narration for offline tests, shaped like real speech."""
    from .timeline import estimated_vo
    folder = ep.build / "vo"
    folder.mkdir(parents=True, exist_ok=True)
    vo, out = estimated_vo(ep), []
    rng = np.random.default_rng(3)
    for p in ep.paras:
        v = vo[p["id"]]
        n = int(v["dur"] * SR)
        t = np.arange(n) / SR
        envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 4.3 * t + rng.uniform(0, 6)) ** 2
        y = sum(a * np.sin(2 * np.pi * f * t) for a, f in [(0.5, 180), (0.3, 360), (0.22, 720), (0.12, 2300)])
        y = (y + 0.04 * rng.standard_normal(n)) * envelope * 0.2
        name = f"placeholder_{p['id']}.wav"
        sf.write(str(folder / name), y.astype(np.float32), SR)
        out.append({**v, "file": name})
    write_json(folder / "paras.json", out)
    return out


def duration_check(ep):
    f = ep.build / "vo" / "paras.json"
    return sum(p["dur"] for p in read_json(f)) if f.exists() else None


__all__ = ["build", "generate", "install_placeholder", "compare_reading", "probe_duration"]
