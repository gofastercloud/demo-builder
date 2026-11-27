"""Offline unit tests for zoom and highlight ffmpeg compositor effects."""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compositor import (
    HighlightEvent,
    ZoomEvent,
    build_highlight_filter,
    build_zoom_filter,
    ease_zoom_progress,
    resolve_region,
)


def _eval_ffmpeg_expr(expr: str, **variables: float) -> float:
    """Evaluate a pure ffmpeg math expression in Python for boundary verification."""

    def _between(val: float, low: float, high: float) -> float:
        return 1.0 if low <= val <= high else 0.0

    def _clip(val: float, low: float, high: float) -> float:
        return max(low, min(val, high))

    def _if(cond: float, truthy: float, falsy: float = 0.0) -> float:
        return truthy if cond else falsy

    def _lt(a: float, b: float) -> float:
        return 1.0 if a < b else 0.0

    def _gt(a: float, b: float) -> float:
        return 1.0 if a > b else 0.0

    # Replace `if(` with `_if(` so it is valid Python syntax.
    py_expr = re.sub(r"\bif\(", "_if(", expr)
    env: dict[str, object] = {
        "PI": math.pi,
        "cos": math.cos,
        "sin": math.sin,
        "between": _between,
        "clip": _clip,
        "_if": _if,
        "lt": _lt,
        "gt": _gt,
        **variables,
    }
    return float(eval(py_expr, {"__builtins__": {}}, env))


def _extract_crop_expressions(segment: str) -> dict[str, str]:
    """Extract w, h, x, y expressions from a crop=... filter segment."""
    match = re.search(
        r"crop=w='([^']+)':h='([^']+)':x='([^']+)':y='([^']+)'",
        segment,
    )
    assert match is not None, f"Could not find crop expressions in: {segment}"
    return {
        "w": match.group(1),
        "h": match.group(2),
        "x": match.group(3),
        "y": match.group(4),
    }


# ---------------------------------------------------------------------------
# Dataclass defaults & validation
# ---------------------------------------------------------------------------


def test_zoom_event_defaults_and_validation() -> None:
    ev = ZoomEvent(start=1.0, end=4.0, x=100, y=120, w=400, h=200)
    assert ev.scale == 1.6
    assert ev.ease_ms == 350

    with pytest.raises(ValueError, match="start"):
        ZoomEvent(start=-0.5, end=2.0, x=0, y=0, w=100, h=100)
    with pytest.raises(ValueError, match="end"):
        ZoomEvent(start=2.0, end=2.0, x=0, y=0, w=100, h=100)
    with pytest.raises(ValueError, match="end"):
        ZoomEvent(start=3.0, end=2.0, x=0, y=0, w=100, h=100)
    with pytest.raises(ValueError, match="scale"):
        ZoomEvent(start=1.0, end=3.0, x=0, y=0, w=100, h=100, scale=0.9)
    with pytest.raises(ValueError, match="ease_ms"):
        ZoomEvent(start=1.0, end=3.0, x=0, y=0, w=100, h=100, ease_ms=-10)
    with pytest.raises(ValueError, match="dimensions"):
        ZoomEvent(start=1.0, end=3.0, x=0, y=0, w=0, h=100)
    with pytest.raises(ValueError, match="dimensions"):
        ZoomEvent(start=1.0, end=3.0, x=0, y=0, w=100, h=-5)


