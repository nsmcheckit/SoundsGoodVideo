"""The mix: continuous bed, narration EQ, band-split ducking, slow levelling, final loudness.

The numbers come from the mix Jee approved on the third episode.
"""
import json
import subprocess

import numpy as np
import pyloudnorm as pyln
import scipy.signal as ss
import soundfile as sf

from .core import SR, read_json, run, write_json
from .measure import to_wav

BED_REF = -18.0
VO_LUFS = -16.0
BED_TARGET = -17.0
DUCK_LOW, DUCK_MID, DUCK_HIGH = -12.0, -8.0, -12.0
SPLIT_LOW, SPLIT_HIGH = 250, 2500


def db(x):
    return 10 ** (np.asarray(x) / 20)


def _source_wav(ep, key):
    music = ep.data["sources"].get("music", {})
    video = ep.data["sources"].get("video", {})
    path = ep.path((music.get(key) or video[key])["path"])
    return to_wav(path, ep.build / "audio" / f"{key}.wav", SR)


def _peq(f0, gain, q):
    A = 10 ** (gain / 40)
    w = 2 * np.pi * f0 / SR
    al = np.sin(w) / (2 * q)
    b = np.array([1 + al * A, -2 * np.cos(w), 1 - al * A])
    a = np.array([1 + al / A, -2 * np.cos(w), 1 - al / A])
    return b / a[0], a / a[0]


def vo_eq(x):
    """Pulls the low-mid weight that was masking voices in the source, and adds a little presence."""
    y = ss.sosfilt(ss.butter(2, 90, "hp", fs=SR, output="sos"), x)
    for f0, gain, q in [(250, -4.0, 0.9), (1400, -2.5, 1.2), (4500, 2.5, 0.9)]:
        b, a = _peq(f0, gain, q)
        y = ss.lfilter(b, a, y)
    return y.astype(np.float32)


