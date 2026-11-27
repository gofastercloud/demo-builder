"""Build deterministic ffmpeg filtergraphs for ray.so-style presentation frames."""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Iterable, Mapping, Sequence
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


HIGHLIGHT_STYLES: frozenset[str] = frozenset({"spotlight", "callout", "both"})

_SAFE_COLOUR_RE = re.compile(
    r"^(?:#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3}(?:[0-9a-fA-F]{2})?)?"
    r"|0x[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?"
    r"|[A-Za-z][A-Za-z0-9]*)"
    r"(?:@(?:(?:0(?:\.\d+)?|1(?:\.0+)?)|0x[0-9a-fA-F]{2}))?$"
)


def _fmt_num(value: float) -> str:
    """Format a floating-point number concisely for ffmpeg filter expressions."""
    formatted = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if formatted in ("", "-0") else formatted


def _require_finite(name: str, value: float) -> None:
    """Reject NaN and infinite numeric values."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


@dataclass(frozen=True)
class ZoomEvent:
    """Declarative camera zoom onto a target region with smooth ease-in/out."""

    start: float
    end: float
    x: float
    y: float
    w: float
    h: float
    scale: float = 1.6
    ease_ms: int = 350

    def __post_init__(self) -> None:
        for field_name, val in (
            ("start", self.start),
            ("end", self.end),
            ("x", self.x),
            ("y", self.y),
            ("w", self.w),
            ("h", self.h),
            ("scale", self.scale),
            ("ease_ms", self.ease_ms),
        ):
            _require_finite(f"ZoomEvent {field_name}", val)
        if self.start < 0:
            raise ValueError(f"ZoomEvent start must be non-negative, got {self.start}")
        if self.end <= self.start:
            raise ValueError(f"ZoomEvent end ({self.end}) must be greater than start ({self.start})")
        if self.w <= 0 or self.h <= 0:
            raise ValueError(f"ZoomEvent region dimensions must be positive, got {self.w}x{self.h}")
        if self.scale < 1.0:
            raise ValueError(f"ZoomEvent scale must be >= 1.0, got {self.scale}")
        if self.ease_ms < 0:
            raise ValueError(f"ZoomEvent ease_ms must be non-negative, got {self.ease_ms}")


@dataclass(frozen=True)
class HighlightEvent:
    """Declarative spotlight dim-surround and/or callout border highlight."""

    start: float
    end: float
    x: float
    y: float
    w: float
    h: float
    style: str = "spotlight"
    dim_opacity: float = 0.45
    color: str = "#38bdf8"
    border_width: int = 3

    def __post_init__(self) -> None:
        for field_name, val in (
            ("start", self.start),
            ("end", self.end),
            ("x", self.x),
            ("y", self.y),
            ("w", self.w),
            ("h", self.h),
            ("dim_opacity", self.dim_opacity),
            ("border_width", self.border_width),
        ):
            _require_finite(f"HighlightEvent {field_name}", val)
        if self.start < 0:
            raise ValueError(f"HighlightEvent start must be non-negative, got {self.start}")
        if self.end <= self.start:
            raise ValueError(f"HighlightEvent end ({self.end}) must be greater than start ({self.start})")
        if self.w <= 0 or self.h <= 0:
            raise ValueError(f"HighlightEvent region dimensions must be positive, got {self.w}x{self.h}")
        if self.style not in HIGHLIGHT_STYLES:
            valid = ", ".join(sorted(HIGHLIGHT_STYLES))
            raise ValueError(f"Unknown highlight style: {self.style!r}. Expected one of: {valid}")
        if not (0.0 <= self.dim_opacity <= 1.0):
            raise ValueError(f"HighlightEvent dim_opacity must be in [0.0, 1.0], got {self.dim_opacity}")
        if self.border_width < 0:
            raise ValueError(f"HighlightEvent border_width must be non-negative, got {self.border_width}")
        if not isinstance(self.color, str) or not _SAFE_COLOUR_RE.match(self.color):
            raise ValueError(
                f"HighlightEvent color must be a valid hex or named colour (with optional @opacity), "
                f"got {self.color!r}"
            )


def _extract_region_coords(region: Any) -> tuple[float, float, float, float]:
    """Extract (x, y, w, h) floats from an event dataclass, mapping, or 4-sequence."""
    if isinstance(region, (ZoomEvent, HighlightEvent)):
        return (float(region.x), float(region.y), float(region.w), float(region.h))
    if isinstance(region, Mapping):
        try:
            return (
                float(region["x"]),
                float(region["y"]),
                float(region["w"]),
                float(region["h"]),
            )
        except KeyError as exc:
            raise ValueError(f"Region mapping missing required key: {exc}") from exc
    if isinstance(region, Sequence) and not isinstance(region, (str, bytes)) and len(region) == 4:
        return (float(region[0]), float(region[1]), float(region[2]), float(region[3]))
    if all(hasattr(region, attr) for attr in ("x", "y", "w", "h")):
        return (float(region.x), float(region.y), float(region.w), float(region.h))
    raise ValueError(f"Unsupported region specification: {region!r}")


def resolve_region(region: Any, width: int, height: int) -> tuple[int, int, int, int]:
    """Resolve pixel or normalised ``[0.0, 1.0]`` coordinates and clamp to frame bounds.

    When all four values lie within ``[0.0, 1.0]`` (with positive width/height), the
    region is interpreted as normalised frame coordinates and scaled to pixels.
    Resulting coordinates are always clamped strictly inside ``[0, width] x [0, height]``
    with at least 1px width and height.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"Video dimensions must be positive, got {width}x{height}")

    x, y, w, h = _extract_region_coords(region)
    for field_name, val in (("x", x), ("y", y), ("w", w), ("h", h)):
        _require_finite(f"Region {field_name}", val)
    if w <= 0 or h <= 0:
        raise ValueError(f"Region dimensions must be positive, got {w}x{h}")

    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0:
        px, py, pw, ph = x * width, y * height, w * width, h * height
    else:
        px, py, pw, ph = x, y, w, h

    x1 = max(0, min(round(px), width))
    y1 = max(0, min(round(py), height))
    x2 = max(0, min(round(px + pw), width))
    y2 = max(0, min(round(py + ph), height))

    if x2 <= x1:
        x1 = min(x1, width - 1)
        x2 = x1 + 1
    if y2 <= y1:
        y1 = min(y1, height - 1)
        y2 = y1 + 1

    return (x1, y1, x2 - x1, y2 - y1)


