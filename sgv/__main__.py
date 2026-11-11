"""Command line. Usage: python -m sgv <command> <episode folder> [options]"""
import argparse
import sys

from .core import Episode, read_json, ts


def main():
    ap = argparse.ArgumentParser(prog="sgv")
    ap.add_argument("command", choices=["measure", "sheet", "answers", "approve", "plan", "voice", "placeholder", "mix", "gfx", "render", "qa", "pack", "deliver", "all"])
    ap.add_argument("episode")
    ap.add_argument("--src", help="measure: one music source")
    ap.add_argument("--gate", choices=["script", "listening"], help="approve: which gate")
    ap.add_argument("--file", help="answers: JSON from the listening sheet")
    ap.add_argument("--orient", default="h,v", help="render: h, v or h,v")
    ap.add_argument("--seeds", help="voice: comma-separated seeds")
    ap.add_argument("--force", action="store_true", help="render: export even with failed checks (marked DRAFT)")
    ap.add_argument("--lang", default="zh", help="zh (the edit) or en (a dub of it: own narration, subtitles, mix)")
    a = ap.parse_args()
    ep = Episode(a.episode, a.lang)
    globals()["cmd_" + a.command](ep, a)


def cmd_measure(ep, a):
    from .measure import analyze
    from .mix import _source_wav
    for key in ([a.src] if a.src else list(ep.data["sources"].get("music", {}))):
        out = ep.build / "analysis"
        out.mkdir(parents=True, exist_ok=True)
        d = analyze(_source_wav(ep, key), out / f"{key}.json", out / f"{key}.png")
        print(key, ts(d["duration"]), d["integrated_lufs"], "LUFS")
        for g in d["grid"]:
            print(f"  {ts(g['start'])}–{ts(g['end'])}  {g['bpm']} BPM")
        print("  boundaries:", ", ".join(ts(b["t"]) for b in d["boundaries"] if b["strength"] > 0.3))


def cmd_sheet(ep, a):
    from .sheet import build
    print(build(ep))


def cmd_answers(ep, a):
    from .sheet import apply_answers
    missing = apply_answers(ep, a.file)
    print("still unanswered: " + ", ".join(missing) if missing else "listening gate approved")


def cmd_approve(ep, a):
    ep.approve(a.gate)
    print("approved", a.gate)


def cmd_plan(ep, a):
    """Checks the edit before any money is spent on voice or render time."""
    from . import qa, timeline
    tl, _ = timeline.build(ep)
    r = qa.run_all(ep, tl)
    _print_report(tl, r)


def cmd_voice(ep, a):
    from . import voice
    seeds = [int(s) for s in a.seeds.split(",")] if a.seeds else None
    best = voice.build(ep, seeds)
    pace = read_json(ep.build / "vo" / "pace.json")
    print("take", best["take"], "score", best["score"], "seconds", best["seconds"], "chars/s", pace["chars_per_second"])


def cmd_placeholder(ep, a):
    from . import voice
    voice.install_placeholder(ep)
    print("placeholder narration installed")


def cmd_mix(ep, a):
    from . import mix, timeline
    tl, _ = timeline.build(ep)
    out, m = mix.mix(ep, tl, lufs=ep.data.get("lufs", -16.0))
    print(out, m)


def cmd_gfx(ep, a):
    from . import gfx, timeline
    tl, _ = timeline.build(ep)
    for o in a.orient.split(","):
        gfx.render_all(ep, tl, o)
        print("graphics ready", o)


def cmd_render(ep, a):
    from . import compose, gfx, mix, qa, subs, timeline
    tl, _ = timeline.build(ep)
    if tl["estimated"]:
        sys.exit("no narration yet: run voice first")
    audio = ep.build / "audio" / "mix.wav"
    if not audio.exists():
        audio, _ = mix.mix(ep, tl, lufs=ep.data.get("lufs", -16.0))
    orients = a.orient.split(",")
    renders = {o: gfx.render_all(ep, tl, o) for o in orients}
    r = qa.run_all(ep, tl)
    if r.fails and not a.force:
        _print_report(tl, r)
        sys.exit("checks failed: nothing exported")
    suffix = "_DRAFT" if r.fails else ""
    outs = {}
    for o in orients:
        subs.write(ep, tl, o)
        name = {"h": "16x9", "v": "9x16"}[o]
        outs[o] = ep.build / f"{ep.id}_{name}{suffix}.mp4"
        compose.assemble(ep, tl, renders[o], o, audio, outs[o])
        compose.contact_sheet(outs[o], tl, ep.build / f"sheet_{o}.jpg")
        print("exported", outs[o])
    qa.write_review(ep, tl, r)
    _print_report(tl, r)


def cmd_qa(ep, a):
    from . import qa
    tl = read_json(ep.build / "timeline.json")
    r = qa.run_all(ep, tl)
    qa.write_review(ep, tl, r)
    _print_report(tl, r)


def cmd_pack(ep, a):
    from . import pack
    print(pack.publish_text(ep))
    for p in pack.covers(ep):
        print(p)


def cmd_deliver(ep, a):
    import json
    from . import pack
    print(json.dumps(pack.deliver(ep), ensure_ascii=False, indent=1))


def cmd_all(ep, a):
    cmd_voice(ep, a)
    cmd_mix(ep, a)
    cmd_render(ep, a)
    cmd_pack(ep, a)


def _print_report(tl, r):
    print(f"total {ts(tl['total'])}  estimated={tl['estimated']}  FAIL {len(r.fails)}  WARN {len(r.warns)}")
    for i in r.fails + r.warns:
        where = f" @{ts(i['t'])}" if i["t"] is not None else ""
        print(f"  {i['level']} {i['rule']}{where}: {i['msg']}")


if __name__ == "__main__":
    main()
