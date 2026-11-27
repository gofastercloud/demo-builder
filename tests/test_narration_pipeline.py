"""Offline tests for the end-to-end narration sync, audio muxing, and caption burn-in pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import narration, record_demo, vhs_compiler  # noqa: E402


def _create_dummy_clips(spec: dict[str, Any], narration_dir: Path) -> dict[str, Path]:
    """Create empty placeholder .wav files for every cue in a storyboard."""
    narration_dir.mkdir(parents=True, exist_ok=True)
    created: dict[str, Path] = {}
    for cue in narration.extract_cues(spec):
        clip_path = narration_dir / f"{cue.id}.wav"
        clip_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
        created[cue.id] = clip_path
    return created


class _FakeClock:
    """Deterministic monotonic clock driven by simulated page waits."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, ms: float) -> None:
        self.now += ms / 1000.0


class _FakePage:
    """Minimal Playwright Page double for testing browser step pacing offline."""

    def __init__(self, clock: _FakeClock, *, action_cost_ms: int = 0) -> None:
        self.clock = clock
        self.action_cost_ms = action_cost_ms
        self.waits: list[int] = []
        self.keyboard = MagicMock()
        self.mouse = MagicMock()

        def _type_side_effect(*_args: Any, **_kwargs: Any) -> None:
            self.clock.advance_ms(self.action_cost_ms)

        self.keyboard.type.side_effect = _type_side_effect

    def goto(self, _url: str, **_kwargs: Any) -> None:
        self.clock.advance_ms(self.action_cost_ms)

    def evaluate(self, _script: str) -> None:
        pass

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(int(ms))
        self.clock.advance_ms(ms)