def ease_zoom_progress(t: float, event: ZoomEvent) -> float:
    """Evaluate sine ease-in/out zoom progress in ``[0.0, 1.0]`` at timestamp ``t``."""
    if t < event.start or t > event.end:
        return 0.0
    ease = min(event.ease_ms / 1000.0, (event.end - event.start) / 2.0)
    if ease <= 0.0:
        return 1.0
    if t < event.start + ease:
        return 0.5 * (1.0 - math.cos(math.pi * (t - event.start) / ease))
    if t > event.end - ease:
        return 0.5 * (1.0 - math.cos(math.pi * (event.end - t) / ease))
    return 1.0


def _zoom_progress_inner_expr(event: ZoomEvent) -> str:
    """Build an ffmpeg sine ease-in/out expression for ``t`` within ``[start, end]``."""
    ease = min(event.ease_ms / 1000.0, (event.end - event.start) / 2.0)
    if ease <= 0.0:
        return "1"

    s = _fmt_num(event.start)
    e = _fmt_num(event.end)
    ease_s = _fmt_num(ease)
    t_in_end = _fmt_num(event.start + ease)
    t_out_start = _fmt_num(event.end - ease)
    return (
        f"if(lt(t,{t_in_end}),0.5*(1-cos(PI*(t-{s})/{ease_s})),"
        f"if(gt(t,{t_out_start}),0.5*(1-cos(PI*({e}-t)/{ease_s})),1))"
    )


