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

from .core import ASR_MODEL, SR, TTS_MODEL, TTS_SPEED, VOICE_ZH, clean_text, probe_duration, read_json, run, spoken_chars, write_json


def _config(ep):
    s = ep.data.get("speech") or {}
    return {"voice": s.get("voice", VOICE_ZH), "model": s.get("model", TTS_MODEL), "speed": float(s.get("speed", TTS_SPEED)),
            "target_cps": s.get("target_cps", TARGET_CPS), "max_speed": float(s.get("max_speed", MAX_SPEED)),
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


def _split(syl):
    return (syl[:-1], syl[-1]) if syl and syl[-1].isdigit() else (syl, "5")


def _sandhi(tones):
    """Third tone before third tone is spoken as a second tone (底鼓 is said dí gǔ)."""
    out = list(tones)
    for i in range(len(out) - 1):
        if out[i] == "3" and out[i + 1] == "3":
            out[i] = "2"
    return out


def _contraction(a_base, i1, i2, b_base, j1, j2):
    """这一 / 那一 / 哪一 run together as zhèi / nèi / něi in ordinary speech; that is not a dropped word.
    (ep04 v5: every take said 这一下 and 那一层 that way and the export check refused all of them.)"""
    exp, got = list(a_base[i1:i2]), list(b_base[j1:j2])
    if exp == ["yi"] and not got and i1 > 0 and a_base[i1 - 1] in ("zhe", "na"):
        return True
    return len(exp) == 2 and exp[1] == "yi" and exp[0] in ("zhe", "na") and got in (["zhei"], ["nei"], ["zhe"], ["na"])


def compare_reading(expected, heard):
    """Compares by pronunciation, so a homophone typed by the recogniser is not a false alarm.

    Syllables are matched without tones first, then tones are checked one by one. A sandhi second tone
    heard as a first tone is let through: the recogniser cannot separate them and picks the commoner word
    (it hears 底鼓 as 低谷). Every other tone difference is reported.
    """
    a, b = _py(clean_text(expected)), _py(clean_text(heard))
    a_base, a_tone = zip(*[_split(s) for s in a]) if a else ((), ())
    b_base, b_tone = zip(*[_split(s) for s in b]) if b else ((), ())
    spoken = _sandhi(a_tone)
    sm = difflib.SequenceMatcher(None, list(a_base), list(b_base), autojunk=False)
    issues, matched = [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            if _contraction(a_base, i1, i2, b_base, j1, j2):
                matched += j2 - j1
                continue
            issues.append({"expected": " ".join(a[i1:i2]), "heard": " ".join(b[j1:j2])})
            continue
        for i, j in zip(range(i1, i2), range(j1, j2)):
            t = b_tone[j]
            ok = t in (a_tone[i], spoken[i], "5") or (spoken[i] == "2" and a_tone[i] == "3" and t == "1")
            if ok:
                matched += 1
            else:
                issues.append({"expected": a[i], "heard": b[j]})
    total = len(a) + len(b)
    return (round(2 * matched / total, 3) if total else 1.0), issues


def _quietest(x, t0, t1, frame=0.01):
    """Centre of the lowest-energy 10 ms frame between t0 and t1."""
    a, b = max(0, int(t0 * SR)), min(len(x), int(t1 * SR))
    n = int(frame * SR)
    if b - a < 2 * n:
        return (t0 + t1) / 2
    k = (b - a) // n
    energy = (x[a: a + k * n].reshape(k, n) ** 2).mean(1)
    return (a + int(np.argmin(energy)) * n + n // 2) / SR


# Jee, ep04: 4.3 字/秒 felt slow. Takes differ a lot in natural pace (3.3 to 4.0 字/秒 raw on one script), so a fixed
# speed-up leaves some seeds dragging; each take is sped up to the same target instead, within what still sounds natural.
TARGET_CPS = 4.85
MAX_SPEED = 1.42


def _raw_cps(ep, base):
    """Characters per second of a take before any speed-up, measured the way pace.json measures the cut."""
    A = read_json(base.with_suffix(".json"))["alignment"]
    ch, st, en = A["characters"], A["character_start_times_seconds"], A["character_end_times_seconds"]
    text, pos, dur, voiced = "".join(ch), 0, 0.0, 0
    for p in ep.paras:
        s = ep.spoken(p)
        i = text.find(s, pos)
        if i < 0:
            return None
        pos = i + len(s)
        words = [k for k in range(i, pos) if re.match(r"\w", ch[k])]
        dur += en[words[-1]] - st[words[0]]
        voiced += spoken_chars(s)
    return voiced / dur if dur else None


def take_speed(ep, base):
    """The speed-up for this take, and whether it had to stop short of the target pace."""
    cfg = _config(ep)
    raw = _raw_cps(ep, base) if cfg["target_cps"] else None
    if not raw:
        return cfg["speed"], False
    want = float(cfg["target_cps"]) / raw
    return round(min(max(want, 1.0), cfg["max_speed"]), 3), want > cfg["max_speed"]


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
    paras, pos, spans = ep.paras, 0, []
    spoken = [ep.spoken(p) for p in paras]
    tail = int(0.012 * SR)
    for p, s in zip(paras, spoken):
        i = text.find(s, pos)
        if i < 0:
            raise SystemExit(f"take does not contain paragraph {p['id']}: the model changed the text")
        pos = i + len(s)
        words = [k for k in range(i, pos) if re.match(r"\w", ch[k])]
        spans.append((i, pos, words[0], words[-1]))
    # The model's character times run late against the audio, so cutting just before a word can clip it.
    # Each boundary goes at the quietest point between the last word of one paragraph and the first of the next.
    cuts = [max(0.0, st[spans[0][2]] - 0.15)]
    for (_, _, _, last), (_, _, first, _) in zip(spans, spans[1:]):
        cuts.append(_quietest(x, en[last] - 0.05, st[first] + 0.05))
    cuts.append(min(len(x) / SR, en[spans[-1][3]] + 0.3))
    out = []
    for n, (p, s) in enumerate(zip(paras, spoken)):
        i, j = spans[n][0], spans[n][1]
        a, b = cuts[n], cuts[n + 1]
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
        pad = np.zeros(4000, np.float32)  # a quarter second of silence so the first syllable is not dropped
        heard = transcribe(engine, np.concatenate([pad, y16, pad]))
        ratio, issues = compare_reading(p["text"], heard)
        report.append({"id": p["id"], "ratio": ratio, "heard": heard, "issues": issues})
        total += ratio * len(p["text"])
    return total / max(1, sum(len(p["text"]) for p in paras)), report


def hard_errors(report):
    """Lines the export check would refuse: far off the script, or with a syllable missing."""
    return sum(1 for row in report if row["ratio"] < 0.82
               or any(len(i["heard"].split()) < len(i["expected"].split()) for i in row["issues"]))


def _pace(paras):
    return sum(spoken_chars(p["text"]) for p in paras) / max(1e-6, sum(p["dur"] for p in paras))


def build(ep, seeds=None):
    """Generates takes, scores each one and installs the best as the episode narration."""
    bases = generate(ep, seeds)
    engine = asr_engine()
    results = []
    for b in bases:
        speed, short = take_speed(ep, b)
        paras = _cut(ep, b, speed)
        target, cap = _config(ep)["target_cps"], _config(ep)["max_speed"]
        cps = _pace(paras)
        if target and not short and abs(cps - target) > 0.03 * target:
            # The cut adds a little air around each paragraph, so correct once against the measured pace.
            want = speed * float(target) / cps
            speed, short = round(min(max(want, 1.0), cap), 3), want > cap
            paras = _cut(ep, b, speed)
        score, report = score_take(ep, paras, engine)
        results.append({"take": b.name, "score": round(score, 4), "seconds": round(sum(p["dur"] for p in paras), 1),
                        "speed": speed, "short": short, "paras": paras, "report": report})
    for r in results:
        r["hard"] = hard_errors(r["report"])
    # A take that swallows a syllable loses to a slightly lower-scoring one that does not (ep04 v5: seed 7 scored
    # higher but said "这下" for "这一下"); voice.dropped would refuse to export it anyway.
    best = min(results, key=lambda r: (r["hard"], r["short"], -r["score"]))
    write_json(ep.build / "vo" / "paras.json", best["paras"])
    write_json(ep.build / "vo" / "reading.json", {
        "take": best["take"], "score": best["score"], "report": best["report"],
        "speed": best["speed"],
        "others": [{"take": r["take"], "score": r["score"], "hard": r["hard"], "speed": r["speed"], "seconds": r["seconds"]} for r in results]})
    write_json(ep.build / "vo" / "pace.json", {"chars_per_second": round(_pace(best["paras"]), 2), "seconds": best["seconds"], "speed": best["speed"]})
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


__all__ = ["build", "generate", "install_placeholder", "compare_reading", "hard_errors", "probe_duration"]
