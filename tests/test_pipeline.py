"""Run with: python3 tests/test_pipeline.py
Each case plants a mistake from a real episode and asserts the matching check stops it."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_fixture import MANIFEST, TRUTH, fresh  # noqa: E402
from sgv import gfx, qa, timeline  # noqa: E402
from sgv.core import Episode, read_json, write_json  # noqa: E402
from sgv.mix import _source_wav  # noqa: E402
from sgv.measure import analyze  # noqa: E402
from sgv.voice import compare_reading, install_placeholder  # noqa: E402

fails = []
def expect(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def section(m, sid):
    return next(s for s in m["sections"] if s["id"] == sid)


def para(m, pid):
    return next(p for s in m["sections"] for p in s.get("paras", []) if p["id"] == pid)


base = fresh("measured")
ep = Episode(base)
d = analyze(_source_wav(ep, "A"), ep.build / "A.json", ep.build / "A.png")
expect("tempo: first section", abs(d["grid"][0]["bpm"] - TRUTH["bpm"][0]) < 0.15, d["grid"][0])
expect("tempo: second section", abs(d["grid"][1]["bpm"] - TRUTH["bpm"][1]) < 0.15, d["grid"][1])
expect("section boundary found", min(abs(b["t"] - TRUTH["switch"]) for b in d["boundaries"]) < 0.5, d["boundaries"])
g = d["grid"][0]
beat = 60 / g["bpm"]
phase = ((g["offset"] + beat / 2) % beat) - beat / 2
expect("bar grid lands on the kick", abs(phase) < 0.02, phase)
analysis = read_json(ep.build / "A.json")


def run_case(mutate, name="case"):
    m = copy.deepcopy(MANIFEST)
    mutate(m)
    folder = fresh(name, m)
    e = Episode(folder)
    write_json(e.build / "analysis" / "A.json", analysis)
    e.approve("script")
    e.approve("listening")
    install_placeholder(e)
    tl, _ = timeline.build(e)
    return e, tl, qa.run_all(e, tl)


def fired(r, rule):
    return any(i["rule"] == rule for i in r.fails)


e, tl, r = run_case(lambda m: None, "clean")
expect("clean episode has no failures", not r.fails, r.fails)
kinds = [v["src"][:4] for v in sorted(tl["video"], key=lambda v: v["t"])]
expect("full-screen graphics reach the picture track", kinds.count("gfx:") == 3, kinds)
expect("picture has no zero-length shots", all(v["dur"] > 0.03 for v in tl["video"]), tl["video"])
expect("clip restores the bed afterwards", any(b.get("clip") for b in tl["bed"]) and not tl["bed"][-1]["clip"])

CASES = {
    "music.no_replay": lambda m: section(m, "body")["music"].__setitem__(0, {"src": "A", "in": 0, "at": "start"}),
    "video.no_replay": lambda m: section(m, "clip")["video"].__setitem__(0, {"src": "A02", "in": 4.0, "at": "start"}),
    "music.bar_cut": lambda m: section(m, "body")["music"].__setitem__(0, {"src": "A", "in": 22.9, "at": "start", "free": False, "lock": True}) or section(m, "open")["music"][0].update(free=False),
    "music.crossfade": lambda m: section(m, "body")["music"][0].update(xf=0.3),
    "music.switch": lambda m: section(m, "body")["music"][0].update({"in": 40.0}),
    "audio.no_stems": lambda m: m["sources"]["music"]["A"].update(stem=True),
    "script.timecode": lambda m: para(m, "p01").update(text="到了 1:40 这里，就是满能量。"),
    "script.names": lambda m: para(m, "p01").update(text="HOPICO 说过，这首满能量。"),
    "script.earlier": lambda m: para(m, "p01").update(text="上一期我们讲过这首。"),
    "script.unconfirmed": lambda m: para(m, "p01").update(text="这里是电吉他。⚠️"),
    "script.ear_claim": lambda m: para(m, "p02").update(text="这条底鼓用的是古筝。"),
    "script.ending": lambda m: para(m, "p06").update(text="谢谢观看。"),
    "script.spec_density": lambda m: para(m, "p01").update(text="低音在 G1，大约四十九赫兹，低了将近一个八度，声像最窄，高频是十六分音符。"),
    "voice.digits": lambda m: para(m, "p01").update(text="速度是 126，满能量。"),
    "subs.en_count": lambda m: para(m, "p01").update(en=["One.", "Two."]),
    "duration": lambda m: m.update(target_seconds=20, target_tolerance=0.05),
    "end.owners": lambda m: m["owners"].append("别的版权方"),
    "license.pending": lambda m: m["sources"]["video"]["A02"].update(license="pending"),
    "layout.over_full": lambda m: section(m, "open")["gfx"][1].update({"until": "end+1.0"}),
}
for rule, mutate in CASES.items():
    _, _, r = run_case(mutate, "case")
    expect("stops " + rule, fired(r, rule), [i["rule"] for i in r.fails])

_, tl, r = run_case(lambda m: section(m, "body")["music"][0].update({"in": 40.0, "through": "the switch is the point of this shot"}), "case")
expect("a stated reason can cross a switch", not fired(r, "music.switch"))

e, tl, r = run_case(lambda m: None, "stale")
para_file = e.file
para_file.write_text(para_file.read_text(encoding="utf-8").replace("满能量", "满功率"), encoding="utf-8")
e2 = Episode(e.dir)
expect("script approval goes stale when words change", not e2.approved("script"))

a, issues = compare_reading("大衩", "大差")
wrong, none = compare_reading("丑角", "愁角")
expect("reading check catches a wrong tone", wrong < 1.0, wrong)
same, none = compare_reading("是", "事")
expect("reading check accepts exact homophones", same == 1.0, same)
sandhi, issues = compare_reading("底鼓踩了将近一分钟", "低谷踩了将近一分钟")
expect("reading check allows third-tone sandhi heard as first tone", sandhi == 1.0 and not issues, issues)
missing, issues = compare_reading("底鼓踩了", "踩了")
expect("reading check still catches a dropped word", missing < 1.0 and issues, issues)


def bbox_case(params, rule, orient):
    m = copy.deepcopy(MANIFEST)
    section(m, "open")["gfx"].append({"type": "big", "at": "p01", "dur": 1.0, "params": params})
    folder = fresh("layout", m)
    e = Episode(folder)
    write_json(e.build / "analysis" / "A.json", analysis)
    install_placeholder(e)
    tl, _ = timeline.build(e)
    gfx.render_all(e, tl, orient)
    r = qa.Report()
    qa.check_layout(e, tl, r, orient)
    expect(f"stops {rule} ({orient})", any(i["rule"] == rule for i in r.fails), r.items)


bbox_case({"lines": ["压字幕"], "size": 80, "y": 950}, "layout.subtitle_clash", "h")
bbox_case({"lines": ["太靠上"], "size": 80, "y": 120}, "layout.safe_zone", "v")
bbox_case({"lines": ["这一行字非常非常非常非常非常非常非常长这一行字非常非常非常非常长"], "size": 120, "y": 400}, "layout.offscreen", "h")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
