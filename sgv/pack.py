"""Covers and the per-platform publishing text."""
from pathlib import Path

from .core import read_json, ts

COVERS = {"zh_16x9": (1920, 1080), "zh_4x3": (1600, 1200), "zh_3x4": (1080, 1440), "en_16x9": (1920, 1080), "en_3x4": (1080, 1440)}


def covers(ep):
    from .gfx import Stage
    spec = ep.data.get("cover")
    if not spec:
        return []
    folder = ep.build / "covers"
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    with Stage() as st:
        st.load_images({k: ep.path(k) for k in spec["images"]})
        for name, (w, h) in COVERS.items():
            lang = name[:2]
            params = {**spec, **(spec.get(lang) or {})}
            st.frame("cover", params, 1.0, 10.0, w, h)
            p = folder / f"{name}.png"
            p.write_bytes(st.png())
            out.append(p)
    return out


def chapters(tl):
    rows, seen_first = [], False
    for s in tl["sections"]:
        if not s.get("chapter"):
            continue
        t = 0.0 if not seen_first else s["start"]
        seen_first = True
        rows.append(f"{int(t // 60):02d}:{int(t % 60):02d} {s['chapter']}")
    return rows


def publish_text(ep, tl=None):
    tl = tl or read_json(ep.build / "timeline.json")
    pub = ep.data.get("publish") or {}
    owners = "\n".join(ep.data.get("owners") or [])
    chap = "\n".join(chapters(tl))
    lines = [f"# {ep.data.get('title', ep.id)} 发布包", "", f"成片时长 {ts(tl['total'])}", ""]
    for platform, block in pub.items():
        lines += [f"## {platform}", ""]
        titles = block.get("titles") or []
        if titles:
            lines += ["**标题**", ""] + [f"{i + 1}. {t}" for i, t in enumerate(titles)] + [""]
        if block.get("body"):
            body = block["body"].replace("{chapters}", chap).replace("{owners}", owners)
            lines += ["**简介**", "", "```", body.strip(), "```", ""]
        if block.get("tags"):
            lines += ["**标签**：" + "、".join(block["tags"]), ""]
    if ep.data.get("pinned_comment"):
        lines += ["## 置顶评论", "", "```", ep.data["pinned_comment"].strip(), "```", ""]
    p = Path(ep.build / "publish.md")
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
