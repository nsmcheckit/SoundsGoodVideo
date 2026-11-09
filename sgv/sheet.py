"""The listening sheet: every open question, each with its own audio clip, answered once on one page."""
import base64
import html
import json
import subprocess

from .core import read_json, run, write_json
from .mix import _source_wav


def _clip(ep, q, folder):
    out = folder / f"{q['id']}.mp3"
    wav = _source_wav(ep, q["src"])
    a, b = float(q["in"]), float(q["out"])
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", wav,
         "-af", f"afade=t=in:d=0.08,afade=t=out:st={max(0.0, b - a - 0.15):.3f}:d=0.15", "-c:a", "libmp3lame", "-b:a", "128k", out])
    return out


def build(ep):
    questions = ep.data.get("listening") or []
    folder = ep.build / "sheet"
    folder.mkdir(parents=True, exist_ok=True)
    cards = []
    for q in questions:
        data = base64.b64encode(_clip(ep, q, folder).read_bytes()).decode()
        cards.append({"id": q["id"], "question": q["question"], "options": q.get("options") or [], "context": q.get("context", ""),
                      "range": f"{int(q['in'] // 60)}:{q['in'] % 60:04.1f} – {int(q['out'] // 60)}:{q['out'] % 60:04.1f}",
                      "src": q["src"], "audio": "data:audio/mpeg;base64," + data})
    title = html.escape(ep.data.get("title", ep.id))
    page = TEMPLATE.replace("__TITLE__", title).replace("__CARDS__", json.dumps(cards, ensure_ascii=False)).replace("__EP__", json.dumps(ep.id))
    out = folder / "listening.html"
    out.write_text(page, encoding="utf-8")
    return out


def apply_answers(ep, answers_path):
    """Records the answers. Approval needs every question answered."""
    answers = read_json(answers_path)
    questions = ep.data.get("listening") or []
    missing = [q["id"] for q in questions if not (answers.get(q["id"]) or {}).get("value")]
    write_json(ep.build / "listening_answers.json", answers)
    if missing:
        return missing
    ep.approve("listening", "all questions answered")
    return []


TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>听辨单 __TITLE__</title>
<style>
:root{--bg:#0d0b09;--panel:#17130f;--line:#3a2f20;--gold:#d9b46c;--text:#f4ead8;--muted:#b7a98f;--red:#e5432f}
:root:not([data-theme="dark"]){color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 "Noto Sans SC","PingFang SC",system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 16px 96px}h1{font-size:26px;margin:0 0 4px;color:var(--gold)}.sub{color:var(--muted);margin:0 0 24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;margin:0 0 14px}.card.done{border-color:var(--gold)}
.q{font-size:18px;font-weight:600;margin:0 0 6px}.ctx{color:var(--muted);font-size:14px;margin:0 0 10px}.rg{color:var(--gold);font-size:13px;margin:0 0 8px}
audio{width:100%;margin:6px 0 12px}.opts{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
button.o{background:transparent;color:var(--text);border:1px solid var(--line);border-radius:999px;padding:7px 14px;font:inherit;cursor:pointer;min-height:40px}
button.o[aria-pressed="true"]{background:var(--gold);color:#17130f;border-color:var(--gold);font-weight:600}
textarea{width:100%;background:#100d0a;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px;font:inherit;min-height:42px;resize:vertical}
.bar{position:fixed;left:0;right:0;bottom:0;background:#120f0ccc;backdrop-filter:blur(6px);border-top:1px solid var(--line);padding:10px 16px}
.bar div{max-width:760px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:10px}
#copy{background:var(--red);color:#fff;border:0;border-radius:8px;padding:9px 16px;font:inherit;font-weight:600;cursor:pointer;min-height:40px}
</style></head><body><main><h1>听辨单：__TITLE__</h1><p class="sub">每条先听，再选。没有合适的选项就写在备注里。</p><div id="list"></div></main>
<div class="bar"><div><span id="count"></span><button id="copy">复制全部答案</button></div></div>
<script>
const CARDS=__CARDS__,KEY="sheet-"+__EP__;let A={};try{A=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(A))}catch(e){}};
const list=document.getElementById("list"),count=document.getElementById("count");
function refresh(){const n=CARDS.filter(c=>A[c.id]&&A[c.id].value).length;count.textContent=`已答 ${n} / ${CARDS.length}`;CARDS.forEach(c=>document.getElementById("c-"+c.id).classList.toggle("done",!!(A[c.id]&&A[c.id].value)));}
CARDS.forEach(c=>{const el=document.createElement("section");el.className="card";el.id="c-"+c.id;
 const q=document.createElement("p");q.className="q";q.textContent=c.question;el.append(q);
 if(c.context){const x=document.createElement("p");x.className="ctx";x.textContent=c.context;el.append(x);}
 const r=document.createElement("p");r.className="rg";r.textContent=`${c.src} · ${c.range}`;el.append(r);
 const a=document.createElement("audio");a.controls=true;a.preload="none";a.src=c.audio;el.append(a);
 const o=document.createElement("div");o.className="opts";
 const all=[...c.options,"听不出来"];all.forEach(v=>{const b=document.createElement("button");b.className="o";b.textContent=v;b.setAttribute("aria-pressed",A[c.id]&&A[c.id].value===v?"true":"false");
  b.onclick=()=>{A[c.id]=A[c.id]||{};A[c.id].value=v;[...o.children].forEach(k=>k.setAttribute("aria-pressed",k===b?"true":"false"));save();refresh();};o.append(b);});el.append(o);
 const t=document.createElement("textarea");t.placeholder="备注（可选）";t.value=(A[c.id]&&A[c.id].note)||"";t.oninput=()=>{A[c.id]=A[c.id]||{};A[c.id].note=t.value;if(!A[c.id].value&&t.value)A[c.id].value="见备注";save();refresh();};el.append(t);
 list.append(el);});refresh();
document.getElementById("copy").onclick=async e=>{const s=JSON.stringify(A,null,1);try{await navigator.clipboard.writeText(s);e.target.textContent="已复制，粘贴给 Claude"}catch(x){prompt("复制下面的内容",s)}};
</script></body></html>
"""

__all__ = ["build", "apply_answers", "subprocess"]