def test_highlight_event_defaults_and_validation() -> None:
    ev = HighlightEvent(start=0.5, end=2.5, x=50, y=60, w=300, h=150)
    assert ev.style == "spotlight"
    assert ev.dim_opacity == 0.45
    assert ev.color == "#38bdf8"
    assert ev.border_width == 3

    with pytest.raises(ValueError, match="start"):
        HighlightEvent(start=-1.0, end=1.0, x=0, y=0, w=100, h=100)
    with pytest.raises(ValueError, match="end"):
        HighlightEvent(start=2.0, end=1.5, x=0, y=0, w=100, h=100)
    with pytest.raises(ValueError, match="style"):
        HighlightEvent(start=1.0, end=3.0, x=0, y=0, w=100, h=100, style="glow")
    with pytest.raises(ValueError, match="dim_opacity"):
        HighlightEvent(start=1.0, end=3.0, x=0, y=0, w=100, h=100, dim_opacity=1.2)
    with pytest.raises(ValueError, match="dim_opacity"):
        HighlightEvent(start=1.0, end=3.0, x=0, y=0, w=100, h=100, dim_opacity=-0.1)
    with pytest.raises(ValueError, match="border_width"):
        HighlightEvent(start=1.0, end=3.0, x=0, y=0, w=100, h=100, border_width=-1)
    with pytest.raises(ValueError, match="color"):
        HighlightEvent(start=1.0, end=3.0, x=0, y=0, w=100, h=100, color="")
    with pytest.raises(ValueError, match="dimensions"):
        HighlightEvent(start=1.0, end=3.0, x=0, y=0, w=0, h=50)


# ---------------------------------------------------------------------------
# Region normalisation & clamping
# ---------------------------------------------------------------------------


def test_resolve_region_pixel_and_normalised_inputs() -> None:
    # Pixel coordinates from tuple, mapping, and dataclass.
    assert resolve_region((100, 120, 400, 200), 1280, 720) == (100, 120, 400, 200)
    assert resolve_region({"x": 100, "y": 120, "w": 400, "h": 200}, 1280, 720) == (100, 120, 400, 200)
    ev = ZoomEvent(start=1.0, end=3.0, x=100, y=120, w=400, h=200)
    assert resolve_region(ev, 1280, 720) == (100, 120, 400, 200)

    # Normalised [0.0, 1.0] coordinates auto-converted to pixels.
    assert resolve_region((0.25, 0.25, 0.5, 0.5), 1280, 720) == (320, 180, 640, 360)
    norm_hl = HighlightEvent(start=0.0, end=2.0, x=0.1, y=0.2, w=0.5, h=0.25)
    assert resolve_region(norm_hl, 1000, 800) == (100, 160, 500, 200)

    # Full-frame normalised region.
    assert resolve_region((0.0, 0.0, 1.0, 1.0), 1280, 720) == (0, 0, 1280, 720)


def test_resolve_region_clamps_to_frame_bounds() -> None:
    # Negative origin trimmed against left/top edge.
    assert resolve_region((-50, -20, 300, 200), 1280, 720) == (0, 0, 250, 180)

    # Overflowing right/bottom edge trimmed to frame boundary.
    assert resolve_region((1100, 600, 400, 300), 1280, 720) == (1100, 600, 180, 120)

    # Normalised region overflowing 1.0 clamped cleanly.
    assert resolve_region((0.8, 0.75, 0.5, 0.5), 1000, 800) == (800, 600, 200, 200)

    # Completely out-of-bounds region still stays strictly inside frame with >=1px size.
    rx, ry, rw, rh = resolve_region((2000, 1500, 100, 100), 1280, 720)
    assert 0 <= rx < 1280
    assert 0 <= ry < 720
    assert rw >= 1 and rx + rw <= 1280
    assert rh >= 1 and ry + rh <= 720

    with pytest.raises(ValueError, match="positive"):
        resolve_region((0, 0, 100, 100), 0, 720)
    with pytest.raises(ValueError, match="positive"):
        resolve_region((0, 0, 100, 100), 1280, -10)


# ---------------------------------------------------------------------------
# Zoom easing math & filtergraph generation
# ---------------------------------------------------------------------------


