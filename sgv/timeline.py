"""Turns episode.yaml plus narration timing into one flat timeline. Everything downstream reads this."""
import re

import numpy as np

from .core import EST_CPS, EST_WPS, clean_text, read_json, spoken_chars, write_json

DEFAULT_GAP = 0.3
MIN_XF = 1.0
DEFAULT_XF = 1.2
CLIP_FADE = 0.25
ANCHOR = re.compile(r"^(start|end|[A-Za-z]\w*?)(?:@(.+?))?([+-]\d+(?:\.\d+)?)?$")


def estimated_vo(ep):
    """Pretend narration from character counts, so the edit can be checked before paying for a voice."""
    cps = ep.data.get("speech", {}).get("est_cps", EST_CPS)
    wps = ep.data.get("speech", {}).get("est_wps", EST_WPS)
    out = {}
    for p in ep.paras:
        text = ep.spoken(p)
        if ep.lang == "zh":
            dur = spoken_chars(text) / cps
        else:
            dur = len(re.findall(r"[A-Za-z0-9'’-]+", text)) / wps + 0.15
        chars = list(text)
        step = dur / max(1, len(chars))
        out[p["id"]] = {
            "id": p["id"], "dur": round(dur, 3), "text": text, "file": None,
            "chars": [[c, round(i * step, 3), round((i + 1) * step, 3)] for i, c in enumerate(chars)],
        }
    return out


def real_vo(ep, build=None):
    f = (build or ep.build) / "vo" / "paras.json"
    return {p["id"]: p for p in read_json(f)} if f.exists() else None


def grid_of(ep, src):
    """Bar lines and hard boundaries for a music source, from the manifest or from measurement."""
    meta = ep.music(src) if src in ep.data["sources"].get("music", {}) else {}
    analysis = ep.build / "analysis" / f"{src}.json"
    info = read_json(analysis) if analysis.exists() else {}
    grids = meta.get("grid") or info.get("grid") or []
    bars = []
    for g in grids:
        bar = 60.0 / g["bpm"] * g.get("bar_beats", 4)
        n0 = int(np.ceil((g["start"] - g["offset"]) / bar - 1e-6))
        k = n0
        while True:
            b = g["offset"] + k * bar
            if b >= g["end"]:
                break
            bars.append(round(b, 4))
            k += 1
    hard = list(meta.get("hard_boundaries") or [])
    return {"bars": np.array(sorted(bars)), "hard": hard}


def nearest(arr, x):
    if len(arr) == 0:
        return x
    return float(arr[int(np.argmin(np.abs(arr - x)))])


class Resolver:
    def __init__(self, ep, vo, lexicon=None):
        self.ep, self.vo = ep, vo
        self.lexicon = lexicon or ep.lexicon
        self.para_t, self.sec = {}, {}

    def __call__(self, spec, sec):
        if isinstance(spec, (int, float)):
            return float(spec) + self.sec[sec["id"]]["start"]
        m = ANCHOR.match(str(spec).strip())
        if not m:
            raise ValueError(f"bad anchor: {spec!r} in section {sec['id']}")
        name, phrase, off = m.groups()
        off = float(off) if off else 0.0
        if name == "start":
            return self.sec[sec["id"]]["start"] + off
        if name == "end":
            return self.sec[sec["id"]]["end"] + off
        if name not in self.para_t:
            raise ValueError(f"unknown anchor {name!r} in section {sec['id']}")
        t = self.para_t[name]
        if phrase:
            v = self.vo[name]
            flat, idx = "", []
            for i, ch in enumerate(v["chars"]):
                c = clean_text(ch[0])
                flat += c
                idx += [i] * len(c)
            needle = clean_text(phrase)
            for k in sorted(self.lexicon["replace"], key=len, reverse=True):
                needle = needle.replace(clean_text(k), clean_text(self.lexicon["replace"][k]))
            j = flat.find(needle)
            if j < 0:
                raise ValueError(f"phrase {phrase!r} not found in {name}")
            t += v["chars"][idx[j]][1]
        return t + off


DUB_MARGIN = 0.12