def build_zoom_filter(
    input_label: str,
    output_label: str,
    width: int,
    height: int,
    events: Iterable[ZoomEvent],
) -> list[str]:
    """Build deterministic ffmpeg per-frame ``scale`` + ``crop`` expressions for smooth zooms.

    Per-frame ``scale(..., eval=frame)`` upscales the frame by the eased zoom factor
    before a fixed-size ``crop=w={width}:h={height}`` centres on the target region and
    clamps strictly within frame bounds.

    Empty event sequences return a lightweight ``null`` passthrough. Overlapping zoom
    events (where a later event starts strictly before the previous event ends) raise
    ``ValueError``. Touching events (``curr.start == prev.end``) are mutually exclusive
    via nested ``if(between(t, start, end), ...)`` with earlier-event precedence at the
    shared boundary timestamp.
    """
    in_lbl = _strip_brackets(input_label)
    out_lbl = _strip_brackets(output_label)
    if width <= 0 or height <= 0:
        raise ValueError(f"Video dimensions must be positive, got {width}x{height}")

    ordered = sorted(events, key=lambda ev: (ev.start, ev.end))
    if not ordered:
        return [f"[{in_lbl}]null[{out_lbl}]"]

    for prev, curr in itertools.pairwise(ordered):
        if curr.start < prev.end:
            raise ValueError(
                f"Overlapping zoom events: [{prev.start}, {prev.end}] and [{curr.start}, {curr.end}]"
            )

    # Build mutually exclusive nested if(between(t, start, end), ...) expressions
    # so touching events never double-count at shared boundary timestamps.
    z_expr = "1"
    cx_expr = "0"
    cy_expr = "0"

    for ev in reversed(ordered):
        rx, ry, rw, rh = resolve_region(ev, width, height)
        target_cx = _fmt_num(rx + rw / 2.0)
        target_cy = _fmt_num(ry + rh / 2.0)
        s = _fmt_num(ev.start)
        e = _fmt_num(ev.end)
        delta = _fmt_num(ev.scale - 1.0)
        p_inner = _zoom_progress_inner_expr(ev)
        ev_zoom = f"1+{delta}*{p_inner}"
        z_expr = f"if(between(t,{s},{e}),{ev_zoom},{z_expr})"
        cx_expr = f"if(between(t,{s},{e}),{target_cx},{cx_expr})"
        cy_expr = f"if(between(t,{s},{e}),{target_cy},{cy_expr})"

    scale_w = f"max({width},trunc({width}*({z_expr})/2)*2)"
    scale_h = f"max({height},trunc({height}*({z_expr})/2)*2)"
    crop_x = f"clip(({cx_expr})*({z_expr})-{width}/2,0,iw-{width})"
    crop_y = f"clip(({cy_expr})*({z_expr})-{height}/2,0,ih-{height})"

    return [
        f"[{in_lbl}]scale=w='{scale_w}':h='{scale_h}':eval=frame:flags=lanczos,"
        f"crop=w={width}:h={height}:x='{crop_x}':y='{crop_y}'[{out_lbl}]"
    ]


def build_highlight_filter(
    input_label: str,
    output_label: str,
    width: int,
    height: int,
    events: Iterable[HighlightEvent],
) -> list[str]:
    """Build deterministic ffmpeg ``drawbox`` spotlight and/or callout border overlays.

    Each overlay is strictly gated by ``enable='between(t,start,end)'``. Empty event
    sequences (or events that produce no visible boxes) return a ``null`` passthrough.
    """
    in_lbl = _strip_brackets(input_label)
    out_lbl = _strip_brackets(output_label)
    if width <= 0 or height <= 0:
        raise ValueError(f"Video dimensions must be positive, got {width}x{height}")

    event_list = list(events)
    if not event_list:
        return [f"[{in_lbl}]null[{out_lbl}]"]

    filters: list[str] = []
    for ev in event_list:
        rx, ry, rw, rh = resolve_region(ev, width, height)
        enable = f"between(t,{_fmt_num(ev.start)},{_fmt_num(ev.end)})"

        if ev.style in ("spotlight", "both") and ev.dim_opacity > 0.0:
            dim = f"black@{_fmt_num(ev.dim_opacity)}"
            # Partition the frame exterior into up to four non-overlapping strips.
            if ry > 0:
                filters.append(f"drawbox=x=0:y=0:w={width}:h={ry}:color={dim}:t=fill:enable='{enable}'")
            if ry + rh < height:
                filters.append(
                    f"drawbox=x=0:y={ry + rh}:w={width}:h={height - (ry + rh)}:"
                    f"color={dim}:t=fill:enable='{enable}'"
                )
            if rx > 0:
                filters.append(f"drawbox=x=0:y={ry}:w={rx}:h={rh}:color={dim}:t=fill:enable='{enable}'")
            if rx + rw < width:
                filters.append(
                    f"drawbox=x={rx + rw}:y={ry}:w={width - (rx + rw)}:h={rh}:"
                    f"color={dim}:t=fill:enable='{enable}'"
                )

        if ev.style in ("callout", "both") and ev.border_width > 0:
            filters.append(
                f"drawbox=x={rx}:y={ry}:w={rw}:h={rh}:color={ev.color}:t={ev.border_width}:enable='{enable}'"
            )

    if not filters:
        return [f"[{in_lbl}]null[{out_lbl}]"]

    return [f"[{in_lbl}]{','.join(filters)}[{out_lbl}]"]


