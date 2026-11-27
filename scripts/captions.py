"""Generate synced WebVTT (.vtt) and SubRip (.srt) caption sidecar files."""

from __future__ import annotations

import textwrap
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaptionCue:
    """A single timed caption cue in seconds."""

    start: float
    end: float
    text: str


def _format_timestamp(seconds: float, *, separator: str) -> str:
    """Format a timestamp in seconds as ``HH:MM:SS<sep>mmm`` with millisecond rollover."""
    total_ms = round(max(0.0, seconds) * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{millis:03d}"


def _wrap_text(text: str, max_chars: int | None) -> str:
    """Wrap cue text cleanly at word boundaries without dropping words."""
    cleaned = text.strip()
    if max_chars is not None and max_chars <= 0:
        raise ValueError("max_chars must be a positive integer or None")
    if not cleaned or max_chars is None:
        return cleaned

    wrapped_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        wrapped_lines.extend(
            textwrap.wrap(
                stripped,
                width=max_chars,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(wrapped_lines)


def _normalise_cues(cues: Iterable[CaptionCue]) -> list[CaptionCue]:
    """Clamp negative timestamps to 0.0 and prevent overlapping cue end times."""
    clamped = [
        CaptionCue(
            start=max(0.0, cue.start),
            end=max(max(0.0, cue.start), cue.end),
            text=cue.text,
        )
        for cue in cues
    ]
    normalised: list[CaptionCue] = []
    for idx, cue in enumerate(clamped):
        end = cue.end
        if idx + 1 < len(clamped):
            next_start = clamped[idx + 1].start
            end = max(cue.start, min(end, next_start))
        normalised.append(CaptionCue(start=cue.start, end=end, text=cue.text))
    return normalised


def render_vtt(cues: Iterable[CaptionCue], max_chars: int | None = 48) -> str:
    """Render caption cues as a WebVTT (.vtt) document.

    Empty cue lists produce a valid empty WebVTT header (``WEBVTT\\n\\n``).
    """
    normalised = _normalise_cues(cues)
    if not normalised:
        return "WEBVTT\n\n"

    blocks: list[str] = []
    for cue in normalised:
        start_ts = _format_timestamp(cue.start, separator=".")
        end_ts = _format_timestamp(cue.end, separator=".")
        body = _wrap_text(cue.text, max_chars)
        blocks.append(f"{start_ts} --> {end_ts}\n{body}")
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def render_srt(cues: Iterable[CaptionCue], max_chars: int | None = 48) -> str:
    """Render caption cues as a SubRip (.srt) document.

    Empty cue lists produce an empty string.
    """
    normalised = _normalise_cues(cues)
    if not normalised:
        return ""

    blocks: list[str] = []
    for index, cue in enumerate(normalised, start=1):
        start_ts = _format_timestamp(cue.start, separator=",")
        end_ts = _format_timestamp(cue.end, separator=",")
        body = _wrap_text(cue.text, max_chars)
        blocks.append(f"{index}\n{start_ts} --> {end_ts}\n{body}")
    return "\n\n".join(blocks) + "\n"


def write_captions(
    cues: Iterable[CaptionCue],
    out_dir: Path | str,
    name: str,
    max_chars: int | None = 48,
) -> tuple[Path, Path]:
    """Write WebVTT and SubRip sidecar files into ``out_dir`` and return ``(vtt_path, srt_path)``."""
    cue_list = list(cues)
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    vtt_path = target_dir / f"{name}.vtt"
    srt_path = target_dir / f"{name}.srt"
    vtt_path.write_text(render_vtt(cue_list, max_chars=max_chars), encoding="utf-8")
    srt_path.write_text(render_srt(cue_list, max_chars=max_chars), encoding="utf-8")
    return vtt_path, srt_path