def test_zoom_easing_math_boundaries() -> None:
    ev = ZoomEvent(start=2.0, end=6.0, x=0.25, y=0.25, w=0.5, h=0.5, scale=2.0, ease_ms=400)

    assert ease_zoom_progress(1.9, ev) == pytest.approx(0.0)
    assert ease_zoom_progress(2.0, ev) == pytest.approx(0.0)
    assert ease_zoom_progress(2.2, ev) == pytest.approx(0.5)
    assert ease_zoom_progress(2.4, ev) == pytest.approx(1.0)
    assert ease_zoom_progress(4.0, ev) == pytest.approx(1.0)
    assert ease_zoom_progress(5.6, ev) == pytest.approx(1.0)
    assert ease_zoom_progress(5.8, ev) == pytest.approx(0.5)
    assert ease_zoom_progress(6.0, ev) == pytest.approx(0.0)
    assert ease_zoom_progress(6.1, ev) == pytest.approx(0.0)


def test_zoom_easing_short_event_and_zero_ease() -> None:
    # Event duration 0.4s with ease_ms=500ms -> ease clamped to 0.2s (half duration).
    short_ev = ZoomEvent(start=1.0, end=1.4, x=100, y=100, w=200, h=200, scale=1.5, ease_ms=500)
    assert ease_zoom_progress(1.0, short_ev) == pytest.approx(0.0)
    assert ease_zoom_progress(1.1, short_ev) == pytest.approx(0.5)
    assert ease_zoom_progress(1.2, short_ev) == pytest.approx(1.0)
    assert ease_zoom_progress(1.3, short_ev) == pytest.approx(0.5)
    assert ease_zoom_progress(1.4, short_ev) == pytest.approx(0.0)

    # Instant zoom when ease_ms=0.
    instant_ev = ZoomEvent(start=1.0, end=2.0, x=100, y=100, w=200, h=200, scale=1.5, ease_ms=0)
    assert ease_zoom_progress(0.99, instant_ev) == pytest.approx(0.0)
    assert ease_zoom_progress(1.0, instant_ev) == pytest.approx(1.0)
    assert ease_zoom_progress(1.5, instant_ev) == pytest.approx(1.0)
    assert ease_zoom_progress(2.0, instant_ev) == pytest.approx(1.0)
    assert ease_zoom_progress(2.01, instant_ev) == pytest.approx(0.0)


def test_build_zoom_filter_empty_returns_passthrough() -> None:
    assert build_zoom_filter("0:v", "vzoom", 1280, 720, []) == ["[0:v]null[vzoom]"]
    assert build_zoom_filter("[vin]", "[vout]", 1280, 720, ()) == ["[vin]null[vout]"]


def test_build_zoom_filter_single_event_expressions_and_clamping() -> None:
    width, height = 1280, 720
    ev = ZoomEvent(start=2.0, end=6.0, x=40, y=30, w=80, h=60, scale=2.0, ease_ms=400)
    segments = build_zoom_filter("0:v", "vzoom", width, height, [ev])
    assert len(segments) == 1
    seg = segments[0]
    assert seg.startswith("[0:v]")
    assert seg.endswith("[vzoom]")
    assert "crop=" in seg
    assert f"scale={width}:{height}" in seg
    assert "between(t,2,6)" in seg

    exprs = _extract_crop_expressions(seg)

    # Evaluate emitted ffmpeg expressions across the full timeline.
    for t in (0.0, 2.0, 2.2, 2.4, 4.0, 5.6, 5.8, 6.0, 7.0):
        ow = _eval_ffmpeg_expr(exprs["w"], t=t, iw=width, ih=height)
        oh = _eval_ffmpeg_expr(exprs["h"], t=t, iw=width, ih=height)
        x = _eval_ffmpeg_expr(exprs["x"], t=t, iw=width, ih=height, ow=ow, oh=oh)
        y = _eval_ffmpeg_expr(exprs["y"], t=t, iw=width, ih=height, ow=ow, oh=oh)

        expected_p = ease_zoom_progress(t, ev)
        expected_z = 1.0 + (ev.scale - 1.0) * expected_p
        assert ow == pytest.approx(width / expected_z)
        assert oh == pytest.approx(height / expected_z)

        # Zero pan outside frame bounds at all times.
        assert 0.0 <= x <= width - ow + 1e-6
        assert 0.0 <= y <= height - oh + 1e-6

    # Near top-left corner (target centre 80, 60) should clamp x=0, y=0 during hold.
    ow_hold = _eval_ffmpeg_expr(exprs["w"], t=4.0, iw=width, ih=height)
    oh_hold = _eval_ffmpeg_expr(exprs["h"], t=4.0, iw=width, ih=height)
    assert _eval_ffmpeg_expr(exprs["x"], t=4.0, iw=width, ih=height, ow=ow_hold, oh=oh_hold) == pytest.approx(
        0.0
    )
    assert _eval_ffmpeg_expr(exprs["y"], t=4.0, iw=width, ih=height, ow=ow_hold, oh=oh_hold) == pytest.approx(
        0.0
    )


