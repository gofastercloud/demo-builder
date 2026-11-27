"""Extract narration cues, compute SHA-256 cache keys, and build synthesis manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "fal-ai/kokoro/american-english"
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
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
