"""Builds the crumpled-paper textures the gta theme cuts its notes, strips and backgrounds from.
Creases: random V-shaped folds at two scales make a height field, lit from the top left, plus grain.
Run once: python3 sgv/gfx/make_textures.py"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

OUT = Path(__file__).parent / "tex"


def folds(w, h, n, rng, scale):
    """Height field of creases: each fold is a V along a random line that fades away from its centre."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    hf = np.zeros((h, w), np.float32)
    for _ in range(n):
        cx, cy = rng.random() * w, rng.random() * h
        ang = rng.random() * np.pi
        nx, ny = np.cos(ang), np.sin(ang)
        d = (xx - cx) * nx + (yy - cy) * ny
        r = scale * (0.5 + rng.random())
        fade = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (r * r)))
        hf += (rng.random() * 2 - 0.6) * np.abs(d) * fade
    return hf


def crumple(w, h, seed, base, amp, grain, gloss=0.0):
    rng = np.random.default_rng(seed)
    hf = folds(w, h, 70, rng, max(w, h) * 0.35) + 0.5 * folds(w, h, 160, rng, max(w, h) * 0.12)
    from scipy.ndimage import gaussian_filter
    hf = gaussian_filter(hf, 1.2)
    gy, gx = np.gradient(hf)
    light = np.array([-0.55, -0.75, 0.9])
    shade = (gx * light[0] + gy * light[1] + light[2]) / np.sqrt(gx ** 2 + gy ** 2 + 1)
    shade = (shade - np.median(shade)) / (np.percentile(np.abs(shade - np.median(shade)), 98) + 1e-6)
    s = np.clip(shade, -1.2, 1.2) * 0.5
    lum = base + amp * s
    if gloss:
        lum += gloss * np.clip(s, 0, None) ** 3 * 6
    yy, xx = np.mgrid[0:h, 0:w]
    vign = 1 - 0.18 * (((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2) * 2
    lum = lum * vign + rng.normal(0, grain, (h, w))
    return np.clip(lum, 0, 1)


def save(arr, tint, path):
    rgb = np.stack([arr * t for t in tint], -1)
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(path, quality=88)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    save(crumple(1400, 1000, 3, 0.93, 0.16, 0.012), (1.0, 0.99, 0.965), OUT / "paper.jpg")
    save(crumple(1920, 1080, 11, 0.055, 0.07, 0.006, gloss=0.08), (1.0, 1.0, 1.04), OUT / "black.jpg")
    print("ok")