class TestMissingClipsFastFailure:
    """Missing narration clips must fail fast before any recording begins."""

    @pytest.mark.parametrize("mode", ["browser", "terminal"])
    def test_missing_clips_exit_nonzero_before_recording(
        self,
        mode: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        step: dict[str, Any] = (
            {"action": "pause", "ms": 200, "narrate": "First narrated step."}
            if mode == "browser"
            else {"action": "type", "text": "echo hi", "enter": True, "narrate": "First narrated step."}
        )
        spec: dict[str, Any] = {
            "name": "missing-demo",
            "mode": mode,
            "narration": {
                "cues": [{"at": 3.0, "text": "Closing explicit cue."}],
            },
            "steps": [step],
        }
        storyboard = tmp_path / "storyboard.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"
        narration_dir = tmp_path / "clips"

        def _forbid(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("Recording or transcoding must not run when clips are missing")

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
        cues = narration.extract_cues(spec)
        for cue in cues:
            assert cue.id in err
            assert str(narration_dir / f"{cue.id}.wav") in err
        assert "--plan-narration" in err
        assert "fal.ai" in err


class TestBrowserNarrationPacing:
    """Verify monotonic start timestamps and pad_steps / gap_ms waiting in browser mode."""

    def test_browser_records_start_timestamps_and_pads_steps(self) -> None:
        clock = _FakeClock(start=50.0)
        page = _FakePage(clock, action_cost_ms=400)
        steps: list[dict[str, Any]] = [
            {"action": "goto", "url": "http://localhost:8000", "narrate": "Welcome."},
            {"action": "pause", "ms": 500},
            {"action": "type", "text": "hello", "after_ms": 100, "narrate": "Typing now."},
        ]

        step_starts = record_demo._run_steps(
            page,  # type: ignore[arg-type]
            steps,
            show_cursor=False,
            step_clip_durations={0: 2.0, 2: 1.5},
            pad_steps=True,
            gap_ms=250,
            clock=clock,
        )

        # Step 0 starts at 0.0s, action takes 400ms, target is 2000 + 250 = 2250ms -> pad 1850ms
        assert step_starts[0] == pytest.approx(0.0, abs=1e-6)
        # Step 1 pauses 500ms -> Step 2 starts at 2.25 + 0.5 = 2.75s
        assert step_starts[2] == pytest.approx(2.75, abs=1e-6)
        # Step 2 action takes 400ms + after_ms 100ms = 500ms; target 1500 + 250 = 1750ms -> pad 1250ms
        assert page.waits == [1850, 500, 100, 1250]

    def test_browser_does_not_pad_when_step_exceeds_clip_duration(self) -> None:
        clock = _FakeClock(start=10.0)
        page = _FakePage(clock, action_cost_ms=2500)
        steps = [{"action": "goto", "url": "http://localhost:8000", "narrate": "Short line."}]

        step_starts = record_demo._run_steps(
            page,  # type: ignore[arg-type]
            steps,
            show_cursor=False,
            step_clip_durations={0: 1.0},
            pad_steps=True,
            gap_ms=250,
            clock=clock,
        )

        assert step_starts[0] == pytest.approx(0.0, abs=1e-6)
        assert page.waits == []

    def test_browser_pad_steps_false_skips_padding_wait(self) -> None:
        clock = _FakeClock(start=0.0)
        page = _FakePage(clock, action_cost_ms=200)
        steps = [
            {"action": "goto", "url": "http://localhost:8000", "narrate": "Fast step."},
            {"action": "pause", "ms": 300, "narrate": "Second step."},
        ]

        step_starts = record_demo._run_steps(
            page,  # type: ignore[arg-type]
            steps,
            show_cursor=False,
            step_clip_durations={0: 3.0, 1: 2.0},
            pad_steps=False,
            gap_ms=250,
            clock=clock,
        )

        assert step_starts[0] == pytest.approx(0.0, abs=1e-6)
        assert step_starts[1] == pytest.approx(0.2, abs=1e-6)
        assert page.waits == [300]


class TestVhsNarrationPacing:
    """Verify cumulative .tape timestamps and Sleep padding in VHS terminal mode."""

    def test_compile_tape_with_timings_emits_sleep_padding(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "typing_speed": "50ms",
            "narration": {"pad_steps": True, "gap_ms": 250},
            "steps": [
                {"action": "type", "text": "echo hi", "enter": True, "narrate": "Run echo."},
                {"action": "pause", "ms": 500},
                {"action": "type", "text": "ls", "enter": True, "after_ms": 200, "narrate": "List files."},
            ],
        }

        tape, step_starts = vhs_compiler.compile_tape_with_timings(
            spec,
            Path("/tmp/raw.mp4"),
            step_durations={0: 2.0, 2: 1.5},
        )

        # Step 0: "echo hi" (7 chars * 50ms) + Enter (50ms) = 400ms; target = 2250ms -> Sleep 1850ms
        assert "Sleep 1850ms" in tape
        assert step_starts[0] == pytest.approx(0.0, abs=1e-6)
        # Step 1: Sleep 500ms -> elapsed 2750ms -> Step 2 starts at 2.75s
        assert step_starts[2] == pytest.approx(2.75, abs=1e-6)
        # Step 2: "ls" (2*50ms) + Enter (50ms) + after_ms (200ms) = 350ms; target = 1750ms -> Sleep 1400ms
        assert "Sleep 1400ms" in tape

    def test_compile_tape_with_timings_respects_pad_steps_false_and_hide_show(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "typing_speed": "50ms",
            "narration": {"pad_steps": False, "gap_ms": 250},
            "steps": [
                {"action": "hide"},
                {"action": "type", "text": "export FOO=1", "enter": True},
                {"action": "show"},
                {"action": "type", "text": "ls", "enter": True, "narrate": "List files."},
                {"action": "pause", "ms": 400, "narrate": "Pause."},
            ],
        }

        tape, step_starts = vhs_compiler.compile_tape_with_timings(
            spec,
            Path("/tmp/raw.mp4"),
            step_durations={3: 3.0, 4: 2.0},
        )

        # Hidden steps do not advance recorded clock
        assert step_starts[3] == pytest.approx(0.0, abs=1e-6)
        # Step 3 takes 3 * 50ms = 150ms, no padding when pad_steps=False
        assert step_starts[4] == pytest.approx(0.15, abs=1e-6)
        assert "Sleep 3100ms" not in tape


class TestTranscodeNarrationAndBurnCaptions:
    """Verify ffmpeg command construction for narration + audio_tracks and caption burn-in."""

    def test_ffmpeg_combines_audio_tracks_inline_and_explicit_cues(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        music = tmp_path / "bgm.mp3"
        music.write_bytes(b"mp3")
        spec: dict[str, Any] = {
            "name": "mixed-demo",
            "mode": "terminal",
            "typing_speed": "50ms",
            "audio_tracks": [
                {"path": str(music), "start": 0.0, "volume": 0.2, "loop": True},
            ],
            "narration": {
                "pad_steps": True,
                "gap_ms": 250,
                "cues": [
                    {"at": 4.5, "text": "Explicit closing cue."},
                ],
            },
            "steps": [
                {"action": "type", "text": "echo hi", "enter": True, "narrate": "Inline opening cue."},
            ],
        }
        storyboard = tmp_path / "story.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"
        narration_dir = tmp_path / "narration"
        clips = _create_dummy_clips(spec, narration_dir)
        cues = narration.extract_cues(spec)
        inline_id, explicit_id = cues[0].id, cues[1].id

        durations = {
            clips[inline_id].resolve(): 2.0,
            clips[explicit_id].resolve(): 1.25,
        }

        def fake_probe(path: Path) -> float:
            resolved = path.resolve()
            if resolved in durations:
                return durations[resolved]
            return 8.0  # raw video duration

        ffmpeg_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            if cmd[0] == "vhs":
                tape_path = Path(cmd[1])
                raw_mp4 = tape_path.parent / "mixed-demo.raw.mp4"
                raw_mp4.write_bytes(b"raw")
                return MagicMock(returncode=0)
            if cmd[0] == "ffmpeg":
                ffmpeg_calls.append(cmd)
                out_file = Path(cmd[-1])
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_bytes(b"video")
                return MagicMock(returncode=0)
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(record_demo.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(record_demo, "_probe_duration", fake_probe)
        monkeypatch.setattr(record_demo.subprocess, "run", fake_run)

        rc = record_demo.main(
            [
                str(storyboard),
                "--out-dir",
                str(out_dir),
                "--narration-dir",
                str(narration_dir),
            ]
        )

        assert rc == 0

        # Sidecar captions written and synced to resolved (start, start + duration)
        vtt_path = out_dir / "mixed-demo.vtt"
        srt_path = out_dir / "mixed-demo.srt"
        assert vtt_path.is_file()
        assert srt_path.is_file()

        vtt_text = vtt_path.read_text(encoding="utf-8")
        assert "00:00:00.000 --> 00:00:02.000" in vtt_text
        assert "Inline opening cue." in vtt_text
        assert "00:00:04.500 --> 00:00:05.750" in vtt_text
        assert "Explicit closing cue." in vtt_text

        srt_text = srt_path.read_text(encoding="utf-8")
        assert "00:00:00,000 --> 00:00:02,000" in srt_text
        assert "00:00:04,500 --> 00:00:05,750" in srt_text

        # First ffmpeg call is MP4 muxing all 3 audio tracks (bgm + inline + explicit)
        mp4_cmd = ffmpeg_calls[0]
        assert "-stream_loop" in mp4_cmd
        assert str(music.resolve()) in mp4_cmd
        assert str(clips[inline_id].resolve()) in mp4_cmd
        assert str(clips[explicit_id].resolve()) in mp4_cmd

        fc_idx = mp4_cmd.index("-filter_complex")
        filter_complex = mp4_cmd[fc_idx + 1]
        assert "amix=inputs=3" in filter_complex
        assert "volume=0.2" in filter_complex
        assert "adelay=4500|4500" in filter_complex

    @pytest.mark.parametrize("via_cli", [True, False])
    def test_burn_captions_applies_escaped_subtitles_filter_for_mp4_and_webm(
        self,
        via_cli: bool,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Path with spaces, single quote, colon, and brackets
        out_dir = tmp_path / "demo's [v1]:final"
        spec: dict[str, Any] = {
            "name": "cap demo",
            "mode": "terminal",
            "captions": {"burn_in": not via_cli},
            "steps": [
                {"action": "type", "text": "echo ok", "enter": True, "narrate": "Burned caption line."},
            ],
        }
        storyboard = tmp_path / "story.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        narration_dir = tmp_path / "clips"
        _create_dummy_clips(spec, narration_dir)

        ffmpeg_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            if cmd[0] == "vhs":
                raw_mp4 = Path(cmd[1]).parent / "cap demo.raw.mp4"
                raw_mp4.write_bytes(b"raw")
                return MagicMock(returncode=0)
            if cmd[0] == "ffmpeg":
                ffmpeg_calls.append(cmd)
                out_file = Path(cmd[-1])
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_bytes(b"video")
                return MagicMock(returncode=0)
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(record_demo.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(record_demo, "_probe_duration", lambda _path: 2.5)
        monkeypatch.setattr(record_demo.subprocess, "run", fake_run)

        argv = [
            str(storyboard),
            "--out-dir",
            str(out_dir),
            "--narration-dir",
            str(narration_dir),
        ]
        if via_cli:
            argv.append("--burn-captions")

        rc = record_demo.main(argv)
        assert rc == 0

        mp4_cmd = ffmpeg_calls[0]
        webm_cmd = ffmpeg_calls[1]

        # MP4 transcode burns subtitles via filter_complex (since narration audio is present)
        fc_idx = mp4_cmd.index("-filter_complex")
        filter_complex = mp4_cmd[fc_idx + 1]
        assert "[0:v:0]subtitles=filename='" in filter_complex
        assert "[vout]" in filter_complex
        assert "-map" in mp4_cmd
        assert "[vout]" in mp4_cmd

        # Special characters in the subtitle path are safely escaped inside single quotes
        assert r"'\\\''" in filter_complex
        assert r"\:" in filter_complex
        assert "cap demo.srt'" in filter_complex

        # WebM transcodes from the burned-in MP4 so both MP4 and WebM have burned captions
        assert str(out_dir / "cap demo.mp4") in webm_cmd
        assert str(out_dir / "cap demo.webm") == webm_cmd[-1]

    def test_burn_captions_without_audio_tracks_uses_vf_filter(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw_video = tmp_path / "raw.webm"
        raw_video.write_bytes(b"raw")
        out_dir = tmp_path / "out dir"
        srt_path = tmp_path / "my subs:1.srt"
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")

        ffmpeg_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            ffmpeg_calls.append(cmd)
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"video")
            return MagicMock(returncode=0)

        monkeypatch.setattr(record_demo.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(record_demo.subprocess, "run", fake_run)

        record_demo._transcode(
            raw_video,
            out_dir,
            "silent",
            fps=30,
            crf=22,
            poster_time=0.5,
            webm=True,
            audio_tracks=None,
            burn_captions_path=srt_path,
        )

        mp4_cmd = ffmpeg_calls[0]
        vf_idx = mp4_cmd.index("-vf")
        assert mp4_cmd[vf_idx + 1].startswith("subtitles=filename='")
        assert r"\:" in mp4_cmd[vf_idx + 1]
        assert mp4_cmd[vf_idx + 1].endswith("my subs\\:1.srt'")

    def test_browser_mode_end_to_end_emits_captions_and_muxes_narration(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec: dict[str, Any] = {
            "name": "web-narrated",
            "mode": "browser",
            "narration": {
                "cues": [{"at": 5.0, "text": "Wrap up."}],
            },
            "steps": [
                {"action": "goto", "url": "http://localhost:8000", "narrate": "Open dashboard."},
                {"action": "click", "selector": "#go", "narrate": "Run action."},
            ],
        }
        storyboard = tmp_path / "web.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"
        narration_dir = tmp_path / "clips"
        clips = _create_dummy_clips(spec, narration_dir)
        cues = narration.extract_cues(spec)

        def fake_browser(
            _spec: dict[str, Any],
            raw_dir: Path,
            **kwargs: Any,
        ) -> Path:
            assert kwargs["step_clip_durations"] == {0: 1.8, 1: 1.2}
            kwargs["step_starts_out"].update({0: 0.0, 1: 2.1})
            raw = raw_dir / "raw.webm"
            raw.write_bytes(b"webm")
            return raw

        durations = {
            clips[cues[0].id].resolve(): 1.8,
            clips[cues[1].id].resolve(): 1.2,
            clips[cues[2].id].resolve(): 1.0,
        }

        def fake_probe(path: Path) -> float:
            return durations.get(path.resolve(), 7.0)

        ffmpeg_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            ffmpeg_calls.append(cmd)
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"video")
            return MagicMock(returncode=0)

        monkeypatch.setattr(record_demo, "_record_browser", fake_browser)
        monkeypatch.setattr(record_demo, "_probe_duration", fake_probe)
        monkeypatch.setattr(record_demo.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(record_demo.subprocess, "run", fake_run)

        rc = record_demo.main(
            [
                str(storyboard),
                "--out-dir",
                str(out_dir),
                "--narration-dir",
                str(narration_dir),
            ]
        )
        assert rc == 0

        vtt = (out_dir / "web-narrated.vtt").read_text(encoding="utf-8")
        assert "00:00:00.000 --> 00:00:01.800" in vtt
        assert "00:00:02.100 --> 00:00:03.300" in vtt
        assert "00:00:05.000 --> 00:00:06.000" in vtt

        mp4_cmd = ffmpeg_calls[0]
        fc = mp4_cmd[mp4_cmd.index("-filter_complex") + 1]
        assert "amix=inputs=3" in fc
        assert "adelay=2100|2100" in fc
        assert "adelay=5000|5000" in fc

    def test_storyboard_without_narration_writes_no_caption_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec: dict[str, Any] = {
            "name": "silent-demo",
            "mode": "browser",
            "steps": [{"action": "pause", "ms": 200}],
        }
        storyboard = tmp_path / "silent.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"

        monkeypatch.setattr(record_demo, "_record_browser", MagicMock(return_value=tmp_path / "raw.webm"))
        monkeypatch.setattr(record_demo, "_transcode", MagicMock())

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir), "--burn-captions"])
        assert rc == 0
        assert not (out_dir / "silent-demo.vtt").exists()
        assert not (out_dir / "silent-demo.srt").exists()