def test_build_zoom_filter_keeps_centred_target_centred() -> None:
    width, height = 1280, 720
    ev = ZoomEvent(start=1.0, end=5.0, x=0.4, y=0.4, w=0.2, h=0.2, scale=2.0, ease_ms=200)
    seg = build_zoom_filter("0:v", "vzoom", width, height, [ev])[0]
    exprs = _extract_crop_expressions(seg)

    ow = _eval_ffmpeg_expr(exprs["w"], t=3.0, iw=width, ih=height)
    oh = _eval_ffmpeg_expr(exprs["h"], t=3.0, iw=width, ih=height)
    x = _eval_ffmpeg_expr(exprs["x"], t=3.0, iw=width, ih=height, ow=ow, oh=oh)
    y = _eval_ffmpeg_expr(exprs["y"], t=3.0, iw=width, ih=height, ow=ow, oh=oh)

    assert ow == pytest.approx(640.0)
    assert oh == pytest.approx(360.0)
    assert x == pytest.approx(320.0)
    assert y == pytest.approx(180.0)


def test_build_zoom_filter_multiple_events_and_overlap_rejection() -> None:
    width, height = 1280, 720
    # Provided out of order, with back-to-back touching boundary at t=4.0.
    e2 = ZoomEvent(start=4.0, end=8.0, x=1100, y=600, w=150, h=100, scale=2.0, ease_ms=300)
    e1 = ZoomEvent(start=1.0, end=4.0, x=540, y=260, w=200, h=200, scale=1.5, ease_ms=300)
    segments = build_zoom_filter("0:v", "vzoom", width, height, [e2, e1])
    assert len(segments) == 1
    seg = segments[0]
    assert "between(t,1,4)" in seg
    assert "between(t,4,8)" in seg

    exprs = _extract_crop_expressions(seg)
    # During e1 hold (t=2.5): scale=1.5.
    assert _eval_ffmpeg_expr(exprs["w"], t=2.5, iw=width, ih=height) == pytest.approx(width / 1.5)
    # During e2 hold (t=6.0): scale=2.0 and clamped to right/bottom edge.
    ow2 = _eval_ffmpeg_expr(exprs["w"], t=6.0, iw=width, ih=height)
    oh2 = _eval_ffmpeg_expr(exprs["h"], t=6.0, iw=width, ih=height)
    x2 = _eval_ffmpeg_expr(exprs["x"], t=6.0, iw=width, ih=height, ow=ow2, oh=oh2)
    y2 = _eval_ffmpeg_expr(exprs["y"], t=6.0, iw=width, ih=height, ow=ow2, oh=oh2)
    assert ow2 == pytest.approx(640.0)
    assert x2 == pytest.approx(640.0)
    assert y2 == pytest.approx(360.0)

    # Overlapping zoom events must raise ValueError.
    overlap_a = ZoomEvent(start=1.0, end=4.0, x=100, y=100, w=200, h=200)
    overlap_b = ZoomEvent(start=3.5, end=6.0, x=300, y=200, w=200, h=200)
    with pytest.raises(ValueError, match="Overlapping"):
        build_zoom_filter("0:v", "vzoom", width, height, [overlap_a, overlap_b])

    with pytest.raises(ValueError, match="positive"):
        build_zoom_filter("0:v", "vzoom", 0, 720, [e1])


