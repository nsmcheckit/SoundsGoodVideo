"""Picture assembly: one cached segment per shot, then a single final pass for strip, watermark, subtitles and audio."""
import json
import subprocess
from pathlib import Path

from .core import FPS, digest, file_key, run, to_frames, write_json

LOOKS = {
    "raw": "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1",
    # Pushes in far enough to lose the game's own burned-in subtitles.
    "zoom14": "scale=2189:1231:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1",
    "fit": "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x070605,setsar=1",
    "gray": "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,hue=s=0,setsar=1",
}


def _vertical(chain):
    """Blurred full-bleed background, with the game picture large and centred at 4:3."""
    return (f"{chain},split[va][vb];[va]scale=-2:1920,crop=1080:1920,boxblur=24:2,eq=brightness=-0.28[vbg];"
            "[vb]crop=1440:1080:240:0,scale=1080:810[vfg];[vbg][vfg]overlay=0:515,setsar=1")


def _input_for(ep, item):
    if item["src"].startswith("gfx:"):
        return None
    return ep.path(ep.video(item["src"])["path"])


def segment(ep, tl, render, idx, bounds, orient, folder):
    item = sorted(tl["video"], key=lambda v: v["t"])[idx]
    f0, f1 = bounds[idx], bounds[idx + 1]
    nf = f1 - f0
    g0, dur = f0 / FPS, nf / FPS
    overlays = []
    for g in tl["gfx"]:
        if g["full"]:
            continue
        a, b = to_frames(g["t"]), to_frames(g["t"] + g["dur"])
        if a < f1 and b > f0:
            overlays.append((render["scenes"][g["id"]], (a - f0) / FPS))
    gfx_full = item["src"].startswith("gfx:")
    src = render["scenes"][item["src"][4:]] if gfx_full else str(_input_for(ep, item))
    key = digest(orient, file_key(src), item["in"], nf, item["look"], item.get("speed", 1.0),
                 *[f"{Path(o[0]).name}@{o[1]:.3f}" for o in overlays])
    out = folder / f"seg_{key}.mp4"
    if out.exists():
        return out
    speed = float(item.get("speed", 1.0))
    inputs, parts = [], []
    if gfx_full:
        inputs += ["-i", src]
        canvas = {"h": "0x070605", "v": "0x070605"}[orient]
        w, h = (1920, 1080) if orient == "h" else (1080, 1920)
        parts.append(f"color=c={canvas}:s={w}x{h}:r={FPS}:d={dur + 0.2:.3f}[bgc];"
                     f"[0:v]fps={FPS},setpts=PTS-STARTPTS[fg];[bgc][fg]overlay=0:0:eof_action=repeat,setsar=1[base]")
    else:
        inputs += ["-ss", f"{item['in']:.3f}", "-t", f"{dur * speed + 0.3:.3f}", "-i", src]
        chain = f"fps={FPS},setpts=(PTS-STARTPTS)/{speed},{LOOKS[item['look']]}"
        body = _vertical(chain) if orient == "v" else chain
        parts.append(f"[0:v]{body},tpad=stop=-1:stop_mode=clone[base]")
    label = "base"
    for j, (mov, rel) in enumerate(overlays):
        inputs += ["-i", mov]
        k = j + 1
        trim = f"trim=start={-rel:.3f}," if rel < 0 else ""
        shift = f"+{max(rel, 0):.3f}/TB"
        parts.append(f"[{k}:v]{trim}setpts=PTS-STARTPTS{shift}[o{k}];[{label}][o{k}]overlay=0:0:eof_action=pass[l{k}]")
        label = f"l{k}"
    parts.append(f"[{label}]trim=end_frame={nf},setpts=PTS-STARTPTS,format=yuv420p[v]")
    tmp = out.with_suffix(".tmp.mp4")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-frames:v", nf, "-r", FPS,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-an", tmp])
    tmp.rename(out)
    return out


def assemble(ep, tl, render, orient, audio, out_path):
    folder = ep.build / f"seg_{orient}"
    folder.mkdir(parents=True, exist_ok=True)
    shots = sorted(tl["video"], key=lambda v: v["t"])
    bounds = [to_frames(v["t"]) for v in shots] + [to_frames(tl["total"])]
    bounds[0] = 0
    segs = [segment(ep, tl, render, i, bounds, orient, folder) for i in range(len(shots))]
    concat = folder / "concat.txt"
    concat.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    end_cards = [g for g in tl["gfx"] if g["type"] == "end"]
    wm_until = end_cards[0]["t"] if end_cards else tl["total"]
    inputs = ["-f", "concat", "-safe", "0", "-i", concat, "-loop", "1", "-i", render["wm"], "-i", audio]
    fc = [f"[0:v]setpts=PTS-STARTPTS[b0];[b0][1:v]overlay=0:0:shortest=1:enable='lt(t,{wm_until:.3f})'[b1]"]
    label = "b1"
    if render.get("map"):
        inputs += ["-i", render["map"]]
        x, y = render["map_pos"]
        fc.append(f"[3:v]setpts=PTS-STARTPTS[m];[{label}][m]overlay={x}:{y}:eof_action=pass[b2]")
        label = "b2"
    ass = ep.build / f"subs_{orient}.ass"
    fc.append(f"[{label}]ass={ass},fps={FPS},format=yuv420p,setsar=1[v]")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "2:a", "-t", f"{tl['total']:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", FPS,
         "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", out_path])
    return out_path


def contact_sheet(video, tl, out, cols=6, width=480):
    """Frames at each graphics scene and at evenly spaced points, for looking over the finished cut."""
    times = sorted({round(g["t"] + min(g["dur"] * 0.6, 3.0), 2) for g in tl["gfx"]} |
                   {round(tl["total"] * i / 12, 2) for i in range(1, 12)})
    times = [t for t in times if t < tl["total"] - 0.1]
    folder = Path(out).parent / "sheet_frames"
    folder.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, t in enumerate(times):
        p = folder / f"{i:03d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-1", str(p)], check=True)
        frames.append(p)
    run(["ffmpeg", "-v", "error", "-y", "-framerate", 1, "-i", folder / "%03d.jpg", "-vf", f"tile={cols}x{(len(frames) + cols - 1) // cols}", "-frames:v", 1, "-q:v", 3, out])
    write_json(Path(out).with_suffix(".json"), times)
    return out
