"""
nameer - configuration and constants (the only place APP_NAME / APP_VERSION live)
"""

APP_NAME = "nameer"
APP_VERSION = "2.0.2"
WINDOW_MIN_WIDTH = 820
WINDOW_MIN_HEIGHT = 560

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".wmv", ".ts", ".m2ts", ".mts", ".mpg",
                    ".mpeg", ".flv", ".ogv", ".3gp", ".vob"}

# Tokens usable in the name template. Each renders to "" when the file has no such stream / value, and
# empty tokens never leave doubled separators behind.
TOKENS = {
    "name": "original base name (spaces → separator, previous nameer tags stripped)",
    "vcodec": "video codec (H264, HEVC, AV1, VP9, ...)",
    "height": "video height (1080, 2160, ...) — use {height}p",
    "width": "video width",
    "fps": "frame rate, rounded (24, 30, 60) — use {fps}fps",
    "vbitrate": "video bitrate in kb/s (stream, or whole-file bitrate when the container hides it)",
    "acodec": "audio codec of the first audio stream (AAC, AC3, EAC3, DTS, OPUS, ...)",
    "acodecs": "all distinct audio codecs",
    "channels": "audio channels of the first audio stream (2, 5.1, 7.1)",
    "abitrate": "audio bitrate of the first audio stream in kb/s",
    "langs": "all distinct audio languages (eng_cze)",
    "subs": "all distinct subtitle languages",
    "duration": "duration as HhMMm (1h42m)",
    "size": "file size in MB or GB (4.2GB)",
    "hdr": "HDR / DV / SDR",
    "bitdepth": "video bit depth (8bit, 10bit)",
    "container": "container (mkv, mp4)",
    "flags": "warnings: i_frame_issue, no_audio, no_video",
}

DEFAULT_TEMPLATE = "{name}_{vcodec}_{height}p_{fps}fps_{vbitrate}kbs_{acodec}_{channels}ch_{langs}_{flags}"

SEPARATORS = {"_": "underscore  a_b", ".": "dot  a.b", "-": "hyphen  a-b", " ": "space  a b"}
CASES = {"upper": "UPPER (H264, AAC)", "lower": "lower (h264, aac)", "keep": "as reported by ffprobe"}
COLLISIONS = {"number": "add a counter (name_2)", "skip": "skip the file", "overwrite": "overwrite"}

DEFAULT_SETTINGS = {
    "template": DEFAULT_TEMPLATE,
    "separator": "_",
    "case": "upper",
    "dry_run": False,
    "check_iframes": True,
    "iframe_seconds": 30,
    "iframe_min": 3,
    "strip_old_tags": True,
    "collision": "number",
    "write_undo": True,
    "recurse": True,
    "ffprobe_path": "",
}
