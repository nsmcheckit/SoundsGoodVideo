"""Renders graphics scenes to alpha video, and caches them by content so a script edit does not re-render everything."""
import base64
import json
import mimetypes
import subprocess
from pathlib import Path

import numpy as np

from .core import FPS, digest, file_key, read_json, to_frames, write_json

ENGINE = Path(__file__).parent / "gfx" / "engine.html"
SIZES = {"h": (1920, 1080), "v": (1080, 1920)}


def engine_key():
    return digest(ENGINE.read_text(encoding="utf-8"))


class Stage:
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.page = self.browser.new_page()
        self.page.goto(ENGINE.as_uri())
        return self

    def __exit__(self, *a):
        self.browser.close()
        self.pw.stop()

    def load_images(self, mapping):
        data = {}
        for key, path in mapping.items():
            mime = mimetypes.guess_type(str(path))[0] or "image/png"
            data[key] = f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()
        if data:
            self.page.evaluate("m => window.load(m)", data)

    def frame(self, kind, params, t, dur, w, h):
        return self.page.evaluate("a => window.draw(...a)", [kind, params, t, dur, w, h])

    def png(self):
        return base64.b64decode(self.page.evaluate("() => window.png()"))


def _images(ep, params):
    keys = []
    if params.get("image"):
        keys.append(params["image"])
    keys += params.get("images") or []
    return {k: ep.path(k) for k in keys}


def render_scene(stage, ep, item, orient, out_dir):
    params = dict(item["params"])
    if item["full"]:
        params["_full"] = True
    images = _images(ep, params)
    key = digest(engine_key(), item["type"], json.dumps(params, sort_keys=True, ensure_ascii=False), item["dur"], orient,
                 *[file_key(p) for p in images.values()])
    out = out_dir / f"{item['id']}_{key}.mov"
    bb_file = out.with_suffix(".bbox.json")
    if out.exists() and bb_file.exists():
        return out, read_json(bb_file)
    stage.load_images(images)
    w, h = SIZES[orient]
    n = max(1, to_frames(item["dur"]))
    tmp = out.with_suffix(".tmp.mov")
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-c:v", "png", "-framerate", str(FPS), "-i", "-",
                          "-c:v", "qtrle", "-pix_fmt", "argb", str(tmp)], stdin=subprocess.PIPE)
    last_sig, last_png, boxes = None, None, []
    for i in range(n):
        r = stage.frame(item["type"], params, i / FPS, item["dur"], w, h)
        if r["sig"] != last_sig:
            last_png, last_sig = stage.png(), r["sig"]
            if i % 3 == 0:
                boxes += r["bb"]
        p.stdin.write(last_png)
    p.stdin.close()
    if p.wait():
        raise RuntimeError(f"encoding failed for {item['id']}")
    tmp.rename(out)
    merged = _merge(boxes)
    write_json(bb_file, merged)
    return out, merged


def _merge(boxes):
    """Union of what a scene ever occupies, kept per distinct box to stay useful for collision checks."""
    seen, out = set(), []
    for b in boxes:
        k = tuple(int(x / 8) for x in b)
        if k not in seen:
            seen.add(k)
            out.append(b)
    return out


def render_static(stage, kind, params, orient, path):
    w, h = SIZES[orient]
    stage.frame(kind, params, 1.0, 10.0, w, h)
    Path(path).write_bytes(stage.png())


def map_strip(ep, tl, orient, out_dir):
    """The song-structure bar: two pre-drawn strips and a moving play head, composited in NumPy."""
    from PIL import Image, ImageDraw, ImageFont
    st = ep.data.get("structure")
    if not st or not tl["map"]:
        return None, None
    W = {"h": 1720, "v": 960}[orient]
    H = 58
    key = digest(json.dumps(st, sort_keys=True, ensure_ascii=False), json.dumps(tl["map"], sort_keys=True), tl["total"], orient, "v2")
    out = out_dir / f"map_{key}.mov"
    pos = {"h": ((1920 - W) // 2, 1014), "v": ((1080 - W) // 2, 1335)}[orient]
    if out.exists():
        return out, pos
    segs = st["segments"]
    length = max(s["end"] for s in segs)
    font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 20, index=2)
    def strip(bright):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for s in segs:
            x0, x1 = int(s["start"] / length * W) + 1, int(s["end"] / length * W) - 1
            color = (217, 180, 108, 235) if bright else (217, 180, 108, 78)
            d.rectangle([x0, H - 12, x1, H - 4], fill=color)
            d.text((x0 + 2, H - 40), s.get("label", ""), font=font,
                   fill=(255, 241, 214, 240 if bright else 110), stroke_width=1, stroke_fill=(0, 0, 0, 170))
        return np.array(im)
    dim, lit = strip(False), strip(True)
    n = to_frames(tl["total"])
    head = np.zeros(n, np.int32) - 1
    for it in tl["map"]["items"]:
        a, b = to_frames(it["t"]), min(n, to_frames(it["t"] + it["dur"]))
        for f in range(a, b):
            head[f] = int(np.clip((it["in"] + (f - a) / FPS) / length * W, 0, W - 1))
    for a, b in tl["map"]["hidden"]:
        head[to_frames(a): to_frames(b)] = -1
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "qtrle", "-pix_fmt", "argb", str(out.with_suffix(".tmp.mov"))], stdin=subprocess.PIPE)
    blank = np.zeros((H, W, 4), np.uint8).tobytes()
    last_x, last = None, blank
    for f in range(n):
        x = int(head[f])
        if x != last_x:
            if x < 0:
                last = blank
            else:
                # Only the segment being played lights up, filled to the play head.
                frame = dim.copy()
                cur = next((s for s in segs if s["start"] / length * W <= x <= s["end"] / length * W), None)
                if cur:
                    x0 = int(cur["start"] / length * W)
                    frame[:, x0: x + 1] = lit[:, x0: x + 1]
                frame[H - 18: H, max(0, x - 1): x + 2] = (255, 241, 214, 255)
                last = frame.tobytes()
            last_x = x
        p.stdin.write(last)
    p.stdin.close()
    if p.wait():
        raise RuntimeError("map strip failed")
    out.with_suffix(".tmp.mov").rename(out)
    return out, pos


def render_all(ep, tl, orient):
    out_dir = ep.build / f"gfx_{orient}"
    out_dir.mkdir(parents=True, exist_ok=True)
    result, boxes = {}, {}
    with Stage() as st:
        for item in tl["gfx"]:
            mov, bb = render_scene(st, ep, item, orient, out_dir)
            result[item["id"]], boxes[item["id"]] = str(mov), bb
        wm = out_dir / "wm.png"
        render_static(st, "wm", {}, orient, wm)
    mp = map_strip(ep, tl, orient, out_dir)
    write_json(ep.build / f"bbox_{orient}.json", boxes)
    return {"scenes": result, "wm": str(wm), "map": str(mp[0]) if mp[0] else None, "map_pos": mp[1]}
