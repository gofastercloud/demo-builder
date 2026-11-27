"""Build deterministic ffmpeg filtergraphs for ray.so-style presentation frames."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

RgbColour = tuple[int, int, int]
GradientStops = tuple[RgbColour, RgbColour]

DEFAULT_PRESET = "catppuccin"
DEFAULT_PADDING = 48
DEFAULT_RADIUS = 16
WINDOW_BAR_HEIGHT = 36
SHADOW_OPACITY = 0.45
SHADOW_SIGMA = 16
SHADOW_OFFSET_Y = 12

FRAME_PRESETS: dict[str, GradientStops | None] = {
    "catppuccin": ((203, 166, 247), (137, 180, 250)),
    "midnight": ((15, 23, 42), (30, 58, 138)),
    "sunset": ((249, 115, 22), (236, 72, 153)),
    "aurora": ((16, 185, 129), (99, 102, 241)),
    "none": None,
}

_WINDOW_BAR_COLOUR = "#1e1e2eff"
_TRAFFIC_LIGHT_DOTS: tuple[tuple[int, str], ...] = (
    (16, "#ff5f56"),
    (36, "#ffbd2e"),
    (56, "#27c93f"),
)


def _even(value: int) -> int:
    """Round an integer up to the nearest even number for yuv420p compatibility."""
    return value if value % 2 == 0 else value + 1


def _strip_brackets(label: str) -> str:
    """Normalise an ffmpeg stream label by stripping optional square brackets."""
    cleaned = label.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        raise ValueError("Filter label must not be empty")
    return cleaned


def _format_fps(fps: int | float) -> str:
    """Format a frame rate cleanly for ffmpeg filter options."""
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    if float(fps).is_integer():
        return str(int(fps))
    return f"{fps:g}"


def _rounded_mask_geq(radius: int) -> str:
    """Return an ffmpeg geq filter expression that rounds all four corners."""
    r = radius
    r_sq = r * r
    dx = f"max(0\\,max({r}-X\\,X-(W-{r})))"
    dy = f"max(0\\,max({r}-Y\\,Y-(H-{r})))"
    alpha_expr = f"if(lte(pow({dx}\\,2)+pow({dy}\\,2)\\,{r_sq})\\,alpha(X\\,Y)\\,0)"
    return f"geq=r='r(X\\,Y)':g='g(X\\,Y)':b='b(X\\,Y)':a='{alpha_expr}'"


@dataclass(frozen=True)
class FrameConfig:
    """Configuration for ray.so-style presentation framing."""

    preset: str = DEFAULT_PRESET
    padding: int = DEFAULT_PADDING
    radius: int = DEFAULT_RADIUS
    shadow: bool = True
    window_bar: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.preset not in FRAME_PRESETS:
            valid = ", ".join(sorted(FRAME_PRESETS))
            raise ValueError(f"Unknown frame preset: {self.preset!r}. Expected one of: {valid}")
        if self.padding < 0:
            raise ValueError(f"Frame padding must be non-negative, got {self.padding}")
        if self.radius < 0:
            raise ValueError(f"Frame corner radius must be non-negative, got {self.radius}")
        if self.preset == "none" and self.enabled:
            object.__setattr__(self, "enabled", False)


def resolve_frame_config(spec_frame: Any, no_frame: bool = False) -> FrameConfig:
    """Resolve storyboard ``frame`` configuration and CLI ``--no-frame`` override."""
    if no_frame:
        return FrameConfig(preset="none", enabled=False)

    if spec_frame is None or spec_frame is True:
        return FrameConfig()

    if spec_frame is False:
        return FrameConfig(preset="none", enabled=False)

    if isinstance(spec_frame, FrameConfig):
        return spec_frame

    if isinstance(spec_frame, str):
        return FrameConfig(preset=spec_frame, enabled=(spec_frame != "none"))

    if isinstance(spec_frame, Mapping):
        preset = spec_frame.get("preset", DEFAULT_PRESET)
        if not isinstance(preset, str):
            raise ValueError(f"Frame preset must be a string, got {preset!r}")
        padding = int(spec_frame.get("padding", DEFAULT_PADDING))
        radius = int(spec_frame.get("radius", DEFAULT_RADIUS))
        shadow = bool(spec_frame.get("shadow", True))
        window_bar = bool(spec_frame.get("window_bar", False))
        enabled = bool(spec_frame.get("enabled", True)) and preset != "none"
        return FrameConfig(
            preset=preset,
            padding=padding,
            radius=radius,
            shadow=shadow,
            window_bar=window_bar,
            enabled=enabled,
        )

    raise ValueError(f"Unsupported frame specification: {spec_frame!r}")


def compute_canvas_size(width: int, height: int, config: FrameConfig) -> tuple[int, int]:
    """Compute output canvas dimensions, guaranteeing even sizes when framing is enabled."""
    if width <= 0 or height <= 0:
        raise ValueError(f"Video dimensions must be positive, got {width}x{height}")
    if not config.enabled:
        return (width, height)

    bar_height = WINDOW_BAR_HEIGHT if config.window_bar else 0
    canvas_w = _even(width + 2 * config.padding)
    canvas_h = _even(height + bar_height + 2 * config.padding)
    return (canvas_w, canvas_h)


def build_frame_filter(
    input_label: str,
    output_label: str,
    width: int,
    height: int,
    fps: int | float,
    config: FrameConfig,
) -> list[str]:
    """Build deterministic ffmpeg filtergraph segments for presentation framing.

    When ``config.enabled`` is ``False``, returns a lightweight ``null`` passthrough
    that preserves the input stream's dimensions unchanged.
    """
    in_lbl = _strip_brackets(input_label)
    out_lbl = _strip_brackets(output_label)
    if width <= 0 or height <= 0:
        raise ValueError(f"Video dimensions must be positive, got {width}x{height}")
    fps_str = _format_fps(fps)

    if not config.enabled:
        return [f"[{in_lbl}]null[{out_lbl}]"]

    gradient = FRAME_PRESETS.get(config.preset)
    if gradient is None:
        return [f"[{in_lbl}]null[{out_lbl}]"]

    (r1, g1, b1), (r2, g2, b2) = gradient
    canvas_w, canvas_h = compute_canvas_size(width, height, config)
    bar_height = WINDOW_BAR_HEIGHT if config.window_bar else 0
    card_w = width
    card_h = height + bar_height
    radius = min(config.radius, card_w // 2, card_h // 2)
    overlay_x = (canvas_w - card_w) // 2
    overlay_y = (canvas_h - card_h) // 2

    prefix = "_frm"
    bg_label = f"{prefix}_bg"
    fg_label = f"{prefix}_fg"

    segments: list[str] = []

    # 1. Diagonal gradient backdrop canvas with guaranteed even dimensions.
    grad_geq = (
        f"geq="
        f"r='{r1}+({r2}-{r1})*(X/W+Y/H)/2':"
        f"g='{g1}+({g2}-{g1})*(X/W+Y/H)/2':"
        f"b='{b1}+({b2}-{b1})*(X/W+Y/H)/2':"
        f"a='255'"
    )
    segments.append(f"color=c=black:s={canvas_w}x{canvas_h}:r={fps_str},format=rgba,{grad_geq}[{bg_label}]")

    # 2. Foreground card: optional macOS window-bar chrome and rounded-corner alpha mask.
    fg_chain: list[str] = [f"[{in_lbl}]format=rgba"]
    if config.window_bar:
        fg_chain.append(f"pad=w={card_w}:h={card_h}:x=0:y={bar_height}:color={_WINDOW_BAR_COLOUR}")
        dot_y = (bar_height - 12) // 2
        for dot_x, dot_colour in _TRAFFIC_LIGHT_DOTS:
            fg_chain.append(f"drawbox=x={dot_x}:y={dot_y}:w=12:h=12:color={dot_colour}:t=fill")
    if radius > 0:
        fg_chain.append(_rounded_mask_geq(radius))
    segments.append(",".join(fg_chain) + f"[{fg_label}]")

    # 3. Optional soft blurred drop shadow behind the foreground card.
    composite_bg = bg_label
    if config.shadow:
        shadow_label = f"{prefix}_shadow"
        bg_shadow_label = f"{prefix}_bg_shadow"
        shadow_y = min(overlay_y + SHADOW_OFFSET_Y, canvas_h - card_h)
        shadow_chain: list[str] = [
            f"color=c=black@{SHADOW_OPACITY}:s={card_w}x{card_h}:r={fps_str}",
            "format=rgba",
        ]
        if radius > 0:
            shadow_chain.append(_rounded_mask_geq(radius))
        shadow_chain.append(f"pad=w={canvas_w}:h={canvas_h}:x={overlay_x}:y={shadow_y}:color=0x00000000")
        shadow_chain.append(f"gblur=sigma={SHADOW_SIGMA}")
        segments.append(",".join(shadow_chain) + f"[{shadow_label}]")
        segments.append(f"[{bg_label}][{shadow_label}]overlay=x=0:y=0:shortest=1[{bg_shadow_label}]")
        composite_bg = bg_shadow_label

    # 4. Centered foreground overlay onto the backdrop (and shadow).
    segments.append(f"[{composite_bg}][{fg_label}]overlay=x={overlay_x}:y={overlay_y}:shortest=1[{out_lbl}]")

    return segments
