"""Signal measurements for a music source: tempo grid, section boundaries, loudness, bands, width, bass pitch.

It never names instruments. Anything about what an instrument *is* goes on the listening sheet.
"""
import warnings

import librosa
import numpy as np
import pyloudnorm as pyln
import scipy.signal as ss
import soundfile as sf
from PIL import Image, ImageDraw

from .core import run, write_json

warnings.filterwarnings("ignore")
AN_SR, HOP = 22050, 512


def to_wav(src, dst, sr=48000):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vn", "-ac", "2", "-ar", sr, "-c:a", "pcm_s16le", dst])
    return dst


def _novelty(F, fps_in, win_s=6.0):
    """Checkerboard novelty on a self-similarity matrix, at about 4 frames per second."""
    k = max(1, int(round(fps_in / 4)))
    rate = fps_in / k
    n = F.shape[1] // k
    F = F[:, :n * k].reshape(F.shape[0], n, k).mean(2)
    F = librosa.util.normalize(F, axis=0)
    R = F.T @ F
    L = int(win_s * rate)
    sign = np.r_[np.ones(L), -np.ones(L)]
    g = np.outer(sign, sign) * np.outer(ss.windows.gaussian(2 * L, L / 2), ss.windows.gaussian(2 * L, L / 2))
    out = np.zeros(len(R))
    for i in range(L, len(R) - L):
        out[i] = np.sum(R[i - L: i + L, i - L: i + L] * g)
    return np.arange(len(out)) / rate, out


def boundaries(y, sr):
    fps = sr / HOP
    features = [
        librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP),
        librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20, hop_length=HOP),
        np.log(librosa.feature.melspectrogram(y=y, sr=sr, hop_length=HOP, n_mels=64) + 1e-6),
    ]
    total = None
    for F in features:
        t, n = _novelty(F, fps)
        n = np.clip(n, 0, None)
        n = n / (n.max() + 1e-9)
        total = n if total is None else total + n
    total /= 3.0
    peaks, _ = ss.find_peaks(total, distance=16, height=0.18)
    return [{"t": round(float(t[i]), 2), "strength": round(float(total[i]), 3)} for i in peaks]


def _fit_tempo(env, fps, t0, t1, lo=70.0, hi=180.0):
    """A fixed tempo and phase for one stretch. More stable than a tracking beat follower on sustained sections."""
    a, b = int(t0 * fps), int(t1 * fps)
    e = env[a:b]
    if len(e) < fps * 6 or e.max() <= 0:
        return None
    e = e - e.mean()
    ac = np.correlate(e, e, "full")[len(e) - 1:]
    lags = np.arange(int(fps * 60 / hi), min(int(fps * 60 / lo), len(ac) - 1))
    if len(lags) < 5:
        return None
    peaks, _ = ss.find_peaks(ac[lags])
    if not len(peaks):
        return None
    scored = []
    for p in peaks[np.argsort(ac[lags][peaks])[::-1][:6]]:
        bpm = 60.0 * fps / lags[p]
        # Favour the range these tracks actually live in; halves and doubles score worse.
        prior = np.exp(-0.5 * (np.log2(bpm / 125.0) / 0.55) ** 2)
        scored.append((ac[lags][p] * prior, bpm))
    bpm0 = max(scored)[1]
    smooth = np.convolve(e, ss.windows.hann(5) / ss.windows.hann(5).sum(), "same")
    axis = np.arange(len(smooth))
    best = None
    # The autocorrelation is only accurate to about a frame, so the search has to reach past that.
    span = max(3.0, bpm0 ** 2 / (60.0 * fps) * 1.5)
    for bpm in np.arange(bpm0 - span, bpm0 + span, 0.02):
        period = 60.0 * fps / bpm
        pulses = np.arange(0, (len(e) - period) / period) * period
        for ph in np.linspace(0, period, 32, endpoint=False):
            score = np.interp(ph + pulses, axis, smooth).sum()
            if best is None or score > best[0]:
                best = (score, bpm, ph / fps + t0)
    return {"bpm": float(best[1]), "phase": float(best[2])}


