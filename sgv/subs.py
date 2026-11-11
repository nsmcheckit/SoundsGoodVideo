"""Bilingual burned-in subtitles, cut from the narration's character timing."""
import difflib
import re

from .core import clean_text, read_json

MAX_ZH = 22
STYLE = {"h": {"w": 1920, "h": 1080, "zh": 46, "en": 28, "mv": 74}, "v": {"w": 1080, "h": 1920, "zh": 54, "en": 32, "mv": 360}}


def fmt(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def sentences(text):
    return [s for s in re.findall(r".+?(?:[。！？…]+[”’」』]?|$)", text.replace("\n", "")) if s.strip()]


def _snap(s, i):
    """The cut nearest to i that does not fall inside a Latin word or a number ("Tech|no" moves to "Techno|")."""
    def ok(k):
        return 0 < k < len(s) and not (s[k - 1].isascii() and s[k - 1].isalnum() and s[k].isascii() and s[k].isalnum())
    for d in range(len(s)):
        for k in (i - d, i + d):
            if ok(k):
                return k
    return i


def two_lines(zh):
    """Portrait subtitles: one long line becomes two, at the punctuation nearest the middle, never inside a word."""
    cuts = [m.end() for m in re.finditer(r"[，、：；]", zh) if 4 < m.end() < len(zh) - 3]
    cut = min(cuts, key=lambda c: abs(c - len(zh) / 2)) if cuts else _snap(zh, len(zh) // 2)
    return zh[:cut].rstrip() + r"\N" + zh[cut:].lstrip()


def chunks(sentence):
    """Splits a sentence at punctuation until each piece fits on a subtitle line."""
    parts = [p for p in re.findall(r".+?(?:[，、；：。！？…]+[”’」』]?|$)", sentence) if p.strip()]
    out, cur = [], ""
    for p in parts:
        if cur and len(clean_text(cur + p)) > MAX_ZH:
            out.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        out.append(cur)
    final = []
    for c in out:
        while len(clean_text(c)) > MAX_ZH + 6:
            k = _snap(c, MAX_ZH)
            final.append(c[:k].rstrip())
            c = c[k:].lstrip()
        final.append(c)
    return final


def _display_map(display, spoken_chars):
    """For each display character, the matching spoken character; the two differ wherever the lexicon rewrote a word."""
    d = [c for c in display]
    s = [c[0] for c in spoken_chars]
    sm = difflib.SequenceMatcher(None, d, s, autojunk=False)
    mapping = [None] * len(d)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        for k in range(i1, i2):
            if j2 > j1:
                r = (k - i1) / max(1, i2 - i1)
                mapping[k] = min(j2 - 1, j1 + int(r * (j2 - j1)))
    last = 0
    for k in range(len(mapping)):
        if mapping[k] is None:
            mapping[k] = last
        last = mapping[k]
    return mapping


MAX_EN = 44
STYLE_DUB = {"h": {"size": 44, "mv": 74}, "v": {"size": 50, "mv": 360}}


def sentences_en(text):
    return [s.strip() for s in re.findall(r".+?(?:[.!?]+[\"”’)]?(?=\s|$)|$)", text) if s.strip()]


def chunks_en(sentence):
    """Clauses joined up to one comfortable line; a clause that is still too long breaks at a space."""
    parts = re.findall(r".+?(?:[,;:—–]+\s*|$)", sentence)
    out, cur = [], ""
    for p in parts:
        if cur and len(cur + p) > MAX_EN:
            out.append(cur.strip())
            cur = p
        else:
            cur += p
    if cur.strip():
        out.append(cur.strip())
    merged = []
    for c in out:
        # a short tail ("a car city.") rides with the clause before it when the two still fit one line
        if merged and min(len(merged[-1]), len(c)) < 16 and len(merged[-1]) + 1 + len(c) <= MAX_EN + 8:
            merged[-1] += " " + c
        else:
            merged.append(c)
    out = merged
    final = []
    for c in out:
        while len(c) > MAX_EN + 10:
            k = c.rfind(" ", 0, MAX_EN)
            k = k if k > 0 else MAX_EN
            final.append(c[:k].strip())
            c = c[k:].strip()
        final.append(c)
    return final


def two_lines_en(line):
    """Portrait: a long line splits at the space nearest the middle."""
    spaces = [m.start() for m in re.finditer(" ", line)]
    if not spaces:
        return line
    k = min(spaces, key=lambda i: abs(i - len(line) / 2))
    return line[:k] + r"\N" + line[k + 1:]


def events_dub(ep, tl):
    vo = {p["id"]: p for p in read_json(ep.build / "vo" / "paras.json")} if (ep.build / "vo" / "paras.json").exists() else None
    if vo is None:
        from .timeline import estimated_vo
        vo = estimated_vo(ep)
    at = {v["id"]: v["t"] for v in tl["vo"]}
    ev = []
    for p in ep.paras:
        v = vo[p["id"]]
        text = p["text"].replace("\n", " ")
        m = _display_map(text, v["chars"])
        pos = 0
        for sent in sentences_en(text):
            for c in chunks_en(sent):
                j = text.find(c, pos)
                k = j + len(c) - 1
                pos = j + len(c)
                a = at[p["id"]] + v["chars"][m[j]][1]
                b = at[p["id"]] + v["chars"][m[k]][2]
                ev.append([a - 0.05, b + 0.15, c, ""])
    ev.sort(key=lambda e: e[0])
    for a, b in zip(ev, ev[1:]):
        if b[0] < a[1]:
            a[1] = b[0] - 0.02
    return ev


def events(ep, tl):
    if ep.lang != "zh":
        return events_dub(ep, tl)
    vo = {p["id"]: p for p in read_json(ep.build / "vo" / "paras.json")} if (ep.build / "vo" / "paras.json").exists() else None
    if vo is None:
        from .timeline import estimated_vo
        vo = estimated_vo(ep)
    at = {v["id"]: v["t"] for v in tl["vo"]}
    ev = []
    for p in ep.paras:
        v = vo[p["id"]]
        text = p["text"].replace("\n", "")
        m = _display_map(text, v["chars"])
        sents = sentences(text)
        en = p.get("en") or []
        if isinstance(en, str):
            en = [en]
        pos = 0
        for si, s in enumerate(sents):
            line_en = en[si] if si < len(en) else ""
            for c in chunks(s):
                j = text.find(c, pos)
                k = j + len(c) - 1
                pos = j + len(c)
                a = at[p["id"]] + v["chars"][m[j]][1]
                b = at[p["id"]] + v["chars"][m[k]][2]
                ev.append([a - 0.05, b + 0.15, re.sub(r"[，。；：、]+$", "", c), line_en])
    ev.sort(key=lambda e: e[0])
    for a, b in zip(ev, ev[1:]):
        if b[0] < a[1]:
            a[1] = b[0] - 0.02
    return ev


def write(ep, tl, orient):
    if ep.lang != "zh":
        return write_dub(ep, tl, orient)
    st = STYLE[orient]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {st['w']}
PlayResY: {st['h']}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Noto Sans CJK SC,{st['zh']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,2.2,1.5,2,80,80,{st['mv']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [head]
    for s, e, zh, en in events(ep, tl):
        if orient == "v" and len(zh) > 16:
            zh = two_lines(zh)
        tail = f"\\N{{\\fnInter\\fs{st['en']}\\b0\\c&HD8D8D8&\\bord1.6}}{en}" if en else ""
        lines.append(f"Dialogue: 0,{fmt(s)},{fmt(e)},Sub,,0,0,0,,{zh}{tail}\n")
    path = ep.build / f"subs_{orient}.ass"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def write_dub(ep, tl, orient):
    """Translated cut: one line of the cut's own language, no second line."""
    st, base = STYLE_DUB[orient], STYLE[orient]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {base['w']}
PlayResY: {base['h']}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Align
Style: Sub,Inter,{st['size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0.5,0,1,2.2,1.5,2,80,80,{st['mv']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [head]
    for s, e, line, _ in events(ep, tl):
        if orient == "v" and len(line) > 28:
            line = two_lines_en(line)
        lines.append(f"Dialogue: 0,{fmt(s)},{fmt(e)},Sub,,0,0,0,,{line}\n")
    path = ep.build / f"subs_{orient}.ass"
    path.write_text("".join(lines), encoding="utf-8")
    return path
