"""Extract narration cues, compute SHA-256 cache keys, and build synthesis manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "fal-ai/kokoro/american-english"
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
DEFAULT_PAD_STEPS = True
DEFAULT_GAP_MS = 250
DEFAULT_VOLUME = 1.0
AUDIO_EXTENSIONS: tuple[str, ...] = (".wav", ".mp3", ".m4a", ".ogg")


@dataclass(frozen=True)
class NarrationCue:
    """A single narration cue extracted from a storyboard."""

    id: str
    text: str
    model: str
    voice: str
    speed: float
    step_index: int | None = None
    at: float | None = None


@dataclass(frozen=True)
class ResolvedNarrationCue:
    """A narration cue resolved to an existing audio file and its probed duration."""

    cue: NarrationCue
    path: Path
    duration: float


@dataclass(frozen=True)
class TimedNarrationCue:
    """A resolved narration cue placed on the final video timeline."""

    cue: NarrationCue
    path: Path
    start: float
    duration: float

    @property
    def end(self) -> float:
        """Return the cue end timestamp in seconds."""
        return self.start + self.duration


def compute_cache_key(model: str, voice: str, speed: float, text: str) -> str:
    """Return the deterministic SHA-256 hex digest for a narration cue."""
    payload = {
        "model": model,
        "speed": float(speed),
        "text": text,
        "voice": voice,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_cache_path(narration_dir: Path | str, cache_id: str) -> tuple[Path, bool]:
    """Resolve the target audio path and cache hit status for a cue ID.

    Checks for an existing ``.wav``, ``.mp3``, ``.m4a``, or ``.ogg`` clip matching
    ``cache_id`` in ``narration_dir``. When no cached clip exists, defaults to
    ``<narration_dir>/<cache_id>.wav``.
    """
    cache_dir = Path(narration_dir)
    for ext in AUDIO_EXTENSIONS:
        candidate = cache_dir / f"{cache_id}{ext}"
        if candidate.is_file():
            return candidate, True
    return cache_dir / f"{cache_id}.wav", False


def _make_cue(
    *,
    text: str,
    model: str,
    voice: str,
    speed: float,
    step_index: int | None,
    at: float | None,
) -> NarrationCue:
    key = compute_cache_key(model=model, voice=voice, speed=speed, text=text)
    return NarrationCue(
        id=key[:16],
        text=text,
        model=model,
        voice=voice,
        speed=float(speed),
        step_index=step_index,
        at=at,
    )


def extract_cues(spec: dict[str, Any]) -> list[NarrationCue]:
    """Extract inline ``step['narrate']`` and top-level ``spec['narration']['cues']`` cues."""
    narration_cfg = spec.get("narration")
    if narration_cfg is not None and not isinstance(narration_cfg, dict):
        raise ValueError("storyboard 'narration' field must be an object")
    narration_cfg = narration_cfg or {}

    base_model = str(narration_cfg.get("model") or DEFAULT_MODEL)
    base_voice = str(narration_cfg.get("voice") or DEFAULT_VOICE)
    base_speed = float(narration_cfg["speed"] if narration_cfg.get("speed") is not None else DEFAULT_SPEED)

    cues: list[NarrationCue] = []

    steps = spec.get("steps") or []
    for step_index, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("narrate") is None:
            continue

        raw = step["narrate"]
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                continue
            cues.append(
                _make_cue(
                    text=text,
                    model=base_model,
                    voice=base_voice,
                    speed=base_speed,
                    step_index=step_index,
                    at=None,
                )
            )
        elif isinstance(raw, dict):
            raw_text = raw.get("text")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise ValueError(f"step {step_index} narrate object requires a non-empty 'text' string")
            text = raw_text.strip()
            model = str(raw.get("model") or base_model)
            voice = str(raw.get("voice") or base_voice)
            speed = float(raw["speed"] if raw.get("speed") is not None else base_speed)
            at = float(raw["at"]) if raw.get("at") is not None else None
            cues.append(
                _make_cue(
                    text=text,
                    model=model,
                    voice=voice,
                    speed=speed,
                    step_index=step_index,
                    at=at,
                )
            )
        else:
            raise ValueError(f"step {step_index} narrate must be a string or object")

    raw_cues = narration_cfg.get("cues") or []
    if not isinstance(raw_cues, list):
        raise ValueError("storyboard 'narration.cues' must be a list")

    for cue_index, raw in enumerate(raw_cues):
        if not isinstance(raw, dict):
            raise ValueError(f"narration.cues[{cue_index}] must be an object")
        raw_text = raw.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError(f"narration.cues[{cue_index}] requires a non-empty 'text' string")
        text = raw_text.strip()
        model = str(raw.get("model") or base_model)
        voice = str(raw.get("voice") or base_voice)
        speed = float(raw["speed"] if raw.get("speed") is not None else base_speed)
        at = float(raw["at"]) if raw.get("at") is not None else None
        cues.append(
            _make_cue(
                text=text,
                model=model,
                voice=voice,
                speed=speed,
                step_index=None,
                at=at,
            )
        )

    return cues


def build_narration_plan(spec: dict[str, Any], narration_dir: Path | str) -> dict[str, Any]:
    """Build a JSON-serialisable narration synthesis manifest for a storyboard."""
    cache_dir = Path(narration_dir)
    extracted = extract_cues(spec)

    manifest_cues: list[dict[str, Any]] = []
    missing_count = 0
    for cue in extracted:
        target_path, cached = resolve_cache_path(cache_dir, cue.id)
        if not cached:
            missing_count += 1
        manifest_cues.append(
            {
                "id": cue.id,
                "text": cue.text,
                "model": cue.model,
                "voice": cue.voice,
                "speed": cue.speed,
                "target_path": str(target_path),
                "cached": cached,
                "step_index": cue.step_index,
                "at": cue.at,
            }
        )

    return {
        "narration_dir": str(cache_dir),
        "total": len(manifest_cues),
        "missing_count": missing_count,
        "cues": manifest_cues,
    }


def get_narration_options(spec: dict[str, Any]) -> tuple[bool, int, float]:
    """Return ``(pad_steps, gap_ms, volume)`` resolved from ``spec['narration']``."""
    narration_cfg = spec.get("narration")
    if narration_cfg is not None and not isinstance(narration_cfg, dict):
        raise ValueError("storyboard 'narration' field must be an object")
    cfg = narration_cfg or {}

    pad_steps = bool(cfg["pad_steps"]) if cfg.get("pad_steps") is not None else DEFAULT_PAD_STEPS
    gap_ms = int(cfg["gap_ms"]) if cfg.get("gap_ms") is not None else DEFAULT_GAP_MS
    if gap_ms < 0:
        raise ValueError(f"narration.gap_ms must be non-negative, got {gap_ms}")
    volume = float(cfg["volume"]) if cfg.get("volume") is not None else DEFAULT_VOLUME
    return pad_steps, gap_ms, volume


def find_missing_clips(
    cues: list[NarrationCue],
    narration_dir: Path | str,
) -> list[tuple[NarrationCue, Path]]:
    """Return ``(cue, target_path)`` pairs for narration clips missing from ``narration_dir``."""
    missing: list[tuple[NarrationCue, Path]] = []
    for cue in cues:
        target_path, cached = resolve_cache_path(narration_dir, cue.id)
        if not cached:
            missing.append((cue, target_path))
    return missing


def format_missing_clips_error(
    missing: list[tuple[NarrationCue, Path]],
    *,
    storyboard: Path | str | None = None,
    narration_dir: Path | str | None = None,
) -> str:
    """Build an actionable error message listing missing clips and synthesis instructions."""
    lines = ["error: missing narration audio clip(s):"]
    seen: set[str] = set()
    for cue, target_path in missing:
        if cue.id in seen:
            continue
        seen.add(cue.id)
        lines.append(f"  - {cue.id}: {target_path}")

    cmd_hint = "--plan-narration"
    if storyboard is not None:
        cmd_hint = f"record_demo.py {storyboard} --plan-narration"
        if narration_dir is not None:
            cmd_hint += f" --narration-dir {narration_dir}"
    lines.append(
        f"Run with {cmd_hint} to inspect the synthesis manifest and synthesise the missing "
        "clips via the fal.ai OAuth MCP before recording."
    )
    return "\n".join(lines)


def resolve_narration_clips(
    cues: list[NarrationCue],
    narration_dir: Path | str,
    *,
    probe_duration: Callable[[Path], float],
) -> list[ResolvedNarrationCue]:
    """Resolve existing narration clips and probe each unique clip's duration."""
    duration_cache: dict[Path, float] = {}
    resolved: list[ResolvedNarrationCue] = []
    for cue in cues:
        clip_path, cached = resolve_cache_path(narration_dir, cue.id)
        if not cached:
            raise FileNotFoundError(f"Missing narration clip for cue {cue.id}: {clip_path}")
        key = clip_path.resolve()
        if key not in duration_cache:
            duration_cache[key] = max(0.0, float(probe_duration(clip_path)))
        resolved.append(ResolvedNarrationCue(cue=cue, path=clip_path, duration=duration_cache[key]))
    return resolved


def resolve_timeline(
    resolved_cues: list[ResolvedNarrationCue],
    step_starts: dict[int, float],
) -> list[TimedNarrationCue]:
    """Place resolved narration cues onto the recording timeline in chronological order."""
    indexed: list[tuple[int, TimedNarrationCue]] = []
    for idx, rc in enumerate(resolved_cues):
        if rc.cue.at is not None:
            start = max(0.0, float(rc.cue.at))
        elif rc.cue.step_index is not None:
            start = max(0.0, float(step_starts.get(rc.cue.step_index, 0.0)))
        else:
            start = 0.0
        indexed.append(
            (
                idx,
                TimedNarrationCue(
                    cue=rc.cue,
                    path=rc.path,
                    start=start,
                    duration=rc.duration,
                ),
            )
        )
    indexed.sort(key=lambda pair: (pair[1].start, pair[0]))
    return [item for _, item in indexed]
