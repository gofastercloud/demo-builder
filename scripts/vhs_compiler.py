"""Compile declarative terminal storyboard dicts into Charmbracelet VHS .tape scripts."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30
DEFAULT_THEME = "Catppuccin Mocha"
DEFAULT_FONT_SIZE = 16
DEFAULT_PADDING = 24
DEFAULT_WINDOW_BAR = "Colorful"
DEFAULT_TYPING_SPEED = "45ms"

_KEY_ALIASES: dict[str, str] = {
    "tab": "Tab",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "Backspace",
    "space": "Space",
    "delete": "Delete",
    "del": "Delete",
    "enter": "Enter",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
}


def _vhs_quote(text: str) -> str:
    """Wrap text in a VHS string delimiter that does not appear inside text."""
    for delim in ('"', "'", "`"):
        if delim not in text:
            return f"{delim}{text}{delim}"
    raise ValueError("Cannot quote VHS string containing double quotes, single quotes, and backticks")


def _split_quotable_chunks(text: str) -> list[str]:
    """Split text into minimal chunks where each chunk avoids at least one VHS quote delimiter."""
    if not text:
        return [""]
    for delim in ('"', "'", "`"):
        if delim not in text:
            return [text]

    chunks: list[str] = []
    current: list[str] = []
    for ch in text:
        candidate = "".join([*current, ch])
        if all(d in candidate for d in ('"', "'", "`")):
            chunks.append("".join(current))
            current = [ch]
        else:
            current.append(ch)
    if current:
        chunks.append("".join(current))
    return chunks


def _format_duration(value: int | float | str) -> str:
    """Normalise a duration value into a VHS duration token (e.g. '45ms', '5s')."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ms = int(value)
        if ms < 0:
            raise ValueError(f"Duration must be non-negative, got {value!r}")
        return f"{ms}ms"
    text = str(value).strip()
    if not text:
        raise ValueError("Duration cannot be empty")
    return text


