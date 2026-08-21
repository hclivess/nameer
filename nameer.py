#!/usr/bin/env python3
"""
nameer - engine: probe a video with ffprobe, build a descriptive name from a template, rename safely.

Importable without Qt; `python nameer.py [--dry-run] files...` is the CLI.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULT_SETTINGS, TOKENS, VIDEO_EXTENSIONS  # noqa: E402

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ ffprobe
def find_ffprobe(explicit: str = "") -> Optional[str]:
    """Explicit path, NAMEER_FFPROBE, next to the app, then PATH."""
    exe = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    candidates = [explicit, os.environ.get("NAMEER_FFPROBE", ""), os.path.join(app_dir(), exe)]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("ffprobe")


def ffprobe_version(path: str) -> str:
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10,
                             creationflags=_CREATE_NO_WINDOW).stdout
        return out.splitlines()[0].replace("ffprobe version ", "").split(" ")[0] if out else "?"
    except Exception:
        return "?"


@dataclass
class MediaInfo:
    path: str
    vcodec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vbitrate: int = 0          # kb/s
    bitdepth: int = 0
    hdr: str = ""
    acodec: str = ""
    acodecs: List[str] = field(default_factory=list)
    channels: str = ""
    abitrate: int = 0          # kb/s
    langs: List[str] = field(default_factory=list)
    subs: List[str] = field(default_factory=list)
    duration: float = 0.0
    size: int = 0
    iframes: Optional[int] = None   # None = not checked
    flags: List[str] = field(default_factory=list)


def _channels_label(n: int) -> str:
    return {6: "5.1", 7: "6.1", 8: "7.1"}.get(n, str(n))


def _frame_rate(value: str) -> float:
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _hdr_label(stream: Dict) -> str:
    side = " ".join(s.get("side_data_type", "") for s in stream.get("side_data_list", [])).lower()
    if "dovi" in side or "dolby vision" in side:
        return "DV"
    transfer = stream.get("color_transfer", "")
    if transfer in ("smpte2084", "arib-std-b67"):
        return "HDR"
    return "SDR" if transfer else ""


def _bitdepth(stream: Dict) -> int:
    bpr = stream.get("bits_per_raw_sample")
    if bpr:
        try:
            return int(bpr)
        except ValueError:
            pass
    pix = stream.get("pix_fmt", "")
    m = re.search(r"p?(10|12|16)(le|be)?$", pix)
    return int(m.group(1)) if m else (8 if pix else 0)


def _lang(stream: Dict) -> str:
    tags = {k.lower(): v for k, v in (stream.get("tags") or {}).items()}
    lang = (tags.get("language") or tags.get("lang") or "").strip().lower()
    return "" if lang in ("", "und", "unknown") else lang


def count_iframes(ffprobe: str, path: str, seconds: int) -> int:
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-read_intervals", f"%+{seconds}",
           "-show_entries", "frame=pict_type", "-of", "csv=p=0", path]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300, creationflags=_CREATE_NO_WINDOW).stdout
    return sum(1 for line in out.splitlines() if line.strip().startswith("I"))


def probe(path: str, ffprobe: str, check_iframes: bool = True, iframe_seconds: int = 30, iframe_min: int = 3) -> MediaInfo:
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=_CREATE_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "ffprobe failed").strip().splitlines()[-1])
    data = json.loads(proc.stdout or "{}")
    info = MediaInfo(path=path, size=os.path.getsize(path))
    fmt = data.get("format", {})
    info.duration = float(fmt.get("duration") or 0)
    format_kbps = int(int(fmt.get("bit_rate") or 0) / 1000)

    video_seen = False
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind == "video" and not video_seen:
            if s.get("disposition", {}).get("attached_pic"):
                continue
            video_seen = True
            info.vcodec = s.get("codec_name", "")
            info.width = int(s.get("width") or 0)
            info.height = int(s.get("height") or 0)
            info.fps = _frame_rate(s.get("avg_frame_rate") or s.get("r_frame_rate") or "0")
            info.vbitrate = int(int(s.get("bit_rate") or 0) / 1000)
            info.bitdepth = _bitdepth(s)
            info.hdr = _hdr_label(s)
        elif kind == "audio":
            codec = s.get("codec_name", "")
            if not info.acodec:
                info.acodec = codec
                info.channels = _channels_label(int(s.get("channels") or 0))
                info.abitrate = int(int(s.get("bit_rate") or 0) / 1000)
            if codec and codec not in info.acodecs:
                info.acodecs.append(codec)
            lang = _lang(s)
            if lang and lang not in info.langs:
                info.langs.append(lang)
        elif kind == "subtitle":
            lang = _lang(s)
            if lang and lang not in info.subs:
                info.subs.append(lang)

    if video_seen and not info.vbitrate and format_kbps:
        # MKV hides per-stream bitrates; whole-file bitrate minus audio is the honest estimate
        info.vbitrate = max(0, format_kbps - info.abitrate)
    if not video_seen:
        info.flags.append("no_video")
    if not info.acodec:
        info.flags.append("no_audio")
    if video_seen and check_iframes:
        info.iframes = count_iframes(ffprobe, path, iframe_seconds)
        if info.iframes < iframe_min:
            info.flags.append("i_frame_issue")
    return info


# ------------------------------------------------------------------ naming
_TOKEN_RE = re.compile(r"\{(" + "|".join(re.escape(t) for t in TOKENS) + r")\}")
_FLAGS = ("i_frame_issue", "no_audio", "no_video", "problem")
# "strong" tags can only come from nameer; a trailing run is stripped only if it contains at least one
_STRONG_RE = re.compile(
    r"^(?:\d{3,4}p|\d{1,3}fps|\d+kbs|\d(?:\.\d)?ch|\d+bit|[0-9]+x[0-9]+|\d+h\d{2}m|\d+m|\d+(?:\.\d)?[MG]B|"
    r"h264|h265|hevc|av1|vp8|vp9|mpeg[124]|mpeg4|msmpeg4v[23]|wmv[123]|vc1|prores|mjpeg|theora|"
    r"aac|ac3|eac3|dts|truehd|opus|vorbis|mp3|mp2|flac|alac|pcm_s\d+[lb]e|hdr|dv|sdr)$", re.IGNORECASE)
# "weak" tags (2-3 letter language codes, container) are stripped only as part of such a run
_WEAK_RE = re.compile(r"^(?:[a-z]{2,3}|mkv|mp4|avi|mov|webm)$", re.IGNORECASE)


def _fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return ""
    m = int(seconds // 60)
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def _fmt_size(size: int) -> str:
    if size <= 0:
        return ""
    gb = size / 1024 ** 3
    return f"{gb:.1f}GB" if gb >= 1 else f"{size / 1024 ** 2:.0f}MB"


def strip_old_tags(stem: str, separator: str) -> str:
    """Remove a trailing run of nameer-style tags so re-running never stacks tags twice."""
    s = stem
    for flag in _FLAGS:
        s = re.sub(r"[ _.\-]" + flag + r"(?=$|[ _.\-])", "", s, flags=re.IGNORECASE)
    s = re.sub(r"(\d)\.(\dch)\b", lambda m: m.group(1) + "\x00" + m.group(2), s)   # keep 5.1ch in one piece
    parts = [p.replace("\x00", ".") for p in re.split(r"(?:\s|" + re.escape(separator) + r")+", s) if p]
    kept = list(parts)
    strong = False
    while len(kept) > 1 and (_STRONG_RE.match(kept[-1]) or _WEAK_RE.match(kept[-1])):
        strong = strong or bool(_STRONG_RE.match(kept[-1]))
        kept.pop()
    if not strong:
        kept = parts
    return separator.join(kept)


def _case(value: str, mode: str) -> str:
    return value.upper() if mode == "upper" else value.lower() if mode == "lower" else value


def token_values(info: MediaInfo, settings: Dict) -> Dict[str, str]:
    sep = settings["separator"]
    mode = settings["case"]
    stem = os.path.splitext(os.path.basename(info.path))[0]
    name = re.sub(r"\s*[-_.]\s+|\s+[-_.]\s*|\s+", sep, stem.strip())   # "a - b", "a -b", "a b" -> a<sep>b
    if settings.get("strip_old_tags", True):
        name = strip_old_tags(name, sep)
    fps = round(info.fps)
    return {
        "name": name,
        "vcodec": _case(info.vcodec, mode),
        "height": str(info.height) if info.height else "",
        "width": str(info.width) if info.width else "",
        "fps": str(fps) if fps else "",
        "vbitrate": str(info.vbitrate) if info.vbitrate else "",
        "acodec": _case(info.acodec, mode),
        "acodecs": sep.join(_case(c, mode) for c in info.acodecs),
        "channels": info.channels if info.channels and info.channels != "0" else "",
        "abitrate": str(info.abitrate) if info.abitrate else "",
        "langs": sep.join(info.langs),
        "subs": sep.join(info.subs),
        "duration": _fmt_duration(info.duration),
        "size": _fmt_size(info.size),
        "hdr": info.hdr,
        "bitdepth": f"{info.bitdepth}bit" if info.bitdepth else "",
        "container": os.path.splitext(info.path)[1].lstrip(".").lower(),
        "flags": sep.join(info.flags),
    }


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def build_name(info: MediaInfo, settings: Dict) -> str:
    """Render the template; a token with no value disappears together with the literal text glued to it."""
    sep = settings["separator"]
    values = token_values(info, settings)
    template = settings["template"]
    pieces = []
    for piece in re.split(r"(\{[a-z]+\})", template):
        m = _TOKEN_RE.fullmatch(piece)
        if m:
            pieces.append(("tok", values.get(m.group(1), "")))
        elif piece:
            pieces.append(("lit", piece))
    # literal text directly after an empty token (e.g. "p", "fps", "kbs") is dropped with it
    out = []
    skip_literal = False
    for kind, text in pieces:
        if kind == "tok":
            if text:
                out.append(text)
                skip_literal = False
            else:
                skip_literal = True
        else:
            if skip_literal:
                # keep only the separator characters from the literal, so the next token still separates
                text = "".join(ch for ch in text if ch in " _.-")
                skip_literal = False
            out.append(text)
    name = "".join(out)
    name = _ILLEGAL.sub("", name)
    # collapse doubled separators / trim
    if sep.strip():
        name = re.sub(re.escape(sep) + r"{2,}", sep, name)
    else:
        name = re.sub(r" {2,}", " ", name)
    name = name.strip(" _.-")
    return (name or "unnamed") + os.path.splitext(info.path)[1]


# ------------------------------------------------------------------ renaming
@dataclass
class RenameResult:
    src: str
    dst: str
    status: str        # renamed | unchanged | skipped | dry-run | failed
    message: str = ""
    info: Optional[MediaInfo] = None


def resolve_target(src: str, new_name: str, collision: str) -> Optional[str]:
    folder = os.path.dirname(os.path.abspath(src))
    dst = os.path.join(folder, new_name)
    if os.path.abspath(dst) == os.path.abspath(src) or not os.path.exists(dst):
        return dst
    if collision == "overwrite":
        return dst
    if collision == "skip":
        return None
    stem, ext = os.path.splitext(new_name)
    n = 2
    while os.path.exists(os.path.join(folder, f"{stem}_{n}{ext}")):
        n += 1
    return os.path.join(folder, f"{stem}_{n}{ext}")


def append_undo(folder: str, src: str, dst: str):
    with open(os.path.join(folder, "nameer-undo.log"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"from": os.path.basename(dst), "to": os.path.basename(src)}, ensure_ascii=False) + "\n")


def undo(folder: str) -> int:
    """Rename back everything listed in nameer-undo.log (most recent first). Returns the count restored."""
    log = os.path.join(folder, "nameer-undo.log")
    if not os.path.isfile(log):
        return 0
    with open(log, encoding="utf-8") as fh:
        entries = [json.loads(line) for line in fh if line.strip()]
    restored = 0
    for e in reversed(entries):
        src = os.path.join(folder, e["from"])
        dst = os.path.join(folder, e["to"])
        if os.path.exists(src) and not os.path.exists(dst):
            os.rename(src, dst)
            restored += 1
    os.remove(log)
    return restored


def process_file(path: str, settings: Dict, ffprobe: str, dry_run: bool = False) -> RenameResult:
    try:
        info = probe(path, ffprobe, settings.get("check_iframes", True), int(settings.get("iframe_seconds", 30)),
                     int(settings.get("iframe_min", 3)))
        new_name = build_name(info, settings)
    except Exception as exc:
        return RenameResult(path, "", "failed", str(exc))
    if new_name == os.path.basename(path):
        return RenameResult(path, path, "unchanged", "already named", info)
    dst = resolve_target(path, new_name, settings.get("collision", "number"))
    if dst is None:
        return RenameResult(path, os.path.join(os.path.dirname(path), new_name), "skipped", "target exists", info)
    if dry_run or settings.get("dry_run"):
        return RenameResult(path, dst, "dry-run", "", info)
    try:
        if os.path.exists(dst) and os.path.abspath(dst) != os.path.abspath(path):
            os.remove(dst)
        os.rename(path, dst)
        if settings.get("write_undo", True):
            append_undo(os.path.dirname(os.path.abspath(path)), path, dst)
        return RenameResult(path, dst, "renamed", "", info)
    except OSError as exc:
        return RenameResult(path, dst, "failed", str(exc), info)


def collect(paths: List[str], recurse: bool = True) -> List[str]:
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            walker = os.walk(p) if recurse else [(p, [], os.listdir(p))]
            for folder, _dirs, files in walker:
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS:
                        out.append(os.path.join(folder, f))
        elif os.path.isfile(p) and os.path.splitext(p)[1].lower() in VIDEO_EXTENSIONS:
            out.append(p)
    return out


# ------------------------------------------------------------------ CLI
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Rename video files after their real properties.")
    ap.add_argument("paths", nargs="*", help="files or folders")
    ap.add_argument("-n", "--dry-run", action="store_true", help="show what would happen, rename nothing")
    ap.add_argument("-t", "--template", default=DEFAULT_SETTINGS["template"], help="name template")
    ap.add_argument("-s", "--separator", default=DEFAULT_SETTINGS["separator"])
    ap.add_argument("--case", choices=("upper", "lower", "keep"), default=DEFAULT_SETTINGS["case"])
    ap.add_argument("--no-iframes", action="store_true", help="skip the I-frame sanity check")
    ap.add_argument("--collision", choices=("number", "skip", "overwrite"), default="number")
    ap.add_argument("--undo", metavar="FOLDER", help="restore names from FOLDER/nameer-undo.log and exit")
    ap.add_argument("--tokens", action="store_true", help="list template tokens and exit")
    ap.add_argument("--ffprobe", default="", help="path to ffprobe")
    a = ap.parse_args(argv)
    if a.tokens:
        for k, v in TOKENS.items():
            print(f"{{{k}}}".ljust(12), v)
        return 0
    if a.undo:
        print(f"restored {undo(a.undo)} file(s)")
        return 0
    if not a.paths:
        ap.print_help()
        return 2
    ffprobe = find_ffprobe(a.ffprobe)
    if not ffprobe:
        print("ffprobe not found: install FFmpeg or put ffprobe next to nameer", file=sys.stderr)
        return 1
    settings = dict(DEFAULT_SETTINGS, template=a.template, separator=a.separator, case=a.case,
                    check_iframes=not a.no_iframes, collision=a.collision)
    failed = 0
    for f in collect(a.paths):
        r = process_file(f, settings, ffprobe, a.dry_run)
        failed += r.status == "failed"
        print(f"[{r.status:9}] {os.path.basename(r.src)}  ->  {os.path.basename(r.dst) if r.dst else r.message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
