"""Offline unit tests for multi-scene xfade transitions and PiP compositing."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compositor import (
    PIP_CORNERS,
    TRANSITION_TYPES,
    PipConfig,
    TransitionSpec,
    build_pip_filter,
    build_xfade_filter,
)

_LEADING_LABELS_RE = re.compile(r"^((?:\[[^\]]+\])+)")
_TRAILING_LABELS_RE = re.compile(r"((?:\[[^\]]+\])+)$")
_SINGLE_LABEL_RE = re.compile(r"\[([^\]]+)\]")


def _extract_graph_labels(segments: list[str]) -> tuple[list[str], list[str]]:
    """Return (consumed_labels, produced_labels) across filtergraph segments."""
    consumed: list[str] = []
    produced: list[str] = []
    for seg in segments:
        lead = _LEADING_LABELS_RE.match(seg)
        if lead:
            consumed.extend(_SINGLE_LABEL_RE.findall(lead.group(1)))
        trail = _TRAILING_LABELS_RE.search(seg)
        if trail:
            produced.extend(_SINGLE_LABEL_RE.findall(trail.group(1)))
    return consumed, produced


def _assert_label_integrity(
    segments: list[str],
    expected_inputs: set[str],
    expected_output: str,
) -> None:
    """Verify every internal label is produced once and consumed once."""
    consumed, produced = _extract_graph_labels(segments)
    assert len(produced) == len(set(produced)), f"Duplicate produced labels: {produced}"
    produced_set = set(produced)
    consumed_set = set(consumed)
    assert expected_output in produced_set
    assert expected_inputs <= consumed_set

    # Every consumed label must be either an external input or produced internally.
    external_consumed = consumed_set - produced_set
    assert external_consumed == expected_inputs

    # Every produced label except the final output must be consumed internally.
    dangling = produced_set - consumed_set
    assert dangling == {expected_output}


# ---------------------------------------------------------------------------
# TransitionSpec tests
# ---------------------------------------------------------------------------


def test_transition_spec_defaults() -> None:
    spec = TransitionSpec()
    assert spec.type == "fade"
    assert spec.duration == 0.5


@pytest.mark.parametrize(
    "transition_type",
    [
        "fade",
        "wipeleft",
        "wiperight",
        "slideleft",
        "slideright",
        "smoothleft",
        "smoothright",
        "dissolve",
        "zoomin",
    ],
)
def test_transition_spec_supported_types(transition_type: str) -> None:
    assert transition_type in TRANSITION_TYPES
    spec = TransitionSpec(type=transition_type, duration=0.75)
    assert spec.type == transition_type
    assert spec.duration == 0.75


@pytest.mark.parametrize("bad_type", ["", "crossfade", "circleopen", "FADE", "wipe_left"])
def test_transition_spec_invalid_type_raises(bad_type: str) -> None:
    with pytest.raises(ValueError, match="Unknown transition type"):
        TransitionSpec(type=bad_type)


@pytest.mark.parametrize("bad_duration", [0.0, -0.5, -1, math.nan, math.inf, -math.inf])
def test_transition_spec_invalid_duration_raises(bad_duration: float) -> None:
    with pytest.raises(ValueError):
        TransitionSpec(type="fade", duration=bad_duration)


# ---------------------------------------------------------------------------
# build_xfade_filter tests
# ---------------------------------------------------------------------------


def test_build_xfade_two_scenes_offset_math_and_labels() -> None:
    segments, starts = build_xfade_filter(
        scene_labels=["[s0]", "s1"],
        durations=[4.0, 5.0],
        transitions=[TransitionSpec(type="fade", duration=0.5)],
        output_label="[vout]",
    )
    assert starts == pytest.approx([0.0, 3.5])
    assert segments == ["[s0][s1]xfade=transition=fade:duration=0.5:offset=3.5[vout]"]
    _assert_label_integrity(segments, {"s0", "s1"}, "vout")


def test_build_xfade_three_scenes_cumulative_overlap_math() -> None:
    segments, starts = build_xfade_filter(
        scene_labels=["s0", "s1", "s2"],
        durations=[4.0, 5.0, 3.0],
        transitions=[
            TransitionSpec(type="wipeleft", duration=0.5),
            TransitionSpec(type="dissolve", duration=1.0),
        ],
        output_label="merged",
    )
    # Scene 0: starts at 0.0 (ends 4.0)
    # Transition 0: offset = 4.0 - 0.5 = 3.5; cumulative = 3.5 + 5.0 = 8.5
    # Transition 1: offset = 8.5 - 1.0 = 7.5; cumulative = 7.5 + 3.0 = 10.5
    assert starts == pytest.approx([0.0, 3.5, 7.5])
    assert len(segments) == 2
    assert "xfade=transition=wipeleft:duration=0.5:offset=3.5" in segments[0]
    assert "xfade=transition=dissolve:duration=1:offset=7.5" in segments[1]
    assert segments[-1].endswith("[merged]")
    _assert_label_integrity(segments, {"s0", "s1", "s2"}, "merged")


def test_build_xfade_four_scenes_chaining() -> None:
    segments, starts = build_xfade_filter(
        scene_labels=["a", "b", "c", "d"],
        durations=[3.0, 4.0, 2.5, 3.5],
        transitions=[
            TransitionSpec("slideleft", 0.5),
            TransitionSpec("smoothright", 0.5),
            TransitionSpec("zoomin", 0.5),
        ],
        output_label="out",
    )
    # 0.0 -> 2.5 (cum 6.5) -> 6.0 (cum 8.5) -> 8.0 (cum 11.5)
    assert starts == pytest.approx([0.0, 2.5, 6.0, 8.0])
    assert len(segments) == 3
    _assert_label_integrity(segments, {"a", "b", "c", "d"}, "out")


def test_build_xfade_validation_errors() -> None:
    t = TransitionSpec()
    with pytest.raises(ValueError, match="at least 2 scenes"):
        build_xfade_filter(["s0"], [3.0], [], "vout")

    with pytest.raises(ValueError, match="durations"):
        build_xfade_filter(["s0", "s1"], [3.0], [t], "vout")

    with pytest.raises(ValueError, match="transitions"):
        build_xfade_filter(["s0", "s1", "s2"], [3.0, 3.0, 3.0], [t], "vout")

    with pytest.raises(ValueError, match="positive"):
        build_xfade_filter(["s0", "s1"], [0.0, 3.0], [t], "vout")

    with pytest.raises(ValueError, match="positive"):
        build_xfade_filter(["s0", "s1"], [3.0, -1.0], [t], "vout")

    # Transition longer than first scene -> negative offset
    with pytest.raises(ValueError, match="exceeds"):
        build_xfade_filter(["s0", "s1"], [0.4, 3.0], [TransitionSpec("fade", 0.5)], "vout")

    # Transition longer than incoming scene
    with pytest.raises(ValueError, match="exceeds"):
        build_xfade_filter(["s0", "s1"], [3.0, 0.4], [TransitionSpec("fade", 0.5)], "vout")


# ---------------------------------------------------------------------------
# PipConfig tests
# ---------------------------------------------------------------------------


def test_pip_config_defaults() -> None:
    cfg = PipConfig()
    assert cfg.corner == "bottom-right"
    assert cfg.scale == 0.32
    assert cfg.margin == 28
    assert cfg.start == 0.0
    assert cfg.end is None
    assert cfg.radius == 12
    assert cfg.border_color == "#cdd6f4"
    assert cfg.border_width == 2


@pytest.mark.parametrize("corner", ["bottom-right", "bottom-left", "top-right", "top-left"])
def test_pip_config_valid_corners(corner: str) -> None:
    assert corner in PIP_CORNERS
    cfg = PipConfig(corner=corner)
    assert cfg.corner == corner


def test_pip_config_validation_errors() -> None:
    with pytest.raises(ValueError, match="corner"):
        PipConfig(corner="centre")

    with pytest.raises(ValueError, match="scale"):
        PipConfig(scale=0.0)
    with pytest.raises(ValueError, match="scale"):
        PipConfig(scale=1.5)

    with pytest.raises(ValueError, match="margin"):
        PipConfig(margin=-4)

    with pytest.raises(ValueError, match="start"):
        PipConfig(start=-1.0)

    with pytest.raises(ValueError, match="end"):
        PipConfig(start=5.0, end=5.0)
    with pytest.raises(ValueError, match="end"):
        PipConfig(start=5.0, end=3.0)

    with pytest.raises(ValueError, match="radius"):
        PipConfig(radius=-1)

    with pytest.raises(ValueError, match="border_width"):
        PipConfig(border_width=-2)

    with pytest.raises(ValueError, match="border_color"):
        PipConfig(border_color="red;evil=1")


# ---------------------------------------------------------------------------
# build_pip_filter tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("corner", "expected_x", "expected_y"),
    [
        ("bottom-right", "W-w-28", "H-h-28"),
        ("bottom-left", "28", "H-h-28"),
        ("top-right", "W-w-28", "28"),
        ("top-left", "28", "28"),
    ],
)
def test_build_pip_filter_all_four_corners(corner: str, expected_x: str, expected_y: str) -> None:
    cfg = PipConfig(corner=corner, margin=28, start=1.5, end=4.5)
    segments = build_pip_filter("base", "pip", "out", 1920, 1080, cfg)
    graph = ";".join(segments)

    assert f"overlay=x={expected_x}:y={expected_y}" in graph
    assert "enable='between(t,1.5,4.5)'" in graph
    assert "setpts=PTS-STARTPTS+1.5/TB" in graph
    _assert_label_integrity(segments, {"base", "pip"}, "out")


def test_build_pip_filter_even_scaling_border_and_rounded_corners() -> None:
    # 1280 * 0.32 = 409.6 -> round 410 (even)
    # 1001 * 0.31 = 310.31 -> round 310 (even); test an odd round: 1000 * 0.333 = 333 -> _even(333) = 334
    cfg = PipConfig(scale=0.333, radius=12, border_color="#cdd6f4", border_width=2)
    segments = build_pip_filter("[0:v]", "[1:v]", "[vout]", 1000, 600, cfg)
    graph = ";".join(segments)

    assert "scale=w=334:h=-2" in graph
    assert "drawbox=x=0:y=0:w=iw:h=ih:color=#cdd6f4:t=2" in graph
    assert "geq=" in graph
    _assert_label_integrity(segments, {"0:v", "1:v"}, "vout")


def test_build_pip_filter_open_ended_window_and_zero_radius_border() -> None:
    cfg = PipConfig(start=2.0, end=None, radius=0, border_width=0)
    segments = build_pip_filter("base", "pip", "out", 1280, 720, cfg)
    graph = ";".join(segments)

    assert "enable='gte(t,2)'" in graph
    assert "setpts=PTS-STARTPTS+2/TB" in graph
    assert "geq=" not in graph
    assert "drawbox=" not in graph
    _assert_label_integrity(segments, {"base", "pip"}, "out")


def test_build_pip_filter_invalid_dimensions_raise() -> None:
    cfg = PipConfig()
    with pytest.raises(ValueError, match="positive"):
        build_pip_filter("base", "pip", "out", 0, 720, cfg)
    with pytest.raises(ValueError, match="positive"):
        build_pip_filter("base", "pip", "out", 1280, -10, cfg)


# ---------------------------------------------------------------------------
# Host ffmpeg smoke tests
# ---------------------------------------------------------------------------


def _run_framemd5_multi(inputs: list[str], filter_complex: str, out_label: str = "vout") -> list[str]:
    """Run ffmpeg with synthetic lavfi inputs and return per-frame MD5 hashes."""
    cmd = ["ffmpeg", "-v", "error", "-hide_banner"]
    for src in inputs:
        cmd.extend(["-f", "lavfi", "-i", src])
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{out_label}]",
            "-f",
            "framemd5",
            "-",
        ]
    )
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return [
        line.split(",")[-1].strip() for line in proc.stdout.splitlines() if line and not line.startswith("#")
    ]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg binary not available on host")
def test_ffmpeg_smoke_three_scene_xfade_runs_cleanly() -> None:
    # Three 2.0s scenes at 5fps with two 0.4s transitions -> 5.2s total (26 frames)
    inputs = [
        "color=c=red:s=160x90:r=5:d=2",
        "color=c=green:s=160x90:r=5:d=2",
        "color=c=blue:s=160x90:r=5:d=2",
    ]
    segments, starts = build_xfade_filter(
        scene_labels=["0:v", "1:v", "2:v"],
        durations=[2.0, 2.0, 2.0],
        transitions=[
            TransitionSpec(type="fade", duration=0.4),
            TransitionSpec(type="wipeleft", duration=0.4),
        ],
        output_label="vout",
    )
    assert starts == pytest.approx([0.0, 1.6, 3.2])

    hashes = _run_framemd5_multi(inputs, ";".join(segments))
    assert len(hashes) == 26
    # Early red frame, middle green frame, and late blue frame must all be distinct.
    assert len({hashes[1], hashes[11], hashes[24]}) == 3


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg binary not available on host")
def test_ffmpeg_smoke_pip_overlay_respects_enable_window() -> None:
    width, height = 160, 90
    base_src = f"color=c=navy:s={width}x{height}:r=5:d=3"
    pip_src = "color=c=orange:s=160x90:r=5:d=2"

    base_hashes = _run_framemd5_multi([base_src], "[0:v]null[vout]")
    assert len(base_hashes) == 15

    cfg = PipConfig(
        corner="bottom-right",
        scale=0.35,
        margin=8,
        start=1.0,
        end=2.0,
        radius=6,
        border_color="#cdd6f4",
        border_width=2,
    )
    segments = build_pip_filter("0:v", "1:v", "vout", width, height, cfg)
    pip_hashes = _run_framemd5_multi([base_src, pip_src], ";".join(segments))

    assert len(pip_hashes) == len(base_hashes)
    # Frame 1 (t=0.2s, before start=1.0s) matches base; frame 7 (t=1.4s, inside [1.0, 2.0]) differs;
    # frame 13 (t=2.6s, after end=2.0s) matches base again.
    assert pip_hashes[1] == base_hashes[1]
    assert pip_hashes[7] != base_hashes[7]
    assert pip_hashes[13] == base_hashes[13]
