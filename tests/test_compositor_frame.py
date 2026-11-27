"""Offline unit tests for the ray.so-style ffmpeg frame compositor."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compositor import (
    FRAME_PRESETS,
    FrameConfig,
    build_frame_filter,
    compute_canvas_size,
    resolve_frame_config,
)


def test_default_frame_config() -> None:
    cfg = resolve_frame_config(None)
    assert cfg == FrameConfig(
        preset="catppuccin",
        padding=48,
        radius=16,
        shadow=True,
        window_bar=False,
        enabled=True,
    )


@pytest.mark.parametrize("preset", ["catppuccin", "midnight", "sunset", "aurora"])
def test_resolve_active_presets_from_string_and_dict(preset: str) -> None:
    from_str = resolve_frame_config(preset)
    assert from_str.preset == preset
    assert from_str.enabled is True
    assert from_str.padding == 48
    assert from_str.radius == 16
    assert from_str.shadow is True
    assert from_str.window_bar is False

    from_dict = resolve_frame_config(
        {
            "preset": preset,
            "padding": 64,
            "radius": 20,
            "shadow": False,
            "window_bar": True,
        }
    )
    assert from_dict.preset == preset
    assert from_dict.enabled is True
    assert from_dict.padding == 64
    assert from_dict.radius == 20
    assert from_dict.shadow is False
    assert from_dict.window_bar is True


def test_resolve_none_preset_and_opt_out_flags() -> None:
    assert resolve_frame_config("none").enabled is False
    assert resolve_frame_config("none").preset == "none"

    assert resolve_frame_config({"preset": "none"}).enabled is False
    assert resolve_frame_config({"enabled": False}).enabled is False

    assert resolve_frame_config(False).enabled is False
    assert resolve_frame_config(False).preset == "none"

    assert resolve_frame_config(None, no_frame=True).enabled is False
    assert resolve_frame_config("aurora", no_frame=True).enabled is False
    assert resolve_frame_config({"preset": "sunset", "padding": 32}, no_frame=True).enabled is False


def test_resolve_true_uses_defaults() -> None:
    cfg = resolve_frame_config(True)
    assert cfg.enabled is True
    assert cfg.preset == "catppuccin"
    assert cfg.padding == 48
    assert cfg.radius == 16
    assert cfg.shadow is True
    assert cfg.window_bar is False


def test_unknown_preset_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown frame preset"):
        resolve_frame_config("neon-tokyo")

    with pytest.raises(ValueError, match="Unknown frame preset"):
        resolve_frame_config({"preset": "vaporwave"})

    with pytest.raises(ValueError, match="Unknown frame preset"):
        FrameConfig(preset="not-a-preset")


def test_frame_presets_registry_contains_expected_names() -> None:
    assert {"catppuccin", "midnight", "sunset", "aurora", "none"} <= set(FRAME_PRESETS)


@pytest.mark.parametrize(
    ("width", "height", "padding", "window_bar"),
    [
        (1280, 720, 48, False),
        (1279, 719, 48, False),
        (1280, 720, 33, False),
        (1279, 719, 33, True),
        (801, 601, 0, True),
    ],
)
def test_even_dimension_guarantees(
    width: int,
    height: int,
    padding: int,
    window_bar: bool,
) -> None:
    cfg = FrameConfig(preset="catppuccin", padding=padding, window_bar=window_bar)
    canvas_w, canvas_h = compute_canvas_size(width, height, cfg)
    assert canvas_w % 2 == 0
    assert canvas_h % 2 == 0
    assert canvas_w >= width + 2 * padding
    assert canvas_h >= height + 2 * padding

    segments = build_frame_filter("0:v", "vframed", width, height, 30, cfg)
    joined = ";".join(segments)
    assert f"s={canvas_w}x{canvas_h}" in joined


def test_disabled_config_emits_passthrough_with_unchanged_dimensions() -> None:
    for cfg in (
        resolve_frame_config("none"),
        resolve_frame_config(False),
        resolve_frame_config("catppuccin", no_frame=True),
    ):
        assert compute_canvas_size(1279, 719, cfg) == (1279, 719)
        segments = build_frame_filter("0:v", "vout", 1279, 719, 30, cfg)
        assert segments == ["[0:v]null[vout]"]


@pytest.mark.parametrize("preset", ["catppuccin", "midnight", "sunset", "aurora"])
def test_build_frame_filter_syntax_and_labels_per_preset(preset: str) -> None:
    cfg = resolve_frame_config(preset)
    segments = build_frame_filter("0:v", "vframed", 1280, 720, 30, cfg)
    assert len(segments) >= 4

    joined = ";".join(segments)
    # Input and output labels wired properly.
    assert "[0:v]" in joined
    assert segments[-1].endswith("[vframed]")

    # Contains gradient canvas, rounded corner alpha mask, blurred drop shadow, and overlay.
    assert "color=" in joined
    assert "geq=" in joined
    assert "gblur=" in joined
    assert "overlay=" in joined
    assert "r=30" in joined

    # Every internal label produced is consumed, and no empty filter segments exist.
    assert all(seg.strip() for seg in segments)
    bracket_labels = re.findall(r"\[([^\]]+)\]", joined)
    assert "0:v" in bracket_labels
    assert "vframed" in bracket_labels


def test_presets_produce_distinct_gradient_expressions() -> None:
    canvas_segments = {}
    for preset in ("catppuccin", "midnight", "sunset", "aurora"):
        cfg = resolve_frame_config(preset)
        segments = build_frame_filter("0:v", "vframed", 1280, 720, 30, cfg)
        canvas_segments[preset] = segments[0]

    assert len(set(canvas_segments.values())) == 4


def test_shadow_disabled_omits_blur_segment() -> None:
    cfg = resolve_frame_config({"preset": "midnight", "shadow": False})
    segments = build_frame_filter("[0:v]", "[vframed]", 1280, 720, 30, cfg)
    joined = ";".join(segments)
    assert "gblur=" not in joined
    assert "[0:v]" in joined
    assert segments[-1].endswith("[vframed]")


def test_window_bar_chrome_adds_header_and_traffic_lights() -> None:
    without_bar = resolve_frame_config({"preset": "sunset", "window_bar": False})
    with_bar = resolve_frame_config({"preset": "sunset", "window_bar": True})

    _, h_no_bar = compute_canvas_size(1280, 720, without_bar)
    _, h_with_bar = compute_canvas_size(1280, 720, with_bar)
    assert h_with_bar > h_no_bar
    assert h_with_bar % 2 == 0

    segments = build_frame_filter("0:v", "vframed", 1280, 720, 30, with_bar)
    joined = ";".join(segments)
    assert "pad=" in joined
    assert "drawbox=" in joined


def test_invalid_dimensions_or_config_values_raise_value_error() -> None:
    cfg = resolve_frame_config("catppuccin")
    with pytest.raises(ValueError):
        build_frame_filter("0:v", "vframed", 0, 720, 30, cfg)
    with pytest.raises(ValueError):
        build_frame_filter("0:v", "vframed", 1280, -10, 30, cfg)
    with pytest.raises(ValueError):
        build_frame_filter("0:v", "vframed", 1280, 720, 0, cfg)
    with pytest.raises(ValueError):
        FrameConfig(padding=-1)
    with pytest.raises(ValueError):
        FrameConfig(radius=-4)
