"""Automatic checks. Each rule exists because Jee had to point the problem out on a real episode.

FAIL stops delivery. WARN goes on Jee's listening list. An item can opt out of a rule only by saying why (reuse: "...", through: "...").
"""
import re
from pathlib import Path

import numpy as np

from .core import clean_text, probe_duration, read_json, ts, write_json
from .timeline import MIN_XF, grid_of

BANNED_NAMES = ["HOPICO", "叫累焦雷", "焦雷", "沐小葵的视频", "歪江", "困高"]
EARLIER_EPISODE = ["上一期", "上期", "前几期", "前两期", "之前那期", "第一期", "第二期", "第三期", "上回"]
TIMECODE = [r"\d+\s*分\s*\d+\s*秒", r"\d+:\d{2}", r"第\s*[一二三四五六七八九十\d]+\s*分[钟]?[第的]", r"[一二三四五六七八九十两]+分[一二三四五六七八九十]+秒"]
ENDING = "更多游戏声音拆解，关注 SoundsGood"
PERSONAL_MARKS = ["在我看来", "在我听来", "我的理解", "我听着", "我感觉"]
# Hard arrangement specs in the narration. Jee (ep04 v2): the details were too fine-grained; the story carries the
# episode and a few specs back it up. BPM is not counted: it is shown on screen and anchors the story.
SPEC_PATTERNS = [r"\d+(?:\.\d+)?\s*(?:Hz|赫兹|dB|分贝)", r"[一二三四五六七八九十百千两]+\s*(?:赫兹|分贝)", r"(?<![A-Za-z])[A-G][#b♯♭]?\d(?!\d)",
                 "八度", "声像", "十六分", "三连音", "附点", "五拍子"]
MAX_SPECS = 3
BAR_TOL = 0.035


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, rule, msg, t=None):
        self.items.append({"level": level, "rule": rule, "msg": msg, "t": t})

    def fail(self, rule, msg, t=None):
        self.add("FAIL", rule, msg, t)

    def warn(self, rule, msg, t=None):
        self.add("WARN", rule, msg, t)

    @property
    def fails(self):
        return [i for i in self.items if i["level"] == "FAIL"]

    @property
    def warns(self):
        return [i for i in self.items if i["level"] == "WARN"]


def _overlaps(ranges):
    """Every pair that shares more than half a second, not just neighbours after sorting."""
    out = []
    ranges = sorted(ranges)
    for i, (a0, a1, ai) in enumerate(ranges):
        for b0, b1, bi in ranges[i + 1:]:
            if b0 >= a1 - 0.5:
                break
            out.append((b0, min(a1, b1), ai, bi))
    return out


def check_script(ep, r):
    paras = ep.paras
    for p in paras:
        t = p["text"]
        for name in BANNED_NAMES:
            if name in t:
                r.fail("script.names", f"{p['id']} 点名了其他 UP 主或频道：{name}")
        for w in EARLIER_EPISODE:
            if w in t:
                r.fail("script.earlier", f"{p['id']} 提到了前几期：{w}")
        for pat in TIMECODE:
            m = re.search(pat, t)
            if m:
                r.fail("script.timecode", f"{p['id']} 口播里有时间码：{m.group(0)}")
        if p.get("pending"):
            r.fail("script.unconfirmed", f"{p['id']} 还在等听辨单的答案：{', '.join(p['pending']) if isinstance(p['pending'], list) else p['pending']}")
        if "⚠" in t or "⚠" in ep.spoken(p):
            r.fail("script.unconfirmed", f"{p['id']} 还带着未确认标记 ⚠️")
        claim = p.get("claim")
        if claim == "ear" and not any(m in t for m in PERSONAL_MARKS) and not p.get("confirmed_by"):
            r.fail("script.ear_claim", f"{p['id']} 是听感判断，既没有写成第一人称，也没有听辨单确认")
        spoken = ep.spoken(p)
        if re.search(r"\d", spoken):
            r.fail("voice.digits", f"{p['id']} 配音文本里有阿拉伯数字，需要写成读法：{re.findall(r'[^，。]*?\d+[^，。]*', spoken)[0][:30]}")
        for w in set(re.findall(r"[A-Za-z][A-Za-z\-]*", spoken)):
            if w not in ep.lexicon["latin_ok"] and w.lower() not in [x.lower() for x in ep.lexicon["latin_ok"]]:
                r.warn("voice.latin", f"{p['id']} 配音里有未验证过的英文词：{w}")
    specs = [(p["id"], m.group(0)) for p in paras for pat in SPEC_PATTERNS for m in re.finditer(pat, p["text"])]
    limit = ep.data.get("max_specs", MAX_SPECS)
    if len(specs) > limit:
        r.fail("script.spec_density", f"口播里有 {len(specs)} 处编曲参数（上限 {limit}），讲故事为主、参数只留最关键的："
               + "，".join(f"{pid} {s}" for pid, s in specs))
    if not any(ENDING.replace(" ", "") in p["text"].replace(" ", "") for p in paras):
        r.fail("script.ending", f"缺少固定结尾句：{ENDING}")
    from .subs import sentences
    for p in paras:
        en = p.get("en")
        if en is None:
            continue
        en = [en] if isinstance(en, str) else en
        n = len(sentences(p["text"]))
        if len(en) != n:
            r.fail("subs.en_count", f"{p['id']} 有 {n} 句中文，却有 {len(en)} 句英文")