# ---------------------------------------------------------------------------
# Highlight spotlight & callout filtergraph generation
# ---------------------------------------------------------------------------


def test_build_highlight_filter_empty_returns_passthrough() -> None:
    assert build_highlight_filter("0:v", "vhl", 1280, 720, []) == ["[0:v]null[vhl]"]
    assert build_highlight_filter("[vin]", "[vout]", 1280, 720, ()) == ["[vin]null[vout]"]


def test_build_highlight_filter_spotlight_dim_surround() -> None:
    ev = HighlightEvent(start=1.5, end=4.5, x=200, y=100, w=400, h=200, style="spotlight", dim_opacity=0.5)
    segments = build_highlight_filter("0:v", "vhl", 1280, 720, [ev])
    assert len(segments) == 1
    seg = segments[0]
    assert seg.startswith("[0:v]")
    assert seg.endswith("[vhl]")

    # 4 non-overlapping dim surround boxes covering the complement of (200, 100, 400, 200).
    assert seg.count("drawbox=") == 4
    assert "x=0:y=0:w=1280:h=100:color=black@0.5:t=fill:enable='between(t,1.5,4.5)'" in seg
    assert "x=0:y=300:w=1280:h=420:color=black@0.5:t=fill:enable='between(t,1.5,4.5)'" in seg
    assert "x=0:y=100:w=200:h=200:color=black@0.5:t=fill:enable='between(t,1.5,4.5)'" in seg
    assert "x=600:y=100:w=680:h=200:color=black@0.5:t=fill:enable='between(t,1.5,4.5)'" in seg


def test_build_highlight_filter_callout_and_both_styles() -> None:
    callout = HighlightEvent(
        start=2.0,
        end=5.0,
        x=0.25,
        y=0.25,
        w=0.5,
        h=0.5,
        style="callout",
        color="#f43f5e",
        border_width=4,
    )
    seg_callout = build_highlight_filter("0:v", "vhl", 1280, 720, [callout])[0]
    assert seg_callout.count("drawbox=") == 1
    assert "black@" not in seg_callout
    assert "drawbox=x=320:y=180:w=640:h=360:color=#f43f5e:t=4:enable='between(t,2,5)'" in seg_callout

    both = HighlightEvent(
        start=3.0,
        end=6.0,
        x=0,
        y=0,
        w=400,
        h=300,
        style="both",
        dim_opacity=0.4,
        color="#38bdf8",
        border_width=3,
    )
    seg_both = build_highlight_filter("0:v", "vhl", 1280, 720, [both])[0]
    # Top and left strips have 0 size and are omitted; bottom + right + border = 3 drawboxes.
    assert seg_both.count("drawbox=") == 3
    assert "color=black@0.4:t=fill:enable='between(t,3,6)'" in seg_both
    assert "drawbox=x=0:y=0:w=400:h=300:color=#38bdf8:t=3:enable='between(t,3,6)'" in seg_both


def test_build_highlight_filter_multiple_events_and_full_frame_noop() -> None:
    e1 = HighlightEvent(start=1.0, end=3.0, x=100, y=100, w=200, h=100, style="callout")
    e2 = HighlightEvent(start=2.5, end=5.5, x=500, y=300, w=300, h=200, style="spotlight")
    seg = build_highlight_filter("0:v", "vhl", 1280, 720, [e1, e2])[0]
    assert "enable='between(t,1,3)'" in seg
    assert "enable='between(t,2.5,5.5)'" in seg
    assert seg.count("drawbox=") == 5

    # Full-frame spotlight has no dim surround -> falls back cleanly to null passthrough.
    full = HighlightEvent(start=0.0, end=2.0, x=0.0, y=0.0, w=1.0, h=1.0, style="spotlight")
    assert build_highlight_filter("0:v", "vhl", 1280, 720, [full]) == ["[0:v]null[vhl]"]

    with pytest.raises(ValueError, match="positive"):
        build_highlight_filter("0:v", "vhl", 1280, 0, [e1])
