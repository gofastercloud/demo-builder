"""Offline tests for the end-to-end compositor wiring in scripts/record_demo.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import compositor, narration, record_demo  # noqa: E402


class _FakeClock:
    """Deterministic monotonic clock driven by simulated page waits and actions."""

    def __init__(self, start: float = 10.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, ms: float) -> None:
        self.now += ms / 1000.0


class _FakeLocator:
    """Minimal Playwright Locator double returning a fixed bounding box."""

    def __init__(self, box: dict[str, float]) -> None:
        self._box = box
        self.first = self

    def wait_for(self, **_kwargs: Any) -> None:
        pass

    def bounding_box(self) -> dict[str, float]:
        return dict(self._box)


class _FakePage:
    """Minimal Playwright Page double with selector bounding-box lookup."""

    def __init__(
        self,
        clock: _FakeClock,
        boxes: dict[str, dict[str, float]] | None = None,
        *,
        action_cost_ms: int = 0,
    ) -> None:
        self.clock = clock
        self.boxes = boxes or {}
        self.action_cost_ms = action_cost_ms
        self.waits: list[int] = []
        self.locator_calls: list[str] = []
        self.keyboard = MagicMock()
        self.mouse = MagicMock()

    def goto(self, _url: str, **_kwargs: Any) -> None:
        self.clock.advance_ms(self.action_cost_ms)

    def evaluate(self, _script: str) -> None:
        pass

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(int(ms))
        self.clock.advance_ms(ms)

    def locator(self, selector: str) -> _FakeLocator:
        self.locator_calls.append(selector)
        if selector not in self.boxes:
            raise AssertionError(f"Unexpected selector lookup: {selector!r}")
        return _FakeLocator(self.boxes[selector])


def _make_fake_ffmpeg(calls: list[list[str]]) -> Any:
    """Return a subprocess.run fake that records ffmpeg/vhs calls and creates dummy outputs."""

    def _fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "vhs":
            tape_path = Path(cmd[1])
            stem = tape_path.stem
            raw_mp4 = tape_path.parent / f"{stem}.raw.mp4"
            raw_mp4.write_bytes(b"RAW_MP4")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "ffmpeg":
            calls.append(list(cmd))
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"VIDEO_BYTES" * 128)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"Unexpected command: {cmd}")

    return _fake_run


class TestDefaultFramingAndOptOut:
    """Verify default ray.so catppuccin framing and --no-frame / spec opt-outs."""

    def test_default_framing_applies_catppuccin_frame_filter(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec: dict[str, Any] = {
            "name": "framed-demo",
            "mode": "browser",
            "width": 1280,
            "height": 720,
            "fps": 30,
            "steps": [{"action": "pause", "ms": 300}],
        }
        storyboard = tmp_path / "story.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"

        ffmpeg_calls: list[list[str]] = []

        def fake_browser(_spec: dict[str, Any], raw_dir: Path, **_kwargs: Any) -> Path:
            raw = raw_dir / "raw.webm"
            raw.write_bytes(b"WEBM")
            return raw

        monkeypatch.setattr(record_demo, "_record_browser", fake_browser)
        monkeypatch.setattr(record_demo.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr(record_demo.subprocess, "run", _make_fake_ffmpeg(ffmpeg_calls))

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir), "--no-webm"])
        assert rc == 0

        mp4_cmd = ffmpeg_calls[0]
        assert "-filter_complex" in mp4_cmd
        fc = mp4_cmd[mp4_cmd.index("-filter_complex") + 1]
        # Default catppuccin gradient (203, 166, 247) -> (137, 180, 250) and 48px padding => 1376x816
        assert "1376x816" in fc
        assert "r='203+(137-203)*(X/W+Y/H)/2'" in fc
        assert "gblur=sigma=16" in fc
        assert "overlay=x=48:y=48:shortest=1" in fc
        assert "-map" in mp4_cmd
        assert "[vout]" in mp4_cmd

    @pytest.mark.parametrize(
        ("frame_field", "extra_cli"),
        [
            (None, ["--no-frame"]),
            (False, []),
            ({"preset": "none"}, []),
            ("none", []),
        ],
    )
    def test_frame_opt_out_disables_frame_filter(
        self,
        frame_field: Any,
        extra_cli: list[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec: dict[str, Any] = {
            "name": "unframed-demo",
            "mode": "browser",
            "steps": [{"action": "pause", "ms": 200}],
        }
        if frame_field is not None:
            spec["frame"] = frame_field
        storyboard = tmp_path / "story.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"

        ffmpeg_calls: list[list[str]] = []

        def fake_browser(_spec: dict[str, Any], raw_dir: Path, **_kwargs: Any) -> Path:
            raw = raw_dir / "raw.webm"
            raw.write_bytes(b"WEBM")
            return raw

        monkeypatch.setattr(record_demo, "_record_browser", fake_browser)
        monkeypatch.setattr(record_demo.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr(record_demo.subprocess, "run", _make_fake_ffmpeg(ffmpeg_calls))

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir), "--no-webm", *extra_cli])
        assert rc == 0

        mp4_cmd = ffmpeg_calls[0]
        assert "-filter_complex" not in mp4_cmd
        assert "-vf" not in mp4_cmd


class TestZoomAndHighlightCapture:
    """Verify browser selector bounding-box capture and terminal timestamped effects."""

    def test_browser_run_steps_captures_selector_zoom_and_highlight(self) -> None:
        clock = _FakeClock(start=100.0)
        page = _FakePage(
            clock,
            boxes={
                "#hero": {"x": 120.0, "y": 80.0, "width": 400.0, "height": 200.0},
                "#cta": {"x": 500.0, "y": 320.0, "width": 160.0, "height": 48.0},
            },
            action_cost_ms=250,
        )
        steps: list[dict[str, Any]] = [
            {
                "action": "goto",
                "url": "http://localhost:8000",
                "highlight": {
                    "selector": "#hero",
                    "style": "callout",
                    "color": "#f59e0b",
                    "duration_ms": 1200,
                },
            },
            {"action": "pause", "ms": 750},
            {
                "action": "click",
                "selector": "#cta",
                "zoom": {
                    "selector": "#cta",
                    "scale": 1.8,
                    "duration_ms": 1500,
                    "ease_ms": 300,
                },
                "highlight": {
                    "selector": "#cta",
                    "style": "both",
                    "color": "#38bdf8",
                    "duration_ms": 1500,
                },
            },
        ]

        zoom_events: list[compositor.ZoomEvent] = []
        highlight_events: list[compositor.HighlightEvent] = []

        record_demo._run_steps(
            page,  # type: ignore[arg-type]
            steps,
            show_cursor=False,
            clock=clock,
            zoom_events_out=zoom_events,
            highlight_events_out=highlight_events,
        )

        # Step 0 is goto (250ms), so #hero is measured right after goto at t=0.25s.
        assert len(highlight_events) == 2
        hl0 = highlight_events[0]
        assert hl0.start == pytest.approx(0.25)
        assert hl0.end == pytest.approx(1.45)
        assert (hl0.x, hl0.y, hl0.w, hl0.h) == (120.0, 80.0, 400.0, 200.0)
        assert hl0.style == "callout"
        assert hl0.color == "#f59e0b"

        # Step 1 pauses 750ms -> Step 2 starts at t=1.0s; #cta measured before click.
        assert len(zoom_events) == 1
        zm0 = zoom_events[0]
        assert zm0.start == pytest.approx(1.0)
        assert zm0.end == pytest.approx(2.5)
        assert (zm0.x, zm0.y, zm0.w, zm0.h) == (500.0, 320.0, 160.0, 48.0)
        assert zm0.scale == pytest.approx(1.8)
        assert zm0.ease_ms == 300

        hl1 = highlight_events[1]
        assert hl1.start == pytest.approx(1.0)
        assert hl1.end == pytest.approx(2.5)
        assert (hl1.x, hl1.y, hl1.w, hl1.h) == (500.0, 320.0, 160.0, 48.0)
        assert hl1.style == "both"
        assert hl1.color == "#38bdf8"

    def test_terminal_mode_rejects_selector_for_zoom_or_highlight(self) -> None:
        steps = [{"action": "pause", "ms": 200, "zoom": {"selector": "#btn", "scale": 1.5}}]
        with pytest.raises(ValueError, match="explicit x/y/w/h"):
            record_demo._extract_terminal_effects(steps, {0: 0.0})

    def test_terminal_mode_resolves_regions_against_tape_timestamps_and_wires_filters(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec: dict[str, Any] = {
            "name": "term-fx",
            "mode": "terminal",
            "typing_speed": "50ms",
            "width": 1280,
            "height": 720,
            "steps": [
                {"action": "type", "text": "echo hi", "enter": True},
                {
                    "action": "pause",
                    "ms": 1000,
                    "zoom": {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.3, "scale": 1.5, "duration_ms": 900},
                    "highlight": {
                        "x": 0.1,
                        "y": 0.2,
                        "w": 0.5,
                        "h": 0.3,
                        "style": "callout",
                        "color": "#a6e3a1",
                        "duration_ms": 900,
                    },
                },
            ],
        }
        storyboard = tmp_path / "term.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"

        ffmpeg_calls: list[list[str]] = []
        monkeypatch.setattr(record_demo.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(record_demo.subprocess, "run", _make_fake_ffmpeg(ffmpeg_calls))

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir), "--no-webm"])
        assert rc == 0

        mp4_cmd = ffmpeg_calls[0]
        fc = mp4_cmd[mp4_cmd.index("-filter_complex") + 1]
        # Step 0: "echo hi" (7*50ms) + Enter (50ms) = 0.4s -> Step 1 starts at 0.4s, ends at 1.3s.
        assert "enable='between(t,0.4,1.3)'" in fc
        assert "color=#a6e3a1" in fc
        assert "eval=frame:flags=lanczos" in fc
        assert "between(t,0.4,1.3)" in fc
        # Default catppuccin frame is also wired in the same filtergraph.
        assert "1376x816" in fc


class TestMultiSceneXfadePipAndTimelineShifting:
    """Verify multi-scene recording, PiP compositing, xfade transitions, and global cue shifting."""

    def test_multi_scene_with_pip_xfade_narration_captions_and_ducked_music(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec: dict[str, Any] = {
            "name": "wow-multi",
            "width": 1280,
            "height": 720,
            "fps": 30,
            "narration": {
                "voice": "af_heart",
                "pad_steps": True,
                "gap_ms": 250,
                "cues": [{"at": 9.0, "text": "Global wrap-up."}],
            },
            "music": {
                "prompt": "clean upbeat synth",
                "volume": 0.18,
                "duck_db": -12.0,
            },
            "scenes": [
                {
                    "name": "browser-intro",
                    "mode": "browser",
                    "steps": [
                        {
                            "action": "goto",
                            "url": "http://localhost:8000",
                            "narrate": "Scene one browser.",
                        }
                    ],
                    "pip": {
                        "mode": "terminal",
                        "corner": "bottom-right",
                        "scale": 0.3,
                        "start": 0.5,
                        "end": 3.5,
                        "steps": [{"action": "type", "text": "npm run dev", "enter": True}],
                    },
                },
                {
                    "name": "terminal-cli",
                    "mode": "terminal",
                    "typing_speed": "50ms",
                    "transition": {"type": "wipeleft", "duration": 0.5},
                    "steps": [
                        {"action": "pause", "ms": 400},
                        {
                            "action": "type",
                            "text": "deploy --prod",
                            "enter": True,
                            "narrate": "Scene two deploy.",
                        },
                    ],
                },
            ],
        }
        storyboard = tmp_path / "multi.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"
        narration_dir = tmp_path / "cache"
        narration_dir.mkdir(parents=True, exist_ok=True)

        # Pre-populate cached narration clips & music track using --plan-media manifest.
        plan_rc = record_demo.main(
            [
                str(storyboard),
                "--out-dir",
                str(out_dir),
                "--narration-dir",
                str(narration_dir),
                "--plan-media",
            ]
        )
        assert plan_rc == 0

        cue_durations: dict[Path, float] = {}
        for scene_spec in spec["scenes"]:
            scene_cue_spec = {
                "narration": {"voice": "af_heart"},
                "steps": scene_spec["steps"],
            }
            for cue in narration.extract_cues(scene_cue_spec):
                p = narration_dir / f"{cue.id}.wav"
                p.write_bytes(b"RIFF")
                cue_durations[p.resolve()] = 1.5
        for cue in narration.extract_cues({"narration": spec["narration"], "steps": []}):
            p = narration_dir / f"{cue.id}.wav"
            p.write_bytes(b"RIFF")
            cue_durations[p.resolve()] = 1.0

        music_spec = narration.extract_music(spec)
        assert music_spec is not None
        music_path = narration_dir / f"{music_spec.id}.wav"
        music_path.write_bytes(b"RIFF")

        recorded_modes: list[str] = []

        def fake_browser(scene_s: dict[str, Any], raw_dir: Path, **kwargs: Any) -> Path:
            recorded_modes.append("browser")
            if kwargs.get("step_starts_out") is not None:
                kwargs["step_starts_out"][0] = 0.0
            raw = raw_dir / f"{scene_s.get('name', 'browser')}.raw.webm"
            raw.write_bytes(b"WEBM")
            return raw

        def fake_probe(path: Path) -> float:
            resolved = path.resolve()
            if resolved in cue_durations:
                return cue_durations[resolved]
            if "scene_0" in path.name:
                return 4.0
            if "scene_1" in path.name or "terminal-cli" in path.name:
                return 5.0
            return 8.5  # merged video duration (4.0 + 5.0 - 0.5)

        ffmpeg_calls: list[list[str]] = []
        monkeypatch.setattr(record_demo, "_record_browser", fake_browser)
        monkeypatch.setattr(record_demo, "_probe_duration", fake_probe)
        monkeypatch.setattr(record_demo.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(record_demo.subprocess, "run", _make_fake_ffmpeg(ffmpeg_calls))

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
        assert recorded_modes == ["browser"]

        # Inspect ffmpeg calls:
        # 1) PiP composite for scene 0
        # 2) xfade stitch of scene 0 + scene 1
        # 3) Final MP4 transcode (default frame + shifted narration + ducked music)
        # 4) Poster extraction
        assert len(ffmpeg_calls) == 4

        pip_cmd = ffmpeg_calls[0]
        pip_fc = pip_cmd[pip_cmd.index("-filter_complex") + 1]
        assert "overlay=x=W-w-28:y=H-h-28:eof_action=pass:enable='between(t,0.5,3.5)'" in pip_fc

        xfade_cmd = ffmpeg_calls[1]
        xfade_fc = xfade_cmd[xfade_cmd.index("-filter_complex") + 1]
        assert "xfade=transition=wipeleft:duration=0.5:offset=3.5" in xfade_fc

        final_cmd = ffmpeg_calls[2]
        final_fc = final_cmd[final_cmd.index("-filter_complex") + 1]
        # Default catppuccin framing applied to final composed timeline
        assert "1376x816" in final_fc
        # Scene 1 starts at global t=3.5s; step 1 inside scene 1 starts at local 0.4s -> global 3.9s (3900ms)
        assert "adelay=3900|3900" in final_fc
        # Global explicit cue at 9.0s -> 9000ms
        assert "adelay=9000|9000" in final_fc
        # Sidechain ducking present for music + narration
        assert "sidechaincompress" in final_fc

        # Sidecar captions reflect exact shifted global timestamps
        vtt = (out_dir / "wow-multi.vtt").read_text(encoding="utf-8")
        assert "00:00:00.000 --> 00:00:01.500" in vtt
        assert "Scene one browser." in vtt
        assert "00:00:03.900 --> 00:00:05.400" in vtt
        assert "Scene two deploy." in vtt
        assert "00:00:09.000 --> 00:00:10.000" in vtt
        assert "Global wrap-up." in vtt


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestRealFfmpegWowSmoke:
    """Real ffmpeg smoke test verifying framing, zoom/highlight, PiP, and xfade execute cleanly."""

    def test_real_ffmpeg_framed_zoom_highlight_and_multi_scene_xfade_pip(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _make_clip(path: Path, colour: str, duration: float = 2.0) -> Path:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={colour}:s=160x90:d={duration}:r=15",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            return path

        spec: dict[str, Any] = {
            "name": "smoke-multi",
            "width": 160,
            "height": 90,
            "fps": 15,
            "poster_time": 0.5,
            "frame": {"preset": "catppuccin", "padding": 16, "radius": 8, "shadow": True},
            "scenes": [
                {
                    "name": "s1",
                    "mode": "browser",
                    "steps": [
                        {
                            "action": "pause",
                            "ms": 500,
                            "zoom": {"x": 20, "y": 15, "w": 60, "h": 40, "scale": 1.5, "duration_ms": 800},
                            "highlight": {
                                "x": 20,
                                "y": 15,
                                "w": 60,
                                "h": 40,
                                "style": "callout",
                                "duration_ms": 800,
                            },
                        }
                    ],
                    "pip": {
                        "mode": "browser",
                        "corner": "bottom-right",
                        "scale": 0.35,
                        "margin": 8,
                        "start": 0.2,
                        "end": 1.6,
                        "steps": [{"action": "pause", "ms": 400}],
                    },
                },
                {
                    "name": "s2",
                    "mode": "browser",
                    "transition": {"type": "fade", "duration": 0.5},
                    "steps": [{"action": "pause", "ms": 500}],
                },
            ],
        }
        storyboard = tmp_path / "smoke.json"
        storyboard.write_text(json.dumps(spec), encoding="utf-8")
        out_dir = tmp_path / "out"

        clip_colours = iter(["#1e1e2e", "#313244", "#181825"])

        def fake_browser(scene_s: dict[str, Any], raw_dir: Path, **kwargs: Any) -> Path:
            colour = next(clip_colours)
            clip = _make_clip(raw_dir / f"{scene_s.get('name', 'clip')}_{colour.lstrip('#')}.mp4", colour)
            if kwargs.get("zoom_events_out") is not None and scene_s.get("name") == "s1":
                kwargs["zoom_events_out"].append(
                    compositor.ZoomEvent(start=0.2, end=1.0, x=20, y=15, w=60, h=40, scale=1.5, ease_ms=200)
                )
            if kwargs.get("highlight_events_out") is not None and scene_s.get("name") == "s1":
                kwargs["highlight_events_out"].append(
                    compositor.HighlightEvent(
                        start=0.2, end=1.0, x=20, y=15, w=60, h=40, style="callout", color="#38bdf8"
                    )
                )
            return clip

        monkeypatch.setattr(record_demo, "_record_browser", fake_browser)

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir), "--no-webm"])
        assert rc == 0
        assert (out_dir / "smoke-multi.mp4").is_file()
        assert (out_dir / "smoke-multi.mp4").stat().st_size > 0
        assert (out_dir / "smoke-multi.png").is_file()