TRANSITION_TYPES: frozenset[str] = frozenset(
    {
        "fade",
        "wipeleft",
        "wiperight",
        "slideleft",
        "slideright",
        "smoothleft",
        "smoothright",
        "dissolve",
        "zoomin",
    }
)

PIP_CORNERS: frozenset[str] = frozenset(
    {
        "bottom-right",
        "bottom-left",
        "top-right",
        "top-left",
    }
)


@dataclass(frozen=True)
class TransitionSpec:
    """Configuration for an ffmpeg ``xfade`` transition between two adjacent scenes."""

    type: str = "fade"
    duration: float = 0.5

    def __post_init__(self) -> None:
        if self.type not in TRANSITION_TYPES:
            valid = ", ".join(sorted(TRANSITION_TYPES))
            raise ValueError(f"Unknown transition type: {self.type!r}. Expected one of: {valid}")
        _require_finite("TransitionSpec duration", self.duration)
        if self.duration <= 0.0:
            raise ValueError(f"TransitionSpec duration must be positive, got {self.duration}")


def build_xfade_filter(
    scene_labels: Sequence[str],
    durations: Sequence[float],
    transitions: Sequence[TransitionSpec],
    output_label: str,
) -> tuple[list[str], list[float]]:
    """Chain ``xfade`` transitions across 2+ scenes and compute global scene start times.

    Returns ``(segments, scene_starts)`` where ``scene_starts[i]`` is the exact global
    timestamp at which scene ``i`` begins on the merged timeline after accounting for
    all cumulative ``transition.duration`` overlaps.
    """
    labels = [_strip_brackets(lbl) for lbl in scene_labels]
    out_lbl = _strip_brackets(output_label)

    if len(labels) < 2:
        raise ValueError(f"build_xfade_filter requires at least 2 scenes, got {len(labels)}")
    if len(durations) != len(labels):
        raise ValueError(
            f"Number of durations ({len(durations)}) must match number of scenes ({len(labels)})"
        )
    if len(transitions) != len(labels) - 1:
        raise ValueError(
            f"Number of transitions ({len(transitions)}) must be one fewer than scenes ({len(labels) - 1})"
        )

    scene_durations: list[float] = []
    for idx, dur in enumerate(durations):
        _require_finite(f"Scene {idx} duration", dur)
        if dur <= 0.0:
            raise ValueError(f"Scene {idx} duration must be positive, got {dur}")
        scene_durations.append(float(dur))

    segments: list[str] = []
    starts: list[float] = [0.0]
    cumulative = scene_durations[0]
    current_label = labels[0]

    for idx, trans in enumerate(transitions):
        next_label = labels[idx + 1]
        next_dur = scene_durations[idx + 1]
        if trans.duration > cumulative:
            raise ValueError(
                f"Transition {idx} duration ({trans.duration}s) exceeds "
                f"accumulated timeline duration ({cumulative}s)"
            )
        if trans.duration > next_dur:
            raise ValueError(
                f"Transition {idx} duration ({trans.duration}s) exceeds "
                f"scene {idx + 1} duration ({next_dur}s)"
            )

        offset = cumulative - trans.duration
        starts.append(offset)
        cumulative = offset + next_dur

        step_out = out_lbl if idx == len(transitions) - 1 else f"_xfade_{idx}"
        segments.append(
            f"[{current_label}][{next_label}]"
            f"xfade=transition={trans.type}:duration={_fmt_num(trans.duration)}:offset={_fmt_num(offset)}"
            f"[{step_out}]"
        )
        current_label = step_out

    return segments, starts