def _low_phase(low_env, env, fps, bpm, phase, t0, t1):
    """Moves the grid onto the kick. Off-beat hats can otherwise win the broadband phase search."""
    a, b = int(t0 * fps), int(t1 * fps)
    e = low_env[a:b]
    if len(e) < fps * 4 or e.std() < 1e-6:
        return phase
    period = 60.0 * fps / bpm
    pulses = np.arange(0, (len(e) - period) / period) * period
    axis = np.arange(len(e))
    best, best_score, scores = phase, -1e18, []
    for ph in np.linspace(0, period, 32, endpoint=False):
        score = float(np.interp(ph + pulses, axis, np.convolve(e, np.ones(3) / 3, "same")).sum())
        scores.append(score)
        if score > best_score:
            best_score, best = score, ph / fps + t0
    # Only trust the low end when it actually pulses; a sustained bass leaves the broadband answer in place.
    return best if best_score > np.median(scores) * 1.6 + 1e-9 else phase


def _downbeat(low, fps, bpm, phase, t0, t1, beats=4):
    """Picks which beat of the bar is the one, from where the low end hits hardest."""
    beat = 60.0 / bpm
    scores = np.zeros(beats)
    k = 0
    while True:
        t = phase + k * beat
        if t >= t1:
            break
        i = int(t * fps)
        if t >= t0 and 0 <= i < len(low):
            scores[k % beats] += low[min(len(low) - 1, i + 1)]
        k += 1
    return phase + int(np.argmax(scores)) * beat


def tempo_map(y, sr, cuts):
    fine = HOP // 2
    fps = sr / fine
    p = librosa.effects.percussive(y, margin=2.0)
    env = librosa.onset.onset_strength(y=p, sr=sr, hop_length=fine, aggregate=np.median)
    S = np.abs(librosa.stft(p, n_fft=2048, hop_length=fine))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low = S[freqs < 150].sum(0)
    dur = len(y) / sr
    edges = [0.0] + [c for c in cuts if 8.0 < c < dur - 8.0] + [dur]
    spans = []
    for a, b in zip(edges, edges[1:]):
        if b - a < 8.0 and spans:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    fits = []
    for a, b in spans:
        f = _fit_tempo(env, fps, a, b)
        if f:
            fits.append({"start": a, "end": b, **f})
    merged = []
    for f in fits:
        if merged and abs(merged[-1]["bpm"] - f["bpm"]) < 0.4:
            merged[-1]["end"] = f["end"]
            merged[-1]["ends"] = merged[-1].get("ends", 1) + 1
        else:
            merged.append(dict(f))
    grids = []
    # Linear, not log: a log difference fires as soon as the window touches the hit, about half a window early.
    low_env = np.r_[0.0, np.maximum(0.0, np.diff(low))]
    for f in merged:
        refit = _fit_tempo(env, fps, f["start"], f["end"]) or f
        phase = _low_phase(low_env, env, fps, refit["bpm"], refit["phase"], f["start"], f["end"])
        offset = _downbeat(low, fps, refit["bpm"], phase, f["start"], f["end"])
        grids.append({"start": round(f["start"], 3), "end": round(f["end"], 3), "bpm": round(refit["bpm"], 2),
                      "offset": round(offset, 4), "bar_beats": 4})
    return grids


def note_name(hz):
    return librosa.hz_to_note(hz) if hz and hz > 0 else None


