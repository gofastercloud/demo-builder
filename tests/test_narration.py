"""Offline unit tests for narration cue extraction, SHA-256 caching, and --plan-narration CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import narration, record_demo  # noqa: E402


class TestCueExtractionAndOverrides:
    """Verify inline and top-level cue extraction plus default/override precedence."""

    def test_inline_string_and_dict_cues_with_defaults(self) -> None:
        spec: dict[str, Any] = {
            "steps": [
                {"action": "goto", "url": "http://localhost:8000", "narrate": "Welcome to the app."},
                {"action": "pause", "ms": 500},
                {
                    "action": "click",
                    "selector": "#deploy",
                    "narrate": {"text": "Click deploy to ship.", "voice": "am_adam", "speed": 1.15},
                },
            ]
        }

        cues = narration.extract_cues(spec)
        assert len(cues) == 2

        first, second = cues
        assert first.text == "Welcome to the app."
        assert first.model == "fal-ai/kokoro/american-english"
        assert first.voice == "af_heart"
        assert first.speed == 1.0
        assert first.step_index == 0
        assert first.at is None

        assert second.text == "Click deploy to ship."
        assert second.model == "fal-ai/kokoro/american-english"
        assert second.voice == "am_adam"
        assert second.speed == 1.15
        assert second.step_index == 2
        assert second.at is None

    def test_top_level_explicit_cues_and_storyboard_overrides(self) -> None:
        spec: dict[str, Any] = {
            "narration": {
                "model": "fal-ai/kokoro/british-english",
                "voice": "bf_emma",
                "speed": 0.95,
                "cues": [
                    {"at": 0.5, "text": "Opening overview."},
                    {
                        "at": 5.25,
                        "text": "Faster closing line.",
                        "model": "fal-ai/kokoro/american-english",
                        "voice": "af_bella",
                        "speed": 1.2,
                    },
                ],
            },
            "steps": [
                {"action": "pause", "ms": 1000, "narrate": "Inline inherits storyboard overrides."},
            ],
        }

        cues = narration.extract_cues(spec)
        assert len(cues) == 3

        inline_cue, explicit_one, explicit_two = cues
        assert inline_cue.step_index == 0
        assert inline_cue.at is None
        assert inline_cue.model == "fal-ai/kokoro/british-english"
        assert inline_cue.voice == "bf_emma"
        assert inline_cue.speed == 0.95

        assert explicit_one.step_index is None
        assert explicit_one.at == 0.5
        assert explicit_one.model == "fal-ai/kokoro/british-english"
        assert explicit_one.voice == "bf_emma"
        assert explicit_one.speed == 0.95

        assert explicit_two.step_index is None
        assert explicit_two.at == 5.25
        assert explicit_two.model == "fal-ai/kokoro/american-english"
        assert explicit_two.voice == "af_bella"
        assert explicit_two.speed == 1.2

    def test_invalid_cue_shapes_raise_value_error(self) -> None:
        with pytest.raises(ValueError, match="narrate"):
            narration.extract_cues({"steps": [{"action": "pause", "narrate": 123}]})

        with pytest.raises(ValueError, match="text"):
            narration.extract_cues({"steps": [{"action": "pause", "narrate": {"text": "   "}}]})

        with pytest.raises(ValueError, match=r"narration\.cues"):
            narration.extract_cues({"narration": {"cues": [{"at": 1.0}]}})


class TestCacheKeyAndManifest:
    """Verify deterministic SHA-256 keys and cache hit/miss detection across audio formats."""

    def test_cache_key_matches_canonical_sha256(self) -> None:
        key_float = narration.compute_cache_key(
            model="fal-ai/kokoro/american-english",
            voice="af_heart",
            speed=1.0,
            text="Hello world.",
        )
        key_int = narration.compute_cache_key(
            model="fal-ai/kokoro/american-english",
            voice="af_heart",
            speed=1,
            text="Hello world.",
        )
        expected = hashlib.sha256(
            json.dumps(
                {
                    "model": "fal-ai/kokoro/american-english",
                    "speed": 1.0,
                    "text": "Hello world.",
                    "voice": "af_heart",
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        assert key_float == expected
        assert key_int == expected

        # Changing any parameter changes the key.
        assert key_float != narration.compute_cache_key(
            model="fal-ai/kokoro/british-english",
            voice="af_heart",
            speed=1.0,
            text="Hello world.",
        )
        assert key_float != narration.compute_cache_key(
            model="fal-ai/kokoro/american-english",
            voice="am_adam",
            speed=1.0,
            text="Hello world.",
        )
        assert key_float != narration.compute_cache_key(
            model="fal-ai/kokoro/american-english",
            voice="af_heart",
            speed=1.1,
            text="Hello world.",
        )
        assert key_float != narration.compute_cache_key(
            model="fal-ai/kokoro/american-english",
            voice="af_heart",
            speed=1.0,
            text="Goodbye world.",
        )

    def test_cache_hit_and_miss_across_wav_mp3_m4a_ogg(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        spec: dict[str, Any] = {
            "steps": [
                {"action": "pause", "ms": 500, "narrate": "Cached as wav."},
                {"action": "pause", "ms": 500, "narrate": "Cached as mp3."},
                {"action": "pause", "ms": 500, "narrate": "Cached as m4a."},
                {"action": "pause", "ms": 500, "narrate": "Cached as ogg."},
                {"action": "pause", "ms": 500, "narrate": "Not cached yet."},
            ]
        }

        cues = narration.extract_cues(spec)
        (cache_dir / f"{cues[0].id}.wav").write_bytes(b"RIFF")
        (cache_dir / f"{cues[1].id}.mp3").write_bytes(b"ID3")
        (cache_dir / f"{cues[2].id}.m4a").write_bytes(b"ftyp")
        (cache_dir / f"{cues[3].id}.ogg").write_bytes(b"OggS")

        plan = narration.build_narration_plan(spec, cache_dir)
        assert plan["narration_dir"] == str(cache_dir)
        assert plan["total"] == 5
        assert plan["missing_count"] == 1

        by_text = {cue["text"]: cue for cue in plan["cues"]}
        assert by_text["Cached as wav."]["cached"] is True
        assert by_text["Cached as wav."]["target_path"] == str(cache_dir / f"{cues[0].id}.wav")

        assert by_text["Cached as mp3."]["cached"] is True
        assert by_text["Cached as mp3."]["target_path"] == str(cache_dir / f"{cues[1].id}.mp3")

        assert by_text["Cached as m4a."]["cached"] is True
        assert by_text["Cached as m4a."]["target_path"] == str(cache_dir / f"{cues[2].id}.m4a")

        assert by_text["Cached as ogg."]["cached"] is True
        assert by_text["Cached as ogg."]["target_path"] == str(cache_dir / f"{cues[3].id}.ogg")

        assert by_text["Not cached yet."]["cached"] is False
        assert by_text["Not cached yet."]["target_path"] == str(cache_dir / f"{cues[4].id}.wav")

    def test_empty_storyboard_produces_valid_empty_manifest(self, tmp_path: Path) -> None:
        plan = narration.build_narration_plan({"steps": [{"action": "pause", "ms": 500}]}, tmp_path)
        assert plan == {
            "narration_dir": str(tmp_path),
            "total": 0,
            "missing_count": 0,
            "cues": [],
        }


class TestCliPlanNarration:
    """Verify record_demo.py --plan-narration CLI behaviour and isolation."""

    def test_cli_prints_manifest_without_launching_recorders_or_ffmpeg(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        storyboard = tmp_path / "demo.json"
        out_dir = tmp_path / "out"
        default_cache = out_dir / ".narration-cache"
        default_cache.mkdir(parents=True)

        spec: dict[str, Any] = {
            "name": "cli-test",
            "steps": [
                {"action": "goto", "url": "http://localhost:3000", "narrate": "Step one narration."},
            ],
            "narration": {
                "cues": [
                    {"at": 2.5, "text": "Explicit timed narration."},
                ]
            },
        }
        storyboard.write_text(json.dumps(spec), encoding="utf-8")

        # Pre-populate one clip as .mp3 in the default cache directory.
        cached_key = narration.compute_cache_key(
            narration.DEFAULT_MODEL,
            narration.DEFAULT_VOICE,
            narration.DEFAULT_SPEED,
            "Step one narration.",
        )[:16]
        (default_cache / f"{cached_key}.mp3").write_bytes(b"ID3")

        def _forbid(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Recorder/ffmpeg must not be invoked during --plan-narration")

        monkeypatch.setattr(record_demo, "_record_browser", _forbid)
        monkeypatch.setattr(record_demo, "_record_terminal", _forbid)
        monkeypatch.setattr(record_demo, "_transcode", _forbid)
        monkeypatch.setattr(record_demo.subprocess, "run", _forbid)

        exit_code = record_demo.main([str(storyboard), "--out-dir", str(out_dir), "--plan-narration"])
        assert exit_code == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["narration_dir"] == str(default_cache)
        assert payload["total"] == 2
        assert payload["missing_count"] == 1
        assert len(payload["cues"]) == 2

        expected_fields = {
            "id",
            "text",
            "model",
            "voice",
            "speed",
            "target_path",
            "cached",
            "step_index",
            "at",
        }
        for cue in payload["cues"]:
            assert set(cue.keys()) == expected_fields

        inline_cue, explicit_cue = payload["cues"]
        assert inline_cue["id"] == cached_key
        assert inline_cue["cached"] is True
        assert inline_cue["target_path"] == str(default_cache / f"{cached_key}.mp3")
        assert inline_cue["step_index"] == 0
        assert inline_cue["at"] is None

        assert explicit_cue["cached"] is False
        assert explicit_cue["target_path"].endswith(".wav")
        assert explicit_cue["step_index"] is None
        assert explicit_cue["at"] == 2.5

    def test_cli_respects_custom_narration_dir_and_empty_storyboard(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        storyboard = tmp_path / "silent.json"
        out_dir = tmp_path / "out"
        custom_cache = tmp_path / "shared-narration-cache"
        storyboard.write_text(
            json.dumps({"steps": [{"action": "pause", "ms": 200}]}),
            encoding="utf-8",
        )

        exit_code = record_demo.main(
            [
                str(storyboard),
                "--out-dir",
                str(out_dir),
                "--plan-narration",
                "--narration-dir",
                str(custom_cache),
            ]
        )
        assert exit_code == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload == {
            "narration_dir": str(custom_cache),
            "total": 0,
            "missing_count": 0,
            "cues": [],
        }

    def test_cli_direct_script_invocation(self, tmp_path: Path) -> None:
        storyboard = tmp_path / "direct.json"
        out_dir = tmp_path / "out"
        storyboard.write_text(
            json.dumps({"steps": [{"action": "pause", "ms": 300, "narrate": "Direct CLI invocation."}]}),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "record_demo.py"),
                str(storyboard),
                "--out-dir",
                str(out_dir),
                "--plan-narration",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["total"] == 1
        assert payload["missing_count"] == 1
        assert payload["cues"][0]["text"] == "Direct CLI invocation."