def _dub(ep, vo_track, dub, total, errors):
    """Moves each paragraph of the translated narration into the slot its Chinese paragraph had.
    A paragraph marked `dub_align: end` finishes where the Chinese one did (for lines that end on a music hit)."""
    paras = {p["id"]: p for p in ep.paras}
    prev_end = 0.0
    for i, v in enumerate(vo_track):
        d = dub[v["id"]]["dur"]
        slot_end = vo_track[i + 1]["t"] if i + 1 < len(vo_track) else total
        t = v["t"] + v["dur"] - d if paras[v["id"]].get("dub_align") == "end" else v["t"]
        t = max(t + float(paras[v["id"]].get("dub_offset", 0.0)), prev_end + 0.1)
        if t + d > slot_end - DUB_MARGIN:
            errors.append({"rule": "dub.overflow", "t": t,
                           "msg": f"{v['id']} 译文配音 {d:.1f} 秒，超出中文段落的位置 {t + d - slot_end + DUB_MARGIN:.1f} 秒；缩短这一段译文"})
        v["t"], v["dur"] = round(t, 3), d
        prev_end = t + d


def _align_pre(ep, res, sec, t_now, errors):
    target = float(sec["align"]["time"]) - float(sec["align"].get("before", 0.0))
    src = sec["align"]["src"]
    last = None
    for s in ep.sections:
        if s["id"] == sec["id"]:
            break
        for m in s.get("music") or []:
            if m["src"] == src and (m.get("sync") is not None or m.get("in", "continue") != "continue"):
                last = (m, s)
    if last is None:
        errors.append({"rule": "timing.align", "msg": f"{sec['id']} 要对齐 {src}，但前面没有可参照的音乐入点", "t": t_now})
        return 0.0
    m, s = last
    if m.get("sync") is not None:
        source_now = float(m["sync"]) + (t_now - res(m["at"], s))
    else:
        source_now = float(m["in"]) + (t_now - res(m.get("at", "start"), s))
    wait = target - source_now
    if wait < 0:
        errors.append({"rule": "timing.align", "t": t_now,
                       "msg": f"{sec['id']} 第一句要落在原曲 {target:.1f} 秒，但前面的口播长了 {-wait:.1f} 秒，音乐已经过了那里"})
        return 0.0
    return wait


def _follow(bed, src, t):
    """Source time of `src` heard at timeline time t, so picture and sound from one recording stay in sync."""
    for b in bed:
        if b["src"] == src and not b["clip"] and b["t"] - 1e-6 <= t < b["t"] + b["dur"] - 1e-6:
            return b["in"] + (t - b["t"])
    return None


def _collect(ep, res, key):
    items = []
    for s in ep.sections:
        for it in s.get(key) or []:
            items.append(dict(it, t=res(it.get("at", "start"), s), section=s["id"]))
    return items


def _music_len(ep, src):
    a = ep.build / "analysis" / f"{src}.json"
    return read_json(a).get("duration", 1e9) if a.exists() else 1e9