@dataclass(frozen=True)
class PipConfig:
    """Configuration for a Picture-in-Picture (PiP) overlay stream."""

    corner: str = "bottom-right"
    scale: float = 0.32
    margin: int = 28
    start: float = 0.0
    end: float | None = None
    radius: int = 12
    border_color: str = "#cdd6f4"
    border_width: int = 2

    def __post_init__(self) -> None:
        if self.corner not in PIP_CORNERS:
            valid = ", ".join(sorted(PIP_CORNERS))
            raise ValueError(f"Unknown PiP corner: {self.corner!r}. Expected one of: {valid}")
        _require_finite("PipConfig scale", self.scale)
        if not (0.0 < self.scale <= 1.0):
            raise ValueError(f"PipConfig scale must be in (0.0, 1.0], got {self.scale}")
        _require_finite("PipConfig margin", self.margin)
        if self.margin < 0:
            raise ValueError(f"PipConfig margin must be non-negative, got {self.margin}")
        _require_finite("PipConfig start", self.start)
        if self.start < 0.0:
            raise ValueError(f"PipConfig start must be non-negative, got {self.start}")
        if self.end is not None:
            _require_finite("PipConfig end", self.end)
            if self.end <= self.start:
                raise ValueError(f"PipConfig end ({self.end}) must be greater than start ({self.start})")
        _require_finite("PipConfig radius", self.radius)
        if self.radius < 0:
            raise ValueError(f"PipConfig radius must be non-negative, got {self.radius}")
        _require_finite("PipConfig border_width", self.border_width)
        if self.border_width < 0:
            raise ValueError(f"PipConfig border_width must be non-negative, got {self.border_width}")
        if not isinstance(self.border_color, str) or not _SAFE_COLOUR_RE.match(self.border_color):
            raise ValueError(
                f"PipConfig border_color must be a valid hex or named colour (with optional @opacity), "
                f"got {self.border_color!r}"
            )


def build_pip_filter(
    base_label: str,
    pip_label: str,
    output_label: str,
    base_w: int,
    base_h: int,
    config: PipConfig,
) -> list[str]:
    """Build deterministic ffmpeg filtergraph segments for a rounded Picture-in-Picture overlay.

    Scales ``pip_label`` to ``base_w * config.scale`` (rounded to an even width, with
    ``h=-2`` preserving aspect ratio and even height), applies optional border and rounded
    corners, shifts timestamps by ``config.start``, and overlays onto ``base_label`` at
    the configured corner gated by ``enable``.
    """
    base_lbl = _strip_brackets(base_label)
    pip_lbl = _strip_brackets(pip_label)
    out_lbl = _strip_brackets(output_label)
    if base_w <= 0 or base_h <= 0:
        raise ValueError(f"Base video dimensions must be positive, got {base_w}x{base_h}")

    pip_w = _even(max(2, round(base_w * config.scale)))
    radius = min(config.radius, pip_w // 2)
    start_str = _fmt_num(config.start)
    prepared_lbl = "_pip_card"

    pip_chain: list[str] = [
        f"[{pip_lbl}]scale=w={pip_w}:h=-2:flags=lanczos",
        "format=rgba",
    ]
    if config.border_width > 0:
        pip_chain.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={config.border_color}:t={config.border_width}")
    if radius > 0:
        pip_chain.append(_rounded_mask_geq(radius))
    pip_chain.append(f"setpts=PTS-STARTPTS+{start_str}/TB")

    m = config.margin
    corner_coords = {
        "top-left": (f"{m}", f"{m}"),
        "top-right": (f"W-w-{m}", f"{m}"),
        "bottom-left": (f"{m}", f"H-h-{m}"),
        "bottom-right": (f"W-w-{m}", f"H-h-{m}"),
    }
    x_expr, y_expr = corner_coords[config.corner]

    if config.end is not None:
        enable = f"between(t,{start_str},{_fmt_num(config.end)})"
    else:
        enable = f"gte(t,{start_str})"

    return [
        ",".join(pip_chain) + f"[{prepared_lbl}]",
        f"[{base_lbl}][{prepared_lbl}]overlay=x={x_expr}:y={y_expr}:eof_action=pass:enable='{enable}'[{out_lbl}]",
    ]