def _parse_duration_ms(value: int | float | str) -> float:
    """Parse a numeric or VHS duration token into milliseconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ms = float(value)
        if ms < 0:
            raise ValueError(f"Duration must be non-negative, got {value!r}")
        return ms
    text = str(value).strip().lower()
    if not text:
        raise ValueError("Duration cannot be empty")
    if text.endswith("ms"):
        ms = float(text[:-2])
    elif text.endswith("s"):
        ms = float(text[:-1]) * 1000.0
    elif text.endswith("m"):
        ms = float(text[:-1]) * 60_000.0
    else:
        ms = float(text)
    if ms < 0:
        raise ValueError(f"Duration must be non-negative, got {value!r}")
    return ms


def _estimate_step_duration_ms(step: dict[str, Any], typing_speed_ms: float) -> float:
    """Estimate the visible duration in milliseconds of a single VHS storyboard step."""
    action = step.get("action")
    step_ms = 0.0

    if action == "type":
        text = str(step["text"])
        char_ms = _parse_duration_ms(step["speed"]) if step.get("speed") is not None else typing_speed_ms
        step_ms = len(text) * char_ms
        if step.get("enter"):
            step_ms += typing_speed_ms
    elif action == "enter":
        step_ms = int(step.get("count", 1)) * typing_speed_ms
    elif action in ("pause", "sleep"):
        step_ms = float(int(step.get("ms", 1000)))
    elif action == "key":
        step_ms = int(step.get("count", 1)) * typing_speed_ms
    elif action == "ctrl":
        step_ms = typing_speed_ms
    elif action in ("hide", "show", "wait"):
        step_ms = 0.0

    after_ms = int(step.get("after_ms", 0))
    return step_ms + float(after_ms)


def _get_setting(spec: dict[str, Any], key: str, default: Any = None) -> Any:
    """Resolve a terminal setting from spec['terminal'] first, falling back to top-level spec."""
    term = spec.get("terminal")
    if isinstance(term, dict) and key in term and term[key] is not None:
        return term[key]
    if key in spec and spec[key] is not None:
        return spec[key]
    return default


def _normalise_key(raw_key: str) -> str:
    key = raw_key.strip()
    if not key:
        raise ValueError("Key name cannot be empty")
    return _KEY_ALIASES.get(key.lower(), key)


def _compile_type_lines(text: str, speed: str | None) -> list[str]:
    """Compile a Type step (handling multi-line text and quote delimiters)."""
    prefix = f"Type@{speed}" if speed else "Type"
    lines: list[str] = []
    segments = text.split("\n")
    for seg_idx, segment in enumerate(segments):
        if segment:
            for chunk in _split_quotable_chunks(segment):
                lines.append(f"{prefix} {_vhs_quote(chunk)}")
        if seg_idx < len(segments) - 1:
            lines.append("Enter")
    return lines


def _compile_step(idx: int, step: dict[str, Any]) -> list[str]:
    action = step.get("action")
    lines: list[str] = []

    if action == "type":
        if "text" not in step or step["text"] is None:
            raise ValueError(f"Step {idx} ('type') requires a 'text' field")
        text = str(step["text"])
        speed = _format_duration(step["speed"]) if step.get("speed") is not None else None
        lines.extend(_compile_type_lines(text, speed))
        if step.get("enter"):
            lines.append("Enter")
    elif action == "enter":
        count = int(step.get("count", 1))
        if count < 1:
            raise ValueError(f"Step {idx} ('enter') count must be >= 1, got {count}")
        lines.append("Enter" if count == 1 else f"Enter {count}")
    elif action in ("pause", "sleep"):
        ms = int(step.get("ms", 1000))
        if ms < 0:
            raise ValueError(f"Step {idx} ({action!r}) ms must be non-negative, got {ms}")
        if ms > 0:
            lines.append(f"Sleep {ms}ms")
    elif action == "key":
        raw_key = step.get("key")
        if not raw_key or not isinstance(raw_key, str):
            raise ValueError(f"Step {idx} ('key') requires a non-empty 'key' field")
        key_name = _normalise_key(raw_key)
        count = int(step.get("count", 1))
        if count < 1:
            raise ValueError(f"Step {idx} ('key') count must be >= 1, got {count}")
        lines.append(key_name if count == 1 else f"{key_name} {count}")
    elif action == "ctrl":
        raw_key = step.get("key")
        if not raw_key or not isinstance(raw_key, str):
            raise ValueError(f"Step {idx} ('ctrl') requires a non-empty 'key' field")
        ctrl_key = raw_key.strip()
        if not ctrl_key:
            raise ValueError(f"Step {idx} ('ctrl') requires a non-empty 'key' field")
        formatted_key = ctrl_key.upper() if len(ctrl_key) == 1 else ctrl_key
        lines.append(f"Ctrl+{formatted_key}")
    elif action == "hide":
        lines.append("Hide")
    elif action == "show":
        lines.append("Show")
    elif action == "wait":
        cmd = "Wait"
        if step.get("timeout") is not None:
            cmd += f"@{_format_duration(step['timeout'])}"
        if step.get("pattern") is not None:
            escaped_pattern = str(step["pattern"]).replace("/", r"\/")
            cmd += f" /{escaped_pattern}/"
        lines.append(cmd)
    else:
        raise ValueError(f"Unknown terminal storyboard action at step {idx}: {action!r}")

    after_ms = int(step.get("after_ms", 0))
    if after_ms < 0:
        raise ValueError(f"Step {idx} after_ms must be non-negative, got {after_ms}")
    if after_ms > 0:
        lines.append(f"Sleep {after_ms}ms")

    return lines


def compile_tape_with_timings(
    spec: dict[str, Any],
    output_path: Path | str,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    step_durations: dict[int, float] | None = None,
    pad_steps: bool | None = None,
    gap_ms: int | None = None,
) -> tuple[str, dict[int, float]]:
    """Compile a terminal storyboard into a VHS .tape script and cumulative step start timestamps.

    When ``step_durations`` (mapping 0-based step index to probed narration clip duration in seconds)
    is provided and ``pad_steps`` is true, emits ``Sleep`` padding so each narrated step stays on
    screen for at least ``clip_duration + gap_ms``.
    """
    resolved_width = int(width if width is not None else _get_setting(spec, "width", DEFAULT_WIDTH))
    resolved_height = int(height if height is not None else _get_setting(spec, "height", DEFAULT_HEIGHT))
    resolved_fps = int(fps if fps is not None else _get_setting(spec, "fps", DEFAULT_FPS))
    theme = _get_setting(spec, "theme", DEFAULT_THEME)
    font_family = _get_setting(spec, "font_family")
    font_size = int(_get_setting(spec, "font_size", DEFAULT_FONT_SIZE))
    padding = int(_get_setting(spec, "padding", DEFAULT_PADDING))
    window_bar = _get_setting(spec, "window_bar", DEFAULT_WINDOW_BAR)
    raw_typing_speed = _get_setting(spec, "typing_speed", DEFAULT_TYPING_SPEED)
    typing_speed = _format_duration(raw_typing_speed)
    typing_speed_ms = _parse_duration_ms(raw_typing_speed)
    shell = _get_setting(spec, "shell")
    env = _get_setting(spec, "env")
    cwd = _get_setting(spec, "cwd")

    narration_cfg = spec.get("narration") if isinstance(spec.get("narration"), dict) else {}
    resolved_pad_steps = (
        bool(pad_steps)
        if pad_steps is not None
        else (bool(narration_cfg["pad_steps"]) if narration_cfg.get("pad_steps") is not None else True)
    )
    resolved_gap_ms = (
        int(gap_ms)
        if gap_ms is not None
        else (int(narration_cfg["gap_ms"]) if narration_cfg.get("gap_ms") is not None else 250)
    )
    if resolved_gap_ms < 0:
        raise ValueError(f"gap_ms must be non-negative, got {resolved_gap_ms}")

    lines: list[str] = [f"Output {_vhs_quote(str(output_path))}"]

    if shell is not None:
        lines.append(f"Set Shell {_vhs_quote(str(shell))}")

    lines.append(f"Set Width {resolved_width}")
    lines.append(f"Set Height {resolved_height}")
    lines.append(f"Set Framerate {resolved_fps}")

    if font_family is not None:
        lines.append(f"Set FontFamily {_vhs_quote(str(font_family))}")

    lines.append(f"Set FontSize {font_size}")
    lines.append(f"Set Padding {padding}")

    if window_bar is not None:
        lines.append(f"Set WindowBar {window_bar}")

    if isinstance(theme, dict):
        lines.append(f"Set Theme {json.dumps(theme)}")
    else:
        lines.append(f"Set Theme {_vhs_quote(str(theme))}")

    lines.append(f"Set TypingSpeed {typing_speed}")

    if env is not None:
        if not isinstance(env, dict):
            raise ValueError("'env' setting must be a mapping of key/value pairs")
        for key, value in env.items():
            lines.append(f"Env {key} {_vhs_quote(str(value))}")

    if cwd is not None:
        cd_cmd = f"cd {shlex.quote(str(cwd))}"
        lines.append("")
        lines.append("Hide")
        lines.extend(_compile_type_lines(cd_cmd, speed=None))
        lines.append("Enter")
        lines.append("Show")

    step_starts: dict[int, float] = {}
    elapsed_ms = 0.0
    hidden = False

    steps = spec.get("steps") or []
    if steps:
        lines.append("")
        for step_index, step in enumerate(steps):
            idx = step_index + 1
            step_starts[step_index] = elapsed_ms / 1000.0
            step_lines = _compile_step(idx, step)

            action = step.get("action")
            if action == "hide":
                hidden = True
            elif action == "show":
                hidden = False
            elif not hidden:
                step_ms = _estimate_step_duration_ms(step, typing_speed_ms)
                if step_durations and step_index in step_durations and resolved_pad_steps:
                    target_ms = float(step_durations[step_index]) * 1000.0 + float(resolved_gap_ms)
                    pad_ms = round(target_ms - step_ms)
                    if pad_ms > 0:
                        step_lines.append(f"Sleep {pad_ms}ms")
                        step_ms += float(pad_ms)
                elapsed_ms += step_ms

            lines.extend(step_lines)

    return "\n".join(lines) + "\n", step_starts


def compile_tape(
    spec: dict[str, Any],
    output_path: Path | str,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    step_durations: dict[int, float] | None = None,
    pad_steps: bool | None = None,
    gap_ms: int | None = None,
) -> str:
    """Compile a terminal storyboard specification dict into a VHS .tape script string."""
    tape, _ = compile_tape_with_timings(
        spec,
        output_path,
        width=width,
        height=height,
        fps=fps,
        step_durations=step_durations,
        pad_steps=pad_steps,
        gap_ms=gap_ms,
    )
    return tape