def build(ep, vo=None):
    dub = None
    if ep.lang != "zh" and vo is None:
        # A dubbed cut keeps the Chinese edit: lay out with the Chinese narration, then drop each translated
        # paragraph into its Chinese paragraph's place.
        dub = real_vo(ep) or estimated_vo(ep)
        vo = real_vo(ep, ep.base_build) or estimated_vo(ep.zh())
    vo = vo or real_vo(ep) or estimated_vo(ep)
    res = Resolver(ep, vo, ep.zh_lexicon if dub is not None else None)
    t, sections, vo_track, errors = 0.0, [], [], []
    for s in ep.sections:
        s0 = t
        res.sec[s["id"]] = {"start": s0, "end": s0}
        pre = s.get("pre", 0.0)
        if s.get("align"):
            # Wait for a moment of the continuing music before the first line, so words and music meet.
            pre = _align_pre(ep, res, s, t, errors)
        t += pre
        paras = s.get("paras") or []
        for i, p in enumerate(paras):
            v = vo[p["id"]]
            res.para_t[p["id"]] = t
            vo_track.append({"id": p["id"], "t": round(t, 3), "dur": v["dur"], "section": s["id"]})
            t += v["dur"]
            if i < len(paras) - 1:
                t += p.get("pause_after", s.get("gap", DEFAULT_GAP))
        t += s.get("post", 0.0)
        sections.append({"id": s["id"], "chapter": s.get("chapter"), "start": round(s0, 3), "end": round(t, 3)})
        res.sec[s["id"]] = {"start": s0, "end": t}
    total = round(t, 3)
    if dub is not None:
        _dub(ep, vo_track, dub, total, errors)

    # ---- music bed ------------------------------------------------------
    music, clips = _collect(ep, res, "music"), _collect(ep, res, "clips")
    for m in music:
        if "sync" in m:
            # `at` is where the source moment `sync` must be heard; the cut happens `lead` seconds before it,
            # or at the start of the section with lead: start.
            lead = m.get("lead", 4.0)
            lead = m["t"] - res.sec[m["section"]]["start"] if lead == "start" else float(lead)
            m["t"] -= lead
            m["in"] = float(m["sync"]) - lead
    for c in clips:
        c["clip"] = True
    merged = sorted(music + clips, key=lambda x: x["t"])
    bed, cursor, last_music = [], {}, None
    for it in merged:
        it = dict(it)
        if it.get("clip"):
            bed.append(it)
            if last_music is not None:
                bed.append({"src": last_music, "t": it["t"] + it["dur"], "in": "continue",
                            "section": it["section"], "resume": True})
            continue
        last_music = it["src"]
        bed.append(it)
    bed.sort(key=lambda x: x["t"])

    out = []
    for i, it in enumerate(bed):
        src = it["src"]
        g = grid_of(ep, src) if not it.get("clip") else {"bars": np.array([]), "hard": []}
        if out and not it.get("clip") and not out[-1].get("clip") and not it.get("lock"):
            prev = out[-1]
            gp = grid_of(ep, prev["src"])
            prev_out = prev["in"] + (it["t"] - prev["t"])
            bar = nearest(gp["bars"], prev_out)
            if not (len(gp["bars"]) and abs(bar - prev_out) > 2.5):
                it["t"] = it["t"] + (bar - prev_out)
                if "sync" in it:
                    it["in"] = it["in"] + (bar - prev_out)
        if out:
            prev = out[-1]
            prev["dur"] = round(it["t"] - prev["t"], 3)
            prev["out"] = round(prev["in"] + prev["dur"], 3)
            if not prev["clip"]:
                cursor[prev["src"]] = prev["out"]
        pos = it.get("in", "continue")
        if pos == "continue":
            pos = cursor.get(src, 0.0)
            explicit = False
        else:
            pos = float(pos)
            explicit = True
            if not it.get("free") and len(g["bars"]):
                pos = nearest(g["bars"], pos)
        rec = {
            "src": src, "t": round(it["t"], 3), "in": round(pos, 3), "dur": 0.0, "out": 0.0,
            "clip": bool(it.get("clip")), "section": it["section"], "explicit": explicit,
            "free": bool(it.get("free")), "reuse": it.get("reuse"), "through": it.get("through"),
            "sync": it.get("sync"),
            "xf": max(MIN_XF, float(it.get("xf", DEFAULT_XF))) if not it.get("clip") else CLIP_FADE,
        }
        if it.get("xf") is not None and float(it["xf"]) < MIN_XF and not it.get("clip"):
            rec["xf_requested"] = float(it["xf"])
        if it.get("clip"):
            rec["dur"] = float(it["dur"])
            rec["video"] = bool(it.get("video"))
            rec["look"] = it.get("look", "raw")
        # A continued item that follows its own source directly is one uninterrupted take.
        if out and not explicit and not rec["clip"] and out[-1]["src"] == src and not out[-1]["clip"]:
            continue
        out.append(rec)
    if out:
        last = out[-1]
        if not last["clip"]:
            last["dur"] = round(total - last["t"], 3)
            last["out"] = round(last["in"] + last["dur"], 3)
        else:
            last["out"] = round(last["in"] + last["dur"], 3)
    for r in out:
        if r["clip"]:
            r["out"] = round(r["in"] + r["dur"], 3)

    # ---- graphics -------------------------------------------------------
    gfx = []
    for n, g in enumerate(_collect(ep, res, "gfx")):
        sec = next(s for s in ep.sections if s["id"] == g["section"])
        if "until" in g:
            dur = res(g["until"], sec) - g["t"]
        else:
            dur = float(g.get("dur", 4.0))
        gfx.append({"id": f"g{n:03d}_{g['type']}", "type": g["type"], "t": round(g["t"], 3), "dur": round(dur, 3),
                    "params": g.get("params") or {}, "full": bool(g.get("full")), "section": g["section"]})

    # ---- picture track --------------------------------------------------
    shots = sorted(_collect(ep, res, "video"), key=lambda x: x["t"])
    for sh in shots:
        if sh.get("follow"):
            own = [b["t"] for b in out if b["src"] == sh["follow"] and not b["clip"] and b["section"] == sh["section"]]
            if own and sh["t"] < own[0] < sh["t"] + 2.5:
                sh["t"] = own[0]
    blocks = [{"t": g["t"], "dur": g["dur"], "kind": "gfx", "id": g["id"]} for g in gfx if g["full"]]
    blocks += [{"t": c["t"], "dur": c["dur"], "kind": "clip", "src": c["src"], "in": c["in"], "look": c["look"]}
               for c in out if c["clip"] and c.get("video")]
    blocks.sort(key=lambda b: b["t"])
    video, vcur = [], {}
    follows = {s["follow"] for s in shots if s.get("follow")}
    cuts = {b["t"] for b in out if b["src"] in follows}
    marks = sorted({0.0, total} | {s["t"] for s in shots} | {b["t"] for b in blocks} | {b["t"] + b["dur"] for b in blocks} | cuts)
    marks = [m for m in marks if 0.0 <= m <= total]
    for a, b in zip(marks, marks[1:]):
        if b - a < 1e-3:
            continue
        block = next((x for x in blocks if x["t"] <= a + 1e-6 and x["t"] + x["dur"] >= b - 1e-6), None)
        if block is not None:
            if block["kind"] == "gfx":
                rec = {"src": f"gfx:{block['id']}", "in": round(a - block["t"], 3), "look": "raw", "speed": 1.0, "block": block["id"]}
            else:
                rec = {"src": block["src"], "in": round(block["in"] + a - block["t"], 3), "look": block["look"], "speed": 1.0,
                       "clip": True, "block": f"clip{block['t']}"}
            rec.update(t=round(a, 3), dur=round(b - a, 3))
            if video and video[-1].get("block") == rec.get("block") and rec.get("block"):
                video[-1]["dur"] = round(video[-1]["dur"] + rec["dur"], 3)
            else:
                video.append(rec)
            continue
        shot = None
        for s in shots:
            if s["t"] <= a + 1e-6:
                shot = s
        if shot is None:
            continue
        src, speed = shot["src"], float(shot.get("speed", 1.0))
        prev = video[-1] if video else None
        if prev is not None and prev.get("shot") == id(shot) and not shot.get("follow"):
            prev["dur"] = round(prev["dur"] + b - a, 3)
            vcur[src] = shot["_pos"] = prev["in"] + prev["dur"] * speed
            continue
        if shot.get("follow"):
            pos = _follow(out, shot["follow"], a)
            if pos is None:
                raise ValueError(f"shot at {a:.2f}s follows {shot['follow']}, but that source is not playing")
        elif shot.get("_started"):
            pos = shot["_pos"]
        else:
            pos = shot.get("in", "continue")
            pos = vcur.get(src, 0.0) if pos == "continue" else float(pos)
            shot["_started"] = True
        rec = {"t": round(a, 3), "dur": round(b - a, 3), "src": src, "in": round(pos, 3), "look": shot.get("look", "raw"),
               "speed": speed, "reuse": shot.get("reuse"), "shot": id(shot)}
        if shot.get("with"):
            # Split screen: the second picture keeps its own running position.
            key = "with:" + shot["with"]
            w_pos = shot["_wpos"] if shot.get("_started_w") else float(shot.get("with_in", vcur.get(shot["with"], 0.0)))
            shot["_started_w"] = True
            rec.update({"with": shot["with"], "with_in": round(w_pos, 3)})
            shot["_wpos"] = w_pos + (b - a)
            vcur[shot["with"]] = shot["_wpos"]
        video.append(rec)
        shot["_pos"] = pos + (b - a) * speed
        vcur[src] = shot["_pos"]
        # Interrupted shots pick up where they stopped, so a block never causes a replay.
    for v in video:
        if v.get("shot"):
            shot = next(s for s in shots if id(s) == v["shot"])
            v.pop("shot")
    for s in shots:
        for k in ("_started", "_pos", "_started_w", "_wpos"):
            s.pop(k, None)

    # ---- structure bar --------------------------------------------------
    st = ep.data.get("structure")
    mapping = []
    if st:
        hidden = [(g["t"], g["t"] + g["dur"]) for g in gfx if g["full"]]
        hidden += [(x["start"], x["end"]) for x, s0 in zip(sections, ep.sections) if s0.get("structure") is False]
        for b in out:
            if b["src"] == st["source"] and not b["clip"]:
                mapping.append({"t": b["t"], "dur": b["dur"], "in": b["in"]})
        mapping = {"items": mapping, "hidden": hidden}

    spoken = dub if dub is not None else vo
    tl = {"total": total, "sections": sections, "vo": vo_track, "bed": out, "video": video, "gfx": gfx,
          "map": mapping, "errors": errors, "estimated": all(not v.get("file") for v in spoken.values())}
    write_json(ep.build / "timeline.json", tl)
    return tl, vo