def analyze(wav_path, out_json, out_png):
    y_st, sr_st = sf.read(str(wav_path), always_2d=True)
    meter = pyln.Meter(sr_st)
    integrated = float(meter.integrated_loudness(y_st))
    peak = float(20 * np.log10(np.abs(y_st).max() + 1e-12))
    y = librosa.resample(y_st.mean(1).astype(np.float32), orig_sr=sr_st, target_sr=AN_SR)
    sr = AN_SR
    dur = len(y) / sr
    bnd = boundaries(y, sr)
    grids = tempo_map(y, sr, [b["t"] for b in bnd if b["strength"] > 0.3])

    edges = [0.0] + [b["t"] for b in bnd] + [dur]
    fps = sr / HOP
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    harm, perc = librosa.decompose.hpss(S, margin=2.0)
    bands = {"sub": (20, 80), "low": (80, 250), "mid": (250, 2000), "high": (2000, 11000)}
    sections = []
    for a, b in zip(edges, edges[1:]):
        if b - a < 0.5:
            continue
        i, j = int(a * fps), max(int(a * fps) + 1, int(b * fps))
        seg = y_st[int(a * sr_st): int(b * sr_st)]
        row = {"start": round(a, 2), "end": round(b, 2)}
        try:
            row["lufs"] = round(float(meter.integrated_loudness(seg)), 1) if len(seg) > sr_st * 0.5 else None
        except ValueError:
            row["lufs"] = None
        total_e = S[:, i:j].sum() + 1e-12
        for name, (lo, hi) in bands.items():
            row[name + "_pct"] = round(100 * float(S[(freqs >= lo) & (freqs < hi)][:, i:j].sum() / total_e), 1)
        row["percussive_pct"] = round(100 * float(perc[:, i:j].sum() / (perc[:, i:j].sum() + harm[:, i:j].sum() + 1e-12)), 1)
        m, s = seg.mean(1), (seg[:, 0] - seg[:, 1]) / 2
        row["width"] = round(float(np.sqrt((s ** 2).mean() / ((m ** 2).mean() + 1e-12))), 3)
        low_band = S[freqs < 200][:, i:j]
        if low_band.size:
            idx = np.argmax(low_band.mean(1))
            row["bass_hz"] = round(float(freqs[freqs < 200][idx]), 1)
            row["bass_note"] = note_name(row["bass_hz"]) if row["bass_hz"] > 20 else None
        sections.append(row)

    st_win = int(3.0 * sr_st)
    hop = int(0.5 * sr_st)
    curve = []
    for k in range(0, max(1, len(y_st) - st_win // 2), hop):
        seg = y_st[max(0, k - st_win // 2): k + st_win // 2]
        ms = np.mean(seg.astype(np.float64) ** 2) + 1e-12
        curve.append(round(float(10 * np.log10(ms) - 0.691 + 3.0), 1))

    data = {"duration": round(dur, 3), "integrated_lufs": round(integrated, 1), "sample_peak_db": round(peak, 1),
            "grid": grids, "boundaries": bnd, "sections": sections, "st_loudness_2hz": curve}
    write_json(out_json, data)
    plot(y, sr, data, out_png)
    return data


def plot(y, sr, data, out_png):
    """A wide picture of the track for looking at, not for the video."""
    W, H = 2200, 620
    M = librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128, hop_length=HOP, fmax=11000), ref=np.max)
    v = np.clip((M + 70) / 70, 0, 1)[::-1]
    idx = np.linspace(0, v.shape[1] - 1, W).astype(int)
    v = v[:, idx]
    img = np.stack([40 + 215 * v ** 0.8, 30 + 180 * v ** 1.1, 20 + 90 * v ** 1.6], -1).astype(np.uint8)
    im = Image.fromarray(img).resize((W, 480)).convert("RGB")
    canvas = Image.new("RGB", (W, H), (10, 9, 8))
    canvas.paste(im, (0, 0))
    d = ImageDraw.Draw(canvas)
    dur = data["duration"]
    X = lambda t: int(t / dur * W)
    for b in data["boundaries"]:
        d.line([X(b["t"]), 0, X(b["t"]), 480], fill=(229, 67, 47), width=2 if b["strength"] > 0.3 else 1)
        d.text((X(b["t"]) + 3, 4), f"{int(b['t'] // 60)}:{b['t'] % 60:04.1f}", fill=(255, 241, 214))
    for g in data["grid"]:
        d.line([X(g["start"]), 500, X(g["end"]), 500], fill=(217, 180, 108), width=4)
        d.text((X(g["start"]) + 3, 508), f"{g['bpm']} BPM", fill=(217, 180, 108))
    c = np.array(data["st_loudness_2hz"])
    pts = [(int(i / max(1, len(c) - 1) * W), 610 - int((np.clip(x, -50, 0) + 50) / 50 * 80)) for i, x in enumerate(c)]
    if len(pts) > 1:
        d.line(pts, fill=(255, 241, 214), width=1)
    canvas.save(out_png)