def check_timeline(ep, tl, r):
    for e in tl.get("errors", []):
        r.fail(e["rule"], e["msg"], e.get("t"))
    # Sources must exist and be long enough.
    for it in tl["bed"]:
        src = (ep.data["sources"].get("music", {}).get(it["src"]) or ep.data["sources"].get("video", {}).get(it["src"]))
        if src is None:
            r.fail("source.missing", f"音乐来源 {it['src']} 没有定义", it["t"])
            continue
        if src.get("stem"):
            r.fail("audio.no_stems", f"成片用了分离音轨 {it['src']}，分离只能用于分析", it["t"])
    music_ranges = {}
    for n, it in enumerate(tl["bed"]):
        if it.get("reuse"):
            continue
        music_ranges.setdefault(it["src"], []).append((it["in"], it["out"], n))
    for src, ranges in music_ranges.items():
        for a, b, _, _ in _overlaps(ranges):
            r.fail("music.no_replay", f"音乐 {src} 的 {ts(a)}–{ts(b)} 被用了两次，应该接着往后走", None)
    video_ranges = {}
    for n, v in enumerate(tl["video"]):
        if v["src"].startswith("gfx:") or v.get("reuse"):
            continue
        video_ranges.setdefault(v["src"], []).append((v["in"], v["in"] + v["dur"] * v.get("speed", 1.0), n))
        meta = ep.data["sources"].get("video", {}).get(v["src"])
        if meta is None:
            r.fail("source.missing", f"画面来源 {v['src']} 没有定义", v["t"])
            continue
        p = ep.path(meta["path"])
        if not p.exists():
            r.fail("source.missing", f"画面文件不存在：{meta['path']}", v["t"])
        elif v["in"] + v["dur"] * v.get("speed", 1.0) > probe_duration(p) + 0.05:
            r.fail("source.too_short", f"画面 {v['src']} 不够长，需要用到 {ts(v['in'] + v['dur'])}", v["t"])
    for src, ranges in video_ranges.items():
        for a, b, _, _ in _overlaps(ranges):
            r.fail("video.no_replay", f"画面 {src} 的 {ts(a)}–{ts(b)} 被用了两次", None)

    items = tl["bed"]
    for prev, cur in zip(items, items[1:]):
        if cur["clip"] or prev["clip"]:
            continue
        if cur.get("xf_requested") is not None:
            r.fail("music.crossfade", f"交叉淡化 {cur['xf_requested']} 秒太短，至少 {MIN_XF} 秒", cur["t"])
        g_prev = grid_of(ep, prev["src"])
        if len(g_prev["bars"]) and not cur["free"] and np.min(np.abs(g_prev["bars"] - prev["out"])) > BAR_TOL:
            r.fail("music.bar_cut", f"{prev['src']} 在 {ts(prev['out'])} 切出，没有落在小节线上", cur["t"])
        g_cur = grid_of(ep, cur["src"])
        if cur["explicit"] and len(g_cur["bars"]) and not cur["free"] and np.min(np.abs(g_cur["bars"] - cur["in"])) > BAR_TOL:
            r.fail("music.bar_cut", f"{cur['src']} 从 {ts(cur['in'])} 切入，没有落在小节线上", cur["t"])
    for it in items:
        if it["clip"] or it.get("through"):
            continue
        for h in grid_of(ep, it["src"])["hard"]:
            if it["in"] + 0.05 < h < it["out"] - 0.05:
                r.fail("music.switch", f"{it['src']} 这段铺底（{ts(it['in'])}–{ts(it['out'])}）跨过了 {ts(h)} 的段落切换点。"
                                       f"请在切换点之前收住，或把入点提前到 {ts(max(0, h - it['dur'] - 0.6))}", it["t"])
    full = [g for g in tl["gfx"] if g["full"]]
    for g in tl["gfx"]:
        if g["full"]:
            continue
        for f in full:
            if g["t"] < f["t"] + f["dur"] - 0.05 and g["t"] + g["dur"] > f["t"] + 0.05:
                r.fail("layout.over_full", f"{g['id']} 叠到了全屏画面 {f['id']} 上", max(g["t"], f["t"]))
    # Picture must cover the whole film.
    shots = sorted(tl["video"], key=lambda v: v["t"])
    if not shots or shots[0]["t"] > 0.02:
        r.fail("video.gap", "开头没有画面", 0.0)
    for a, b in zip(shots, shots[1:]):
        if b["t"] > a["t"] + a["dur"] + 0.05:
            r.fail("video.gap", f"{ts(a['t'] + a['dur'])} 起有一段没有画面", a["t"] + a["dur"])
    if shots and shots[-1]["t"] + shots[-1]["dur"] < tl["total"] - 0.05:
        r.fail("video.gap", "片尾没有画面到结束", shots[-1]["t"] + shots[-1]["dur"])

    target = ep.data.get("target_seconds")
    if target:
        tol = ep.data.get("target_tolerance", 0.08)
        over = tl["total"] - target
        if abs(over) > target * tol:
            r.fail("duration", f"成片 {ts(tl['total'])}，目标 {ts(target)}，差 {over:+.0f} 秒。" + _trim_advice(ep, tl, over), None)
    owners = ep.data.get("owners") or []
    end = [g for g in tl["gfx"] if g["type"] == "end"]
    if not end:
        r.fail("end.card", "没有片尾卡")
    else:
        got = end[0]["params"].get("owners") or []
        for o in owners:
            if o not in got:
                r.fail("end.owners", f"片尾缺少版权声明：{o}")
    used = {v["src"] for v in tl["video"] if not v["src"].startswith("gfx:")}
    for key in used:
        meta = ep.data["sources"].get("video", {}).get(key) or {}
        if meta.get("license") == "pending":
            r.fail("license.pending", f"素材 {key} 的授权还没拿到，不能进成片")


