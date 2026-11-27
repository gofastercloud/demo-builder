"""Offline tests for background music planning (--plan-media), cache lookup, and sidechain ducking."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import narration, record_demo  # noqa: E402


class TestMusicExtractionAndCacheKey:
    """Verify spec['music'] extraction, defaults, validation, and deterministic SHA-256 keys."""

    def test_absent_music_returns_none(self) -> None:
        assert narration.extract_music({"steps": [{"action": "pause", "ms": 200}]}) is None
        assert narration.extract_music({"music": None, "steps": []}) is None

    def test_music_defaults_and_overrides(self) -> None:
        default_spec = {"music": {"prompt": "warm upbeat ambient synth"}}
        music = narration.extract_music(default_spec)
        assert music is not None
        assert music.prompt == "warm upbeat ambient synth"
        assert music.model == "fal-ai/cassetteai/music-generator"
        assert music.duration_sec == 30
        assert music.volume == 0.18
        assert music.duck_db == -12.0
        assert music.fade_in == 1.0
        assert music.fade_out == 1.5
        assert len(music.id) == 16

        override_spec = {
            "music": {
                "prompt": "  minimal lo-fi beat  ",
                "model": "fal-ai/custom/music",
                "duration_sec": 45,
                "volume": 0.25,
                "duck_db": -16.0,
                "fade_in": 0.5,
                "fade_out": 2.0,
            }
        }
        custom = narration.extract_music(override_spec)
        assert custom is not None
        assert custom.prompt == "minimal lo-fi beat"
        assert custom.model == "fal-ai/custom/music"
        assert custom.duration_sec == 45
        assert custom.volume == 0.25
        assert custom.duck_db == -16.0
        assert custom.fade_in == 0.5
        assert custom.fade_out == 2.0

    def test_invalid_music_shapes_raise_value_error(self) -> None:
        with pytest.raises(ValueError, match="music"):
            narration.extract_music({"music": "not-an-object"})

        with pytest.raises(ValueError, match="prompt"):
            narration.extract_music({"music": {}})

        with pytest.raises(ValueError, match="prompt"):
            narration.extract_music({"music": {"prompt": "   "}})

        with pytest.raises(ValueError, match="duration_sec"):
            narration.extract_music({"music": {"prompt": "ambient", "duration_sec": 0}})

        with pytest.raises(ValueError, match="volume"):
            narration.extract_music({"music": {"prompt": "ambient", "volume": -0.1}})

        with pytest.raises(ValueError, match="duck_db"):
            narration.extract_music({"music": {"prompt": "ambient", "duck_db": 6.0}})

        with pytest.raises(ValueError, match="fade_in"):
            narration.extract_music({"music": {"prompt": "ambient", "fade_in": -1.0}})

        with pytest.raises(ValueError, match="fade_out"):
            narration.extract_music({"music": {"prompt": "ambient", "fade_out": -0.5}})

    def test_music_cache_key_matches_canonical_sha256(self) -> None:
        key_int = narration.compute_music_cache_key(
            model="fal-ai/cassetteai/music-generator",
            prompt="calm tech background",
            duration_sec=30,
        )
        key_float = narration.compute_music_cache_key(
            model="fal-ai/cassetteai/music-generator",
            prompt="calm tech background",
            duration_sec=30.0,
        )
        expected = hashlib.sha256(
            json.dumps(
                {
                    "duration_sec": 30.0,
                    "model": "fal-ai/cassetteai/music-generator",
                    "prompt": "calm tech background",
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        assert key_int == expected
        assert key_float == expected

        # Changing any key component changes the digest.
        assert key_int != narration.compute_music_cache_key(
            model="fal-ai/other/music",
            prompt="calm tech background",
            duration_sec=30,
        )
        assert key_int != narration.compute_music_cache_key(
            model="fal-ai/cassetteai/music-generator",
            prompt="energetic synthwave",
            duration_sec=30,
        )
        assert key_int != narration.compute_music_cache_key(
            model="fal-ai/cassetteai/music-generator",
            prompt="calm tech background",
            duration_sec=45,
        )


class TestPlanMediaManifest:
    """Verify --plan-narration and --plan-media include music and update missing_count."""

    @pytest.mark.parametrize("ext", [".wav", ".mp3", ".m4a", ".ogg"])
    def test_music_cache_hit_across_supported_extensions(self, ext: str, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        spec: dict[str, Any] = {
            "music": {"prompt": "subtle corporate ambient"},
            "steps": [{"action": "pause", "ms": 300}],
        }
        music = narration.extract_music(spec)
        assert music is not None

        clip_path = cache_dir / f"{music.id}{ext}"
        clip_path.write_bytes(b"AUDIO")

        plan = narration.build_narration_plan(spec, cache_dir)
        assert plan["missing_count"] == 0
        assert plan["music"] == {
            "id": music.id,
            "prompt": "subtle corporate ambient",
            "model": "fal-ai/cassetteai/music-generator",
            "duration_sec": 30,
            "target_path": str(clip_path),
            "cached": True,
        }

    def test_missing_music_counted_in_missing_count(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        spec: dict[str, Any] = {
            "music": {"prompt": "gentle acoustic guitar"},
            "steps": [{"action": "pause", "ms": 500, "narrate": "Hello world."}],
        }

        plan = narration.build_narration_plan(spec, cache_dir)
        assert plan["total"] == 1
        assert plan["missing_count"] == 2
        assert plan["music"] is not None
        assert plan["music"]["cached"] is False
        assert plan["music"]["target_path"] == str(cache_dir / f"{plan['music']['id']}.wav")

    @pytest.mark.parametrize("flag", ["--plan-narration", "--plan-media"])
    def test_cli_plan_flags_emit_music_and_do_not_record(
        self,
        flag: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        storyboard = tmp_path / "demo.json"
        out_dir = tmp_path / "out"
        spec: dict[str, Any] = {
            "name": "music-plan-demo",
            "music": {"prompt": "ambient piano bed", "duration_sec": 20},
            "steps": [{"action": "pause", "ms": 200, "narrate": "Intro line."}],
        }
        storyboard.write_text(json.dumps(spec), encoding="utf-8")

        def _forbid(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(f"Recorder/ffmpeg must not run under {flag}")

        monkeypatch.setattr(record_demo, "_record_browser", _forbid)
        monkeypatch.setattr(record_demo, "_record_terminal", _forbid)
        monkeypatch.setattr(record_demo, "_transcode", _forbid)
        monkeypatch.setattr(record_demo.subprocess, "run", _forbid)

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir), flag])
        assert rc == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["total"] == 1
        assert payload["missing_count"] == 2
        assert set(payload["music"].keys()) == {
            "id",
            "prompt",
            "model",
            "duration_sec",
            "target_path",
            "cached",
        }
        assert payload["music"]["prompt"] == "ambient piano bed"
        assert payload["music"]["duration_sec"] == 20
        assert payload["music"]["cached"] is False

    def test_cli_plan_media_emits_null_music_when_absent(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        storyboard = tmp_path / "no-music.json"
        out_dir = tmp_path / "out"
        storyboard.write_text(json.dumps({"steps": [{"action": "pause", "ms": 200}]}), encoding="utf-8")

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir), "--plan-media"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["music"] is None
        assert payload["missing_count"] == 0


class TestMissingMusicFastFailure:
    """Recording with missing cached music must fail fast before capture."""

    @pytest.mark.parametrize("mode", ["browser", "terminal"])
    def test_missing_music_fails_before_recording(
        self,
        mode: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        step: dict[str, Any] = (
            {"action": "pause", "ms": 200}
            if mode == "browser"
            else {"action": "type", "text": "echo hi", "enter": True}
        )
        spec: dict[str, Any] = {
            "name": "missing-music-demo",
            "mode": mode,
            "music": {"prompt": "soft electronic pulse"},
            "steps": [step],
        }
        storyboard = tmp_path / "storyboard.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"
        narration_dir = tmp_path / "media-cache"

        def _forbid(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("Recording or transcoding must not run when music clip is missing")

        monkeypatch.setattr(record_demo, "_record_browser", _forbid)
        monkeypatch.setattr(record_demo, "_record_terminal", _forbid)
        monkeypatch.setattr(record_demo, "_transcode", _forbid)

        rc = record_demo.main(
            [
                str(storyboard),
                "--out-dir",
                str(out_dir),
                "--narration-dir",
                str(narration_dir),
            ]
        )

        assert rc != 0
        err = capsys.readouterr().err
        music = narration.extract_music(spec)
        assert music is not None
        expected_target = str(narration_dir / f"{music.id}.wav")
        assert expected_target in err
        assert "--plan-media" in err
        assert "fal.ai" in err


class TestTranscodeMusicAndDuckingFiltergraph:
    """Verify ffmpeg filtergraph generation for music-only beds and sidechain ducking."""

    def _capture_transcode_cmds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        audio_tracks: list[dict[str, Any]] | None,
        music_track: dict[str, Any] | None,
        video_duration: float = 10.0,
        webm: bool = True,
    ) -> list[list[str]]:
        raw_video = tmp_path / "raw.webm"
        raw_video.write_bytes(b"WEBM")
        out_dir = tmp_path / "out"

        calls: list[list[str]] = []

        def _fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(list(cmd))
            # Create dummy output file so stat() succeeds.
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"DATA" * 512)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(record_demo.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr(record_demo, "_probe_duration", lambda _p: video_duration)
        monkeypatch.setattr(record_demo.subprocess, "run", _fake_run)

        record_demo._transcode(
            raw_video,
            out_dir,
            "demo",
            fps=30,
            crf=22,
            poster_time=1.0,
            webm=webm,
            audio_tracks=audio_tracks,
            music_track=music_track,
        )
        return calls

    def test_music_only_bed_loops_trims_and_fades_without_sidechain(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        music_file = tmp_path / "bed.wav"
        music_file.write_bytes(b"RIFF")

        calls = self._capture_transcode_cmds(
            tmp_path,
            monkeypatch,
            audio_tracks=None,
            music_track={
                "path": str(music_file),
                "volume": 0.18,
                "duck_db": -12.0,
                "fade_in": 1.0,
                "fade_out": 1.5,
            },
            video_duration=10.0,
            webm=True,
        )

        mp4_cmd = calls[0]
        # Must loop music input indefinitely before -i <music_file>.
        music_idx = mp4_cmd.index(str(music_file.resolve()))
        assert mp4_cmd[music_idx - 3 : music_idx] == ["-stream_loop", "-1", "-i"]

        fc = mp4_cmd[mp4_cmd.index("-filter_complex") + 1]
        assert "atrim=0:10.000" in fc
        assert "volume=0.18" in fc
        assert "afade=t=in:st=0:d=1.000" in fc
        assert "afade=t=out:st=8.500:d=1.500" in fc
        assert "sidechaincompress" not in fc
        assert fc.endswith("[aout]")
        assert "-map" in mp4_cmd and "[aout]" in mp4_cmd

        # WebM transcode must retain audio (libopus, not -an).
        webm_cmd = calls[1]
        assert "libopus" in webm_cmd
        assert "-an" not in webm_cmd

    def test_music_with_narration_applies_sidechain_ducking(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cue_file = tmp_path / "cue1.wav"
        cue_file.write_bytes(b"RIFF")
        music_file = tmp_path / "bed.mp3"
        music_file.write_bytes(b"ID3")

        calls = self._capture_transcode_cmds(
            tmp_path,
            monkeypatch,
            audio_tracks=[{"path": str(cue_file), "start": 1.25, "volume": 1.0}],
            music_track={
                "path": str(music_file),
                "volume": 0.2,
                "duck_db": -12.0,
                "fade_in": 1.0,
                "fade_out": 1.5,
            },
            video_duration=8.0,
            webm=False,
        )

        mp4_cmd = calls[0]
        music_idx = mp4_cmd.index(str(music_file.resolve()))
        assert mp4_cmd[music_idx - 3 : music_idx] == ["-stream_loop", "-1", "-i"]

        fc = mp4_cmd[mp4_cmd.index("-filter_complex") + 1]
        assert "adelay=1250|1250" in fc
        assert "asplit=2[narr_mix][narr_sc]" in fc
        assert "atrim=0:8.000" in fc
        assert "volume=0.2" in fc
        assert "afade=t=in:st=0:d=1.000" in fc
        assert "afade=t=out:st=6.500:d=1.500" in fc
        assert "[music][narr_sc]sidechaincompress=" in fc
        assert "[music_ducked]" in fc
        assert "[narr_mix][music_ducked]amix=inputs=2:duration=longest:normalize=0" in fc
        assert "[aout]" in fc

    def test_main_passes_resolved_music_track_to_transcode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        out_dir = tmp_path / "out"
        narration_dir = tmp_path / "cache"
        narration_dir.mkdir()

        spec: dict[str, Any] = {
            "name": "wired-music",
            "mode": "browser",
            "music": {
                "prompt": "clean minimal synth",
                "volume": 0.22,
                "duck_db": -14.0,
                "fade_in": 0.8,
                "fade_out": 1.2,
            },
            "steps": [{"action": "pause", "ms": 200}],
        }
        music = narration.extract_music(spec)
        assert music is not None
        cached_music = narration_dir / f"{music.id}.mp3"
        cached_music.write_bytes(b"ID3")

        storyboard = tmp_path / "demo.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")

        captured: dict[str, Any] = {}

        def _fake_record_browser(_spec: dict[str, Any], raw_dir: Path, **_kwargs: Any) -> Path:
            raw = raw_dir / "raw.webm"
            raw.write_bytes(b"WEBM")
            return raw

        def _fake_transcode(*_args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(record_demo, "_record_browser", _fake_record_browser)
        monkeypatch.setattr(record_demo, "_transcode", _fake_transcode)

        rc = record_demo.main(
            [
                str(storyboard),
                "--out-dir",
                str(out_dir),
                "--narration-dir",
                str(narration_dir),
                "--no-webm",
            ]
        )
        assert rc == 0
        assert captured["audio_tracks"] is None
        assert captured["music_track"] == {
            "path": str(cached_music),
            "volume": 0.22,
            "duck_db": -14.0,
            "fade_in": 0.8,
            "fade_out": 1.2,
        }


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestRealFfmpegSmoke:
    """Smoke-test real ffmpeg execution of both music-only and sidechaincompress filtergraphs."""

    def _make_fixtures(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        raw_video = tmp_path / "raw.mp4"
        narr_wav = tmp_path / "narr.wav"
        music_wav = tmp_path / "music.wav"

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=160x90:d=3:r=15",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(raw_video),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                str(narr_wav),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=220:duration=1",
                str(music_wav),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return raw_video, narr_wav, music_wav

    def test_real_ffmpeg_sidechain_ducking_and_music_only(self, tmp_path: Path) -> None:
        raw_video, narr_wav, music_wav = self._make_fixtures(tmp_path)
        out_dir = tmp_path / "out"

        # 1. Narration + looping music with sidechaincompress ducking.
        record_demo._transcode(
            raw_video,
            out_dir,
            "ducked",
            fps=15,
            crf=28,
            poster_time=0.5,
            webm=False,
            audio_tracks=[{"path": str(narr_wav), "start": 0.5, "volume": 1.0}],
            music_track={
                "path": str(music_wav),
                "volume": 0.18,
                "duck_db": -12.0,
                "fade_in": 0.5,
                "fade_out": 0.5,
            },
        )
        assert (out_dir / "ducked.mp4").stat().st_size > 0
        assert (out_dir / "ducked.png").stat().st_size > 0

        # 2. Music-only bed (no narration).
        record_demo._transcode(
            raw_video,
            out_dir,
            "music-only",
            fps=15,
            crf=28,
            poster_time=0.5,
            webm=False,
            audio_tracks=None,
            music_track={
                "path": str(music_wav),
                "volume": 0.18,
                "duck_db": -12.0,
                "fade_in": 0.5,
                "fade_out": 0.5,
            },
        )
        assert (out_dir / "music-only.mp4").stat().st_size > 0
        assert (out_dir / "music-only.png").stat().st_size > 0
