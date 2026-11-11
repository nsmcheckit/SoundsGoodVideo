"""One frame of every scene in both orientations, for checking the look by eye."""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sgv.gfx import SIZES, Stage  # noqa: E402

OUT = Path(__file__).parent / "_work"
SCENES = [
    ("title", {"_full": 1, "title": "冥火流星", "sub": "一半 Trance，一半 Techno", "kicker": "BOSS THEME BREAKDOWN", "seal": "曲"}, 8),
    ("compare", {"_full": 1, "title": "先分清这两个词", "kicker": "TECHNO VS TRANCE", "cols": [
        {"name": "Techno", "en": "DETROIT · 1980S", "points": ["四拍底鼓从头踩到尾", "几乎只用机器", "靠音色和律动往前推"], "foot": "推着身体走"},
        {"name": "Trance", "en": "EUROPE · 1990S", "points": ["保留四拍骨架", "重心挪到旋律", "breakdown 抽掉鼓再砸回来"], "foot": "拽着情绪走"}]}, 8),
    ("layers", {"_full": 1, "title": "胡琴进来之后", "kicker": "LAYERS", "seconds": 20, "layers": [
        {"name": "底鼓", "spans": [[0, 20]]}, {"name": "低音", "spans": [[0, 12], [15, 20]]}, {"name": "胡琴", "spans": [[10, 20]], "hot": True}], "marks": [{"t": 10, "text": "胡琴开口"}]}, 12),
    ("steps", {"_full": 1, "title": "四拍底鼓", "kicker": "FOUR ON THE FLOOR", "bpm": 132, "note": "每一拍都踩一下", "rows": [{"name": "底鼓", "hits": [0, 4, 8, 12], "hot": True}, {"name": "踩镲", "hits": [2, 6, 10, 14]}]}, 8),
    ("curve", {"_full": 1, "title": "转阶段的响度", "kicker": "LOUDNESS", "unit": "LUFS", "values": [-24, -23, -22, -20, -18, -16, -13, -11, -40, -42, -6, -7, -8, -7], "marks": [{"at": 0.62, "text": "半秒静音"}, {"at": 0.78, "text": "嗡"}]}, 7),
    ("needles", {"_full": 1, "title": "一针比一针高", "kicker": "8 BARS · 实测", "note": "每小节扎一下", "foot": "连着八下",
                 "values": [0, 2, 3, 5, 6, 7, 8, 10], "bar": 1.818, "lead": 0.4}, 16),
    ("number", {"from": 126, "to": 132, "unit": "BPM · 每分钟拍数"}, 4),
    ("loops", {"_full": 1, "title": "同一段循环，一轮比一轮轻", "kicker": "LOOP", "note": "最狠的那一下，只给你一次", "bars": [{"label": "第一轮", "v": 0.95, "value": "-9"}, {"label": "第二轮", "v": 0.6, "value": "-17"}, {"label": "第三轮", "v": 0.58, "value": "-17"}]}, 8),
    ("roles", {"_full": 1, "title": "三种声音，三个人", "kicker": "THREE VOICES", "rows": [{"name": "锣鼓与唢呐", "desc": "舞狮尊主烈焰，传统", "seal": "狮"}, {"name": "合成器与 808", "desc": "梦差，机关术的力量", "seal": "差"}, {"name": "电吉他", "desc": "魂，新锐而叛逆", "seal": "魂"}]}, 8),
    ("quote", {"_full": 1, "text": "以中式音乐为骨，西式音乐为肉；去掉中国乐器那一层，音乐就立不住。", "source": "薄彩生，中国日报专访"}, 8),
    ("big", {"_full": 1, "lines": ["唢呐一响", "不是大喜，就是大悲"]}, 8),
    ("ask", {"text": "猜猜这是哪个游戏的 Boss 曲？"}, 6),
    ("end", {"owners": ["游戏画面与音乐版权归 S-GAME 所有"]}, 6),
]

for orient, cols, scale in (("h", 4, 0.25), ("v", 6, 0.3)):
    w, h = SIZES[orient]
    tw, th = int(w * scale), int(h * scale)
    rows = (len(SCENES) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), (45, 45, 45))
    with Stage() as st:
        for i, (kind, params, dur) in enumerate(SCENES):
            st.frame(kind, params, dur * 0.72, dur, w, h)
            p = OUT / "_g.png"
            p.write_bytes(st.png())
            im = Image.open(p).convert("RGBA").resize((tw, th))
            base = Image.new("RGBA", im.size, (45, 60, 80, 255))
            base.alpha_composite(im)
            sheet.paste(base.convert("RGB"), ((i % cols) * tw, (i // cols) * th))
    sheet.save(OUT / f"gallery_{orient}.jpg", quality=90)