def _trim_advice(ep, tl, over):
    if over <= 0:
        return ""
    durs = {v["id"]: v["dur"] for v in tl["vo"]}
    optional = [p for p in ep.paras if p.get("optional")]
    if not optional:
        return "稿子里没有标 optional 的段落，需要 Jee 决定删哪里。"
    picked, acc = [], 0.0
    for p in sorted(optional, key=lambda x: -durs[x["id"]]):
        if acc >= over:
            break
        picked.append(p["id"])
        acc += durs[p["id"]]
    return f"可删的段落：{'、'.join(picked)}，共省 {acc:.0f} 秒。"


def check_reading(ep, r):
    f = ep.build / "vo" / "reading.json"
    if not f.exists():
        return
    d = read_json(f)
    for row in d["report"]:
        if row["ratio"] < 0.82:
            r.fail("voice.reading", f"{row['id']} 和稿子差异太大（{row['ratio']}），听到：{row['heard'][:40]}")
        elif row["issues"]:
            detail = "；".join(f"{i['expected']}→{i['heard']}" for i in row["issues"][:3])
            r.warn("voice.reading", f"{row['id']} 可能读错：{detail}")


def check_mix(ep, tl, r):
    f = ep.build / "mix_metrics.json"
    if not f.exists():
        return
    m = read_json(f)
    target = ep.data.get("lufs", -16.0)
    if abs(m["integrated_lufs"] - target) > 0.6:
        r.fail("mix.loudness", f"整片响度 {m['integrated_lufs']} LUFS，目标 {target}")
    if m["true_peak_db"] is not None and m["true_peak_db"] > -1.0:
        r.fail("mix.peak", f"峰值 {m['true_peak_db']} dB，超过 -1 dB")
    o = m.get("vo_over_bed_db")
    if o is not None and not 7.0 <= o <= 16.0:
        r.fail("mix.vo_balance", f"口播比背景高 {o} dB，已确认的范围是 7–16 dB")
    v = m.get("vocal_band_margin_db")
    if v is not None and v > 15.0:
        r.warn("mix.vocal_masking", f"125 Hz–2 kHz 口播比背景高 {v} dB，原声人声可能被盖住")
    for s in m["cut_steps"]:
        if not s["clip"] and abs(s["step_lu"]) > 5.0:
            r.warn("mix.cut_jump", f"剪辑点前后响度跳了 {s['step_lu']} LU", s["t"])
    if m["bed_dropouts"]:
        r.warn("mix.dropout", f"背景音乐有接近无声的地方：{', '.join(ts(x) for x in m['bed_dropouts'][:6])}")


