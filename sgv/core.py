"""Small shared helpers and the fixed production constants."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

import yaml

FPS = 30
SR = 48000
REPO = Path(__file__).resolve().parent.parent
ASR_MODEL = REPO / ".models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"

# Chinese and English narration voices confirmed on earlier episodes.
VOICE_ZH = "5eoK8NqMBsMdqUmImHNs"
VOICE_EN = "UgBBYS2sOqTuMpoF3BR0"
TTS_MODEL = "eleven_v3"
TTS_SPEED = 1.2
# Measured at 1.2x on the lion-dance episode. The old 5.4 figure ran long every time.
EST_CPS = 4.6


def run(cmd):
    subprocess.run([str(c) for c in cmd], check=True)


def probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def has_audio(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return bool(r.stdout.strip())


def to_frames(t):
    return int(round(t * FPS))


def ts(t):
    """Human timestamp, e.g. 3:07.4"""
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


def digest(*parts):
    return hashlib.sha1("\x00".join(str(p) for p in parts).encode()).hexdigest()[:16]


def file_key(path):
    p = Path(path)
    s = p.stat()
    return f"{p.name}:{s.st_size}:{int(s.st_mtime)}"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def clean_text(s):
    """Letters, digits and CJK only, lowercased; used for matching script against speech."""
    return re.sub(r"[^\w]", "", s).replace("_", "").lower()


def spoken_chars(s):
    """Rough count of spoken syllables, used to estimate narration length."""
    latin = re.findall(r"[A-Za-z]+", s)
    rest = re.sub(r"[A-Za-z]+", "", s)
    return len(clean_text(rest)) + sum(max(1, round(len(w) / 3)) for w in latin)


class Episode:
    """An episode folder: episode.yaml, assets/, build/."""

    def __init__(self, folder):
        self.dir = Path(folder).resolve()
        self.file = self.dir / "episode.yaml"
        self.data = yaml.safe_load(self.file.read_text(encoding="utf-8"))
        self.build = self.dir / "build"
        self.build.mkdir(parents=True, exist_ok=True)
        lex = yaml.safe_load((REPO / "sgv" / "lexicon.yaml").read_text(encoding="utf-8"))
        own = self.data.get("lexicon") or {}
        self.lexicon = {
            "replace": {**(lex.get("replace") or {}), **(own.get("replace") or {})},
            "listen": sorted(set((lex.get("listen") or []) + (own.get("listen") or []))),
            "latin_ok": sorted(set((lex.get("latin_ok") or []) + (own.get("latin_ok") or []))),
        }

    @property
    def id(self):
        return self.data["id"]

    @property
    def sections(self):
        return self.data["sections"]

    @property
    def paras(self):
        return [p for s in self.sections for p in s.get("paras", [])]

    def path(self, rel):
        p = Path(rel)
        return p if p.is_absolute() else self.dir / p

    def music(self, key):
        return self.data["sources"]["music"][key]

    def video(self, key):
        return self.data["sources"]["video"][key]

    def spoken(self, para):
        """The text sent to the voice model: an explicit override, or the script with the lexicon applied."""
        if para.get("tts"):
            return para["tts"]
        out = para["text"]
        for k in sorted(self.lexicon["replace"], key=len, reverse=True):
            out = out.replace(k, self.lexicon["replace"][k])
        return out

    # ---- approvals -----------------------------------------------------
    @property
    def state_file(self):
        return self.dir / "approvals.json"

    def approvals(self):
        return read_json(self.state_file) if self.state_file.exists() else {}

    def approve(self, gate, note=""):
        s = self.approvals()
        s[gate] = {"note": note, "script_hash": self.script_hash()}
        write_json(self.state_file, s)

    def script_hash(self):
        return digest(*[self.spoken(p) for p in self.paras])

    def approved(self, gate):
        """A script approval goes stale as soon as the words change."""
        a = self.approvals().get(gate)
        if not a:
            return False
        return gate != "script" or a.get("script_hash") == self.script_hash()
