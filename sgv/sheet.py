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
        card = {"id": q["id"], "question": q["question"], "options": q.get("options") or [], "context": q.get("context", ""),
                "range": "", "src": "", "audio": ""}
        if q.get("src"):
            data = base64.b64encode(_clip(ep, q, folder).read_bytes()).decode()
            card.update(range=f"{int(q['in'] // 60)}:{q['in'] % 60:04.1f} – {int(q['out'] // 60)}:{q['out'] % 60:04.1f}",
                        src=q.get("label", q["src"]), audio="data:audio/mpeg;base64," + data)
        cards.append(card)
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


TEMPLATE = """<title>听辨单 · __TITLE__</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;600&family=Noto+Serif+SC:wght@700;900&display=swap">
<style>
/* One column of listening cards; answers save as they are picked. */
:root{--bg:#f6f2ea;--panel:#fffdf8;--line:#e3d9c6;--fg:#231d14;--muted:#6f6352;--gold:#9a7428;--gold-soft:#efe2c2;--red:#c23a28;
 --serif:"Noto Serif SC","Songti SC",serif;--sans:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e0c0a;--panel:#18140f;--line:#3a3022;--fg:#f4ead8;--muted:#b3a68e;--gold:#d9b46c;--gold-soft:#3a2f1c;--red:#e5432f;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0e0c0a;--panel:#18140f;--line:#3a3022;--fg:#f4ead8;--muted:#b3a68e;--gold:#d9b46c;--gold-soft:#3a2f1c;--red:#e5432f;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font:15px/1.65 var(--sans);padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
main{max-width:720px;margin:0 auto;padding-block:28px 120px;display:flex;flex-direction:column;gap:14px}
header{display:flex;flex-direction:column;gap:4px;margin-bottom:8px}
.eyebrow{font-size:12px;letter-spacing:.14em;color:var(--red);font-weight:600}
h1{font:900 28px/1.25 var(--serif);margin:0;color:var(--gold);text-wrap:balance}
.lead{color:var(--muted);margin:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.card.done{border-color:var(--gold)}
.head{display:flex;gap:10px;align-items:baseline}
.qid{font:600 12px var(--sans);color:var(--gold);letter-spacing:.06em;font-variant-numeric:tabular-nums;flex:none}
.q{font-weight:600;font-size:16px;margin:0;min-width:0}
.ctx{color:var(--muted);font-size:13.5px;margin:0}
.rg{color:var(--gold);font-size:12.5px;margin:0;font-variant-numeric:tabular-nums}
audio{width:100%}
.opts{display:flex;flex-wrap:wrap;gap:8px}
button.o{background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:999px;padding:7px 14px;font:inherit;font-size:14px;cursor:pointer;min-height:40px;text-align:left}
button.o:hover{border-color:var(--gold)}
button.o[aria-pressed="true"]{background:var(--gold);color:var(--bg);border-color:var(--gold);font-weight:600}
button:focus-visible,textarea:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
textarea{width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:inherit;font-size:14px;min-height:40px;resize:vertical}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line);padding:10px max(16px,env(safe-area-inset-right,0px)) calc(10px + env(safe-area-inset-bottom,0px)) max(16px,env(safe-area-inset-left,0px))}
.bar div{max-width:720px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
#count{font-variant-numeric:tabular-nums}
#status{color:var(--muted);font-size:13px}
#copy{background:var(--red);color:#fff;border:0;border-radius:8px;padding:9px 16px;font:inherit;font-weight:600;cursor:pointer;min-height:40px}
@media (prefers-reduced-motion:no-preference){button.o{transition:background .15s,border-color .15s}}
</style>
<main>
<header><span class="eyebrow">SOUNDSGOOD · 听辨单</span><h1>__TITLE__</h1>
<p class="lead">每条先听片段，再点选一个答案；拿不准就选“听不出来”，有补充写在备注里。答案会自动保存，我这边直接读取。</p></header>
<div id="list"></div>
</main>
<div class="bar"><div><span><strong id="count"></strong> <span id="status">正在连接保存服务…</span></span><button id="copy" hidden>复制全部答案</button></div></div>
<script>
const CARDS=__CARDS__,KEY="sheet-"+__EP__;
let A={};try{A=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
let db=null,col=null;const pending={};
const status=document.getElementById("status"),count=document.getElementById("count"),copyBtn=document.getElementById("copy");
function local(){try{localStorage.setItem(KEY,JSON.stringify(A))}catch(e){}}
function refresh(){const n=CARDS.filter(c=>A[c.id]&&A[c.id].value).length;count.textContent=`已答 ${n} / ${CARDS.length}`;
 CARDS.forEach(c=>{const el=document.getElementById("c-"+c.id);el.classList.toggle("done",!!(A[c.id]&&A[c.id].value));
  el.querySelectorAll("button.o").forEach(b=>b.setAttribute("aria-pressed",A[c.id]&&A[c.id].value===b.dataset.v?"true":"false"));
  const t=el.querySelector("textarea");if(document.activeElement!==t)t.value=(A[c.id]&&A[c.id].note)||"";});}
async function save(id){local();refresh();if(!col)return;clearTimeout(pending[id]);
 pending[id]=setTimeout(async()=>{try{await col.doc(id).set({value:A[id].value||"",note:A[id].note||"",at:new Date().toISOString()});status.textContent="已保存";}
  catch(e){status.textContent=e&&e.code==="invalid_argument"?"你没有写入权限，请用下面的按钮复制答案":"暂时没存上，稍后会再试；也可以复制答案发给我";copyBtn.hidden=false;}},400);}
const list=document.getElementById("list");
CARDS.forEach((c,i)=>{const el=document.createElement("section");el.className="card";el.id="c-"+c.id;
 const h=document.createElement("div");h.className="head";const n=document.createElement("span");n.className="qid";n.textContent=c.id.toUpperCase();
 const q=document.createElement("p");q.className="q";q.textContent=c.question;h.append(n,q);el.append(h);
 if(c.context){const x=document.createElement("p");x.className="ctx";x.textContent=c.context;el.append(x);}
 if(c.audio){const r=document.createElement("p");r.className="rg";r.textContent=`${c.src} · ${c.range}`;const a=document.createElement("audio");a.controls=true;a.preload="none";a.src=c.audio;el.append(r,a);}
 const o=document.createElement("div");o.className="opts";[...c.options,"听不出来"].forEach(v=>{const b=document.createElement("button");b.className="o";b.type="button";b.textContent=v;b.dataset.v=v;
  b.onclick=()=>{A[c.id]=A[c.id]||{};A[c.id].value=v;save(c.id);};o.append(b);});el.append(o);
 const t=document.createElement("textarea");t.id="note-"+c.id;t.placeholder="备注（可选）";t.oninput=()=>{A[c.id]=A[c.id]||{};A[c.id].note=t.value;if(!A[c.id].value&&t.value)A[c.id].value="见备注";save(c.id);};el.append(t);
 list.append(el);});
refresh();
copyBtn.onclick=async()=>{const s=JSON.stringify(A,null,1);try{await navigator.clipboard.writeText(s);copyBtn.textContent="已复制，粘贴给 Claude";}catch(e){status.textContent="复制没成功，请把下面这段选中复制";const pre=document.createElement("pre");pre.textContent=s;pre.style.whiteSpace="pre-wrap";list.append(pre);}};
const timer=setTimeout(()=>{if(!col){status.textContent="保存服务暂时连不上：答案先存在这台设备上，也可以复制发给我";copyBtn.hidden=false;}},10000);
(async()=>{try{db=await window.claude.use("db");}catch(e){db=null}
 if(!db){clearTimeout(timer);status.textContent="这里没法自动保存：请答完后复制发给我";copyBtn.hidden=false;return;}
 col=db.collection("answers");
 col.onSnapshot(snap=>{if(!snap.metadata.fromCache){clearTimeout(timer);status.textContent="答案会自动保存";}
  snap.docs.forEach(d=>{const v=d.data();if(v&&!pending[d.id+"_typing"])A[d.id]={value:v.value||"",note:v.note||""};});local();refresh();},
  e=>{clearTimeout(timer);status.textContent="保存服务断开了：请复制答案发给我";copyBtn.hidden=false;});})();
</script>
"""

__all__ = ["build", "apply_answers", "subprocess"]