def _sub_zone(orient):
    return (120, 900, 1800, 1012) if orient == "h" else (60, 1330, 1020, 1565)


def check_layout(ep, tl, r, orient):
    f = ep.build / f"bbox_{orient}.json"
    if not f.exists():
        return
    boxes = read_json(f)
    zx0, zy0, zx1, zy1 = _sub_zone(orient)
    vo_spans = [(v["t"], v["t"] + v["dur"]) for v in tl["vo"]]
    W, H = (1920, 1080) if orient == "h" else (1080, 1920)
    for g in tl["gfx"]:
        bb = boxes.get(g["id"]) or []
        speaking = any(a < g["t"] + g["dur"] and b > g["t"] for a, b in vo_spans)
        for b in bb:
            if b[0] < -2 or b[2] > W + 2 or b[1] < -2 or b[3] > H + 2:
                r.fail("layout.offscreen", f"{orient}: {g['id']} 的文字超出画面 {b}", g["t"])
                break
        if speaking and g["type"] != "end":
            for b in bb:
                if b[0] < zx1 and b[2] > zx0 and b[1] < zy1 and b[3] > zy0:
                    r.fail("layout.subtitle_clash", f"{orient}: {g['id']} 的文字压到字幕区 {b}", g["t"])
                    break
        if orient == "v":
            for b in bb:
                if b[1] < 240 or b[3] > 1680:
                    r.fail("layout.safe_zone", f"v: {g['id']} 的文字超出 3:4 安全区 {b}", g["t"])
                    break


def run_all(ep, tl=None):
    tl = tl or read_json(ep.build / "timeline.json")
    r = Report()
    check_script(ep, r)
    check_timeline(ep, tl, r)
    check_reading(ep, r)
    check_mix(ep, tl, r)
    for o in ("h", "v"):
        check_layout(ep, tl, r, o)
    if not ep.approved("listening") and not ep.data.get("no_listening"):
        r.fail("gate.listening", "听辨单还没有确认")
    if not ep.approved("script"):
        r.fail("gate.script", "逐字稿还没有确认，或确认之后又改过")
    write_json(ep.build / "qa.json", r.items)
    return r


def listen_list(ep, tl):
    """What a human ear should go straight to. Everything else was machine-checked."""
    out = []
    items = tl["bed"]
    for a, b in zip(items, items[1:]):
        if b["clip"]:
            out.append((b["t"], f"原声片段进入（{b['src']}）"))
        elif a["clip"]:
            out.append((b["t"], "原声片段结束，音乐接回"))
        else:
            out.append((b["t"], f"音乐接口：{a['src']} {ts(a['out'])} 接 {b['src']} {ts(b['in'])}"))
    positions = {v["id"]: v["t"] for v in tl["vo"]}
    vo_file = ep.build / "vo" / "paras.json"
    chars = {p["id"]: p for p in read_json(vo_file)} if vo_file.exists() else {}
    for p in ep.paras:
        text = p["text"]
        for w in ep.lexicon["listen"]:
            start = text.find(w)
            if start < 0:
                continue
            base = positions[p["id"]]
            v = chars.get(p["id"])
            if v and v["chars"]:
                base += v["chars"][min(len(v["chars"]) - 1, start)][1]
            out.append((base, f"读音：{w}"))
    f = ep.build / "vo" / "reading.json"
    if f.exists():
        for row in read_json(f)["report"]:
            if row["issues"]:
                out.append((positions[row["id"]], f"语音识别提示 {row['id']}：" + "；".join(f"{i['expected']}→{i['heard']}" for i in row["issues"][:2])))
    return sorted(out, key=lambda x: x[0])


def write_review(ep, tl, r):
    lines = [f"# {ep.data.get('title', ep.id)} 终审清单", "", f"成片 {ts(tl['total'])}", ""]
    lines += ["## 只听这些位置", ""]
    for t, what in listen_list(ep, tl):
        lines.append(f"- **{ts(t)}** {what}")
    if r.warns:
        lines += ["", "## 自动检查的提醒", ""]
        lines += [f"- {('**' + ts(i['t']) + '** ') if i['t'] is not None else ''}{i['msg']}" for i in r.warns]
    if r.fails:
        lines += ["", "## 未通过（修好前不交付）", ""]
        lines += [f"- [{i['rule']}] {i['msg']}" for i in r.fails]
    p = ep.build / "review.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


__all__ = ["run_all", "write_review", "clean_text", "Path"]