def _short_term(x, hop, win=3.0):
    k = int(win * SR)
    out = []
    for i in range(0, len(x), hop):
        seg = x[max(0, i - k // 2): i + k // 2]
        out.append(10 * np.log10(np.mean(seg.astype(np.float64) ** 2) + 1e-12) - 0.691 + 3.0)
    return np.array(out)


def _smooth(x, att, rel):
    y = np.empty_like(x)
    aa, ar = np.exp(-48 / (att * SR)), np.exp(-48 / (rel * SR))
    v = 0.0
    for i in range(0, len(x), 48):
        target = x[i]
        c = aa if target < v else ar
        v = c * v + (1 - c) * target
        y[i: i + 48] = v
    return y


def build_bed(ep, tl):
    N = int(round(tl["total"] * SR))
    bed = np.zeros((N, 2), np.float32)
    clip_mask = np.zeros(N, bool)
    meter = pyln.Meter(SR)
    cache, gain = {}, {}
    items = tl["bed"]
    for n, it in enumerate(items):
        key = it["src"]
        if key not in cache:
            y, _ = sf.read(str(_source_wav(ep, key)), always_2d=True, dtype="float32")
            cache[key] = y
            gain[key] = float(BED_REF - meter.integrated_loudness(y))
        src = cache[key]
        fade_in = (items[n - 1]["xf"] if items[n - 1]["clip"] else it["xf"]) if n > 0 else 0.3
        fade_out = items[n + 1]["xf"] if n + 1 < len(items) else 1.5
        if it["clip"]:
            fade_out = it["xf"]
        elif n + 1 < len(items) and items[n + 1]["clip"]:
            fade_out = items[n + 1]["xf"]
        half_in, half_out = fade_in / 2, fade_out / 2
        s0 = max(0.0, it["in"] - half_in)
        lead = it["in"] - s0
        length = it["dur"] + lead + half_out
        a, b = int(s0 * SR), int((s0 + length) * SR)
        seg = src[a: b].copy()
        if len(seg) == 0:
            continue
        p0 = int(round((it["t"] - lead) * SR))
        if p0 < 0:
            seg, p0 = seg[-p0:], 0
        seg = seg[: max(0, N - p0)]
        m = len(seg)
        env = np.ones(m, np.float32)
        ni = min(m, int(fade_in * SR))
        if ni:
            env[:ni] = np.sin(np.linspace(0, np.pi / 2, ni)) if n > 0 else np.linspace(0, 1, ni)
        no = min(m, int(fade_out * SR))
        if no:
            env[-no:] *= np.cos(np.linspace(0, np.pi / 2, no))
        bed[p0: p0 + m] += seg * env[:, None] * float(db(gain[key]))
        if it["clip"]:
            clip_mask[p0: p0 + m] = True
    return bed, clip_mask


def build_vo(ep, tl):
    N = int(round(tl["total"] * SR))
    vo = np.zeros(N, np.float32)
    paras = {p["id"]: p for p in read_json(ep.build / "vo" / "paras.json")}
    for v in tl["vo"]:
        y, _ = sf.read(str(ep.build / "vo" / paras[v["id"]]["file"]), dtype="float32")
        p0 = int(round(v["t"] * SR))
        y = y[: max(0, N - p0)]
        vo[p0: p0 + len(y)] += y
    active = np.abs(vo) > 1e-4
    vo = vo_eq(vo)
    meter = pyln.Meter(SR)
    vo *= float(db(VO_LUFS - meter.integrated_loudness(vo[active])))
    return vo


def _duck_curve(vo):
    w = int(0.03 * SR)
    env = np.sqrt(np.convolve(vo.astype(np.float64) ** 2, np.ones(w) / w, "same"))
    active = (env > db(-45)).astype(np.float64)
    k = int(0.7 * SR)
    active = np.convolve(active, np.ones(k), "same") > 0
    look = int(0.12 * SR)
    active = np.concatenate([active[look:], np.zeros(look, bool)])
    return _smooth(np.where(active, -11.0, 0.0), 0.08, 0.45) / -11.0


def band(x, lo, hi):
    return ss.sosfiltfilt(ss.butter(4, [lo, hi], "bandpass", fs=SR, output="sos"), x, axis=0)


def _rms_db(x):
    return float(10 * np.log10(np.mean(np.asarray(x, np.float64) ** 2) + 1e-12))


def mix(ep, tl=None, lufs=-16.0, out_name="mix.wav"):
    tl = tl or read_json(ep.build / "timeline.json")
    bed, clip_mask = build_bed(ep, tl)
    vo = build_vo(ep, tl)
    N = len(vo)
    hop = int(0.1 * SR)
    L = _short_term(bed, hop)
    correction = np.clip((BED_TARGET - L) * 0.55, -6, 5)
    correction[L < -55] = 0
    correction[clip_mask[::hop][: len(correction)]] = 0
    win = min(31, len(correction) - (1 - len(correction) % 2))
    if win >= 5:
        correction = ss.savgol_filter(correction, win, 2)
    level = np.interp(np.arange(N) / SR, np.arange(len(correction)) * 0.1, correction)
    amount = _duck_curve(vo)
    lo = ss.sosfiltfilt(ss.butter(4, SPLIT_LOW, "lp", fs=SR, output="sos"), bed, axis=0)
    hi = ss.sosfiltfilt(ss.butter(4, SPLIT_HIGH, "hp", fs=SR, output="sos"), bed, axis=0)
    mid = bed - lo - hi
    lv, dn = level[:, None], amount[:, None]
    ducked = (lo * db(lv + DUCK_LOW * dn) + mid * db(lv + DUCK_MID * dn) + hi * db(lv + DUCK_HIGH * dn)).astype(np.float32)
    voice = vo * float(db(-0.5))
    raw = ducked + np.stack([voice, voice], 1)
    build = ep.build / "audio"
    build.mkdir(parents=True, exist_ok=True)
    sf.write(str(build / "mix_raw.wav"), raw, SR, subtype="FLOAT")
    limited = build / "mix_lim.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", build / "mix_raw.wav", "-af",
         "alimiter=limit=0.89:attack=4:release=60:level=disabled", "-c:a", "pcm_f32le", limited])
    target = f"I={lufs}:TP=-1.5:LRA=11"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(limited), "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = json.loads(r.stderr[r.stderr.rfind("{"):])
    af = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    out = build / out_name
    run(["ffmpeg", "-v", "error", "-y", "-i", limited, "-af", af, "-ar", SR, "-c:a", "pcm_s16le", out])
    metrics = measure_mix(ep, tl, out, ducked, voice, bed)
    write_json(ep.build / "mix_metrics.json", metrics)
    return out, metrics


def measure_mix(ep, tl, out, ducked, voice, bed):
    x, _ = sf.read(str(out), always_2d=True, dtype="float32")
    meter = pyln.Meter(SR)
    integrated = float(meter.integrated_loudness(x))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    peaks = [float(l.split("Peak:")[1].split()[0]) for l in r.stderr.splitlines() if "Peak:" in l and "dBFS" in l]
    active = _duck_curve(voice) > 0.9
    if active.sum() < SR:
        vo_vs_bed = vocal_margin = None
    else:
        vo_vs_bed = _rms_db(voice[active]) - _rms_db(ducked[active])
        vm = band(np.stack([voice, voice], 1), 125, 2000)
        bm = band(ducked, 125, 2000)
        vocal_margin = _rms_db(vm[active]) - _rms_db(bm[active])
    # Level step across each cut, measured on the bed alone, before ducking.
    steps = []
    w = int(2.0 * SR)
    items = tl["bed"]
    for a, b in zip(items, items[1:]):
        p = int(b["t"] * SR)
        xf = int(max(a["xf"], b["xf"]) * SR / 2)
        L0, L1 = _rms_db(bed[max(0, p - xf - w): max(1, p - xf)]), _rms_db(bed[p + xf: p + xf + w])
        steps.append({"t": b["t"], "step_lu": round(L1 - L0, 1), "clip": b["clip"] or a["clip"]})
    hop = int(0.5 * SR)
    st = _short_term(bed, hop)
    gaps = []
    for i in np.where(st < -50)[0]:
        gaps.append(round(float(i * 0.5), 1))
    return {"integrated_lufs": round(integrated, 2), "true_peak_db": round(max(peaks), 2) if peaks else None,
            "vo_over_bed_db": None if vo_vs_bed is None else round(vo_vs_bed, 1),
            "vocal_band_margin_db": None if vocal_margin is None else round(vocal_margin, 1),
            "cut_steps": steps, "bed_dropouts": gaps}
