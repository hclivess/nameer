import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DEFAULT_SETTINGS  # noqa: E402
from nameer import MediaInfo, build_name, resolve_target, strip_old_tags  # noqa: E402

FULL = MediaInfo(path="/v/home recording.mkv", vcodec="h264", width=1920, height=1040, fps=23.976, vbitrate=5819,
                 bitdepth=8, hdr="SDR", acodec="aac", acodecs=["aac"], channels="2", abitrate=128,
                 langs=["eng", "cze"], duration=6120, size=4_500_000_000)


def S(**kw):
    return dict(DEFAULT_SETTINGS, **kw)


def test_default_template_matches_readme_example():
    assert build_name(FULL, S()) == "home_recording_H264_1040p_24fps_5819kbs_AAC_2ch_eng_cze.mkv"


def test_empty_tokens_take_their_suffix_with_them():
    info = MediaInfo(path="/v/clip.mp4", vcodec="hevc", height=2160, fps=60, flags=["no_audio"])
    assert build_name(info, S()) == "clip_HEVC_2160p_60fps_no_audio.mp4"


def test_dot_separator_and_lower_case():
    s = S(template="{name}.{height}p.{vcodec}.{acodec}.{channels}ch", separator=".", case="lower")
    assert build_name(FULL, s) == "home.recording.1040p.h264.aac.2ch.mkv"


def test_rerun_is_idempotent():
    first = build_name(FULL, S())
    again = MediaInfo(**{**FULL.__dict__, "path": "/v/" + first})
    assert build_name(again, S()) == first


def test_strip_keeps_short_real_words():
    assert strip_old_tags("Let it be", "_") == "Let_it_be"
    assert strip_old_tags("the_end_eng", "_") == "the_end_eng"
    assert strip_old_tags("show_S01E02_hevc_2160p_24fps_8000kbs_EAC3_5.1ch_eng_cze_HDR_10bit", "_") == "show_S01E02"


def test_illegal_characters_dropped():
    info = MediaInfo(path='/v/what: "is" this?.mkv', vcodec="h264", height=720, fps=25)
    assert build_name(info, S()) == "what_is_this_H264_720p_25fps.mkv"


def test_resolve_target_numbering(tmp_path):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"x")
    (tmp_path / "b.mkv").write_bytes(b"x")
    assert resolve_target(str(src), "b.mkv", "number") == str(tmp_path / "b_2.mkv")
    assert resolve_target(str(src), "b.mkv", "skip") is None
    assert resolve_target(str(src), "b.mkv", "overwrite") == str(tmp_path / "b.mkv")
    assert resolve_target(str(src), "a.mkv", "skip") == str(src)


def test_collect_natural_order(tmp_path):
    from nameer import collect
    sub = tmp_path / "b"
    sub.mkdir()
    for n in ("clip10.mkv", "clip2.mkv", "Clip1.mkv", "notes.txt"):
        (tmp_path / n).write_bytes(b"")
    (sub / "ep9.mp4").write_bytes(b"")
    (sub / "ep10.mp4").write_bytes(b"")
    got = [os.path.relpath(p, tmp_path) for p in collect([str(tmp_path)])]
    assert got == ["Clip1.mkv", "clip2.mkv", "clip10.mkv", os.path.join("b", "ep9.mp4"), os.path.join("b", "ep10.mp4")]


def test_natural_sorted_paths():
    from utils.naturalsort import natural_sorted
    assert natural_sorted(["x/img10.jpg", "x/img2.jpg", "x/IMG1.jpg"]) == ["x/IMG1.jpg", "x/img2.jpg", "x/img10.jpg"]
