#!/usr/bin/env python3
"""Record deterministic product demo videos from a JSON storyboard using Playwright or VHS + ffmpeg.

Run browser demos with:
    uv run --with playwright python3 scripts/record_demo.py storyboard.json --out-dir docs/assets/demos

Run terminal demos with:
    python3 scripts/record_demo.py storyboard.json --out-dir docs/assets/demos
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Page

try:
    from scripts.captions import CaptionCue, write_captions
    from scripts.compositor import (
        FrameConfig,
        HighlightEvent,
        PipConfig,
        TransitionSpec,
        ZoomEvent,
        build_frame_filter,
        build_highlight_filter,
        build_pip_filter,
        build_xfade_filter,
        build_zoom_filter,
        resolve_frame_config,
    )
    from scripts.narration import (
        DEFAULT_MUSIC_DUCK_DB,
        DEFAULT_MUSIC_FADE_IN,
        DEFAULT_MUSIC_FADE_OUT,
        DEFAULT_MUSIC_VOLUME,
        NarrationCue,
        TimedNarrationCue,
        build_narration_plan,
        extract_cues,
        extract_music,
        find_missing_clips,
        format_missing_clips_error,
        format_missing_music_error,
        get_narration_options,
        resolve_cache_path,
        resolve_narration_clips,
        resolve_timeline,
    )
    from scripts.vhs_compiler import compile_tape_with_timings
except ModuleNotFoundError:
    from captions import CaptionCue, write_captions
    from compositor import (
        FrameConfig,
        HighlightEvent,
        PipConfig,
        TransitionSpec,
        ZoomEvent,
        build_frame_filter,
        build_highlight_filter,
        build_pip_filter,
        build_xfade_filter,
        build_zoom_filter,
        resolve_frame_config,
    )
    from narration import (
        DEFAULT_MUSIC_DUCK_DB,
        DEFAULT_MUSIC_FADE_IN,
        DEFAULT_MUSIC_FADE_OUT,
        DEFAULT_MUSIC_VOLUME,
        NarrationCue,
        TimedNarrationCue,
        build_narration_plan,
        extract_cues,
        extract_music,
        find_missing_clips,
        format_missing_clips_error,
        format_missing_music_error,
        get_narration_options,
        resolve_cache_path,
        resolve_narration_clips,
        resolve_timeline,
    )
    from vhs_compiler import compile_tape_with_timings

CURSOR_INIT_JS = r"""
(() => {
  if (window.__pdCursorReady) return;
  window.__pdCursorReady = true;

  const inject = () => {
    if (!document.body || document.getElementById('__pd-cursor')) return;
    const style = document.createElement('style');
    style.textContent = `
      #__pd-cursor {
        position: fixed;
        top: 0; left: 0;
        width: 20px; height: 20px;
        border-radius: 50%;
        background: rgba(56, 189, 248, 0.35);
        border: 2px solid #ffffff;
        box-shadow: 0 0 14px rgba(56, 189, 248, 0.85), 0 2px 6px rgba(0, 0, 0, 0.55);
        pointer-events: none;
        z-index: 2147483647;
        transform: translate(-100px, -100px);
        transition: width 120ms ease, height 120ms ease, background 120ms ease;
      }
      #__pd-cursor.down {
        width: 15px; height: 15px;
        background: rgba(245, 158, 11, 0.75);
      }
      .__pd-ripple {
        position: fixed;
        width: 14px; height: 14px;
        margin-left: -7px; margin-top: -7px;
        border-radius: 50%;
        border: 2px solid rgba(56, 189, 248, 0.95);
        pointer-events: none;
        z-index: 2147483646;
        animation: __pd-rip 520ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
      }
      @keyframes __pd-rip {
        0% { transform: scale(0.6); opacity: 0.95; }
        100% { transform: scale(3.4); opacity: 0; }
      }
    `;
    document.head.appendChild(style);
    const cur = document.createElement('div');
    cur.id = '__pd-cursor';
    document.body.appendChild(cur);

    window.addEventListener('mousemove', (e) => {
      cur.style.transform = `translate(${e.clientX - 10}px, ${e.clientY - 10}px)`;
    }, { passive: true });
    window.addEventListener('mousedown', (e) => {
      cur.classList.add('down');
      const r = document.createElement('div');
      r.className = '__pd-ripple';
      r.style.left = `${e.clientX}px`;
      r.style.top = `${e.clientY}px`;
      document.body.appendChild(r);
      setTimeout(() => r.remove(), 560);
    }, { passive: true });
    window.addEventListener('mouseup', () => cur.classList.remove('down'), { passive: true });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject, { once: true });
  } else {
    inject();
  }
})();
"""


def _bounding_box_of(page: Page, selector: str, timeout: int = 8000) -> tuple[float, float, float, float]:
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=timeout)
    box = loc.bounding_box()
    if not box:
        raise RuntimeError(f"Element {selector!r} has no bounding box")
    return float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])


def _center_of(page: Page, selector: str, timeout: int = 8000) -> tuple[float, float]:
    x, y, w, h = _bounding_box_of(page, selector, timeout=timeout)
    return x + w / 2.0, y + h / 2.0


def _resolve_effect_region(
    cfg: dict[str, Any],
    step: dict[str, Any],
    page: Page | None,
) -> tuple[float, float, float, float]:
    """Resolve an effect's (x, y, w, h) region from explicit coordinates or a browser selector."""
    if all(k in cfg for k in ("x", "y", "w", "h")):
        return (float(cfg["x"]), float(cfg["y"]), float(cfg["w"]), float(cfg["h"]))
    selector = cfg.get("selector") or step.get("selector")
    if selector:
        if page is None:
            raise ValueError(
                "Terminal mode zoom/highlight requires explicit x/y/w/h coordinates, not 'selector'"
            )
        return _bounding_box_of(page, str(selector))
    raise ValueError("Step zoom/highlight requires either 'selector' or 'x', 'y', 'w', 'h'")


def _build_zoom_event(
    cfg: dict[str, Any],
    step: dict[str, Any],
    start: float,
    page: Page | None,
) -> ZoomEvent:
    x, y, w, h = _resolve_effect_region(cfg, step, page)
    duration_ms = float(cfg.get("duration_ms", 1500))
    return ZoomEvent(
        start=start,
        end=start + duration_ms / 1000.0,
        x=x,
        y=y,
        w=w,
        h=h,
        scale=float(cfg.get("scale", 1.6)),
        ease_ms=int(cfg.get("ease_ms", 350)),
    )


def _build_highlight_event(
    cfg: dict[str, Any],
    step: dict[str, Any],
    start: float,
    page: Page | None,
) -> HighlightEvent:
    x, y, w, h = _resolve_effect_region(cfg, step, page)
    duration_ms = float(cfg.get("duration_ms", 1500))
    return HighlightEvent(
        start=start,
        end=start + duration_ms / 1000.0,
        x=x,
        y=y,
        w=w,
        h=h,
        style=str(cfg.get("style", "spotlight")),
        dim_opacity=float(cfg.get("dim_opacity", 0.45)),
        color=str(cfg.get("color", "#38bdf8")),
        border_width=int(cfg.get("border_width", 3)),
    )


def _extract_terminal_effects(
    steps: list[dict[str, Any]],
    step_starts: dict[int, float],
) -> tuple[list[ZoomEvent], list[HighlightEvent]]:
    """Build timestamped ZoomEvent and HighlightEvent lists from terminal step specs."""
    zoom_events: list[ZoomEvent] = []
    highlight_events: list[HighlightEvent] = []
    for step_index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        start = max(0.0, float(step_starts.get(step_index, 0.0)))
        raw_zoom = step.get("zoom")
        if isinstance(raw_zoom, dict):
            zoom_events.append(_build_zoom_event(raw_zoom, step, start, page=None))
        raw_hl = step.get("highlight")
        if isinstance(raw_hl, dict):
            highlight_events.append(_build_highlight_event(raw_hl, step, start, page=None))
    return zoom_events, highlight_events


def _run_steps(
    page: Page,
    steps: list[dict[str, Any]],
    show_cursor: bool,
    *,
    step_clip_durations: dict[int, float] | None = None,
    pad_steps: bool = True,
    gap_ms: int = 250,
    clock: Callable[[], float] = time.monotonic,
    zoom_events_out: list[ZoomEvent] | None = None,
    highlight_events_out: list[HighlightEvent] | None = None,
) -> dict[int, float]:
    step_starts: dict[int, float] = {}
    recording_start = clock()

    def _capture_effects(step: dict[str, Any], effect_start: float) -> None:
        raw_zoom = step.get("zoom")
        if isinstance(raw_zoom, dict) and zoom_events_out is not None:
            zoom_events_out.append(_build_zoom_event(raw_zoom, step, effect_start, page))
        raw_hl = step.get("highlight")
        if isinstance(raw_hl, dict) and highlight_events_out is not None:
            highlight_events_out.append(_build_highlight_event(raw_hl, step, effect_start, page))

    for step_index, step in enumerate(steps):
        idx = step_index + 1
        step_start = clock()
        if step_clip_durations and step_index in step_clip_durations:
            step_starts[step_index] = max(0.0, step_start - recording_start)

        action = step.get("action")
        measure_after = action in ("goto", "wait_for")
        if not measure_after:
            _capture_effects(step, max(0.0, step_start - recording_start))

        if action == "goto":
            page.goto(step["url"], wait_until=step.get("wait_until", "networkidle"))
            if show_cursor:
                page.evaluate(CURSOR_INIT_JS)
        elif action == "wait_for":
            page.locator(step["selector"]).first.wait_for(
                state=step.get("state", "visible"),
                timeout=int(step.get("timeout", 10000)),
            )
        elif action == "pause":
            page.wait_for_timeout(int(step.get("ms", 1000)))
        elif action == "move":
            if "selector" in step:
                x, y = _center_of(page, step["selector"])
            else:
                x, y = float(step["x"]), float(step["y"])
            page.mouse.move(x, y, steps=int(step.get("steps", 18)))
        elif action == "hover":
            x, y = _center_of(page, step["selector"])
            page.mouse.move(x, y, steps=int(step.get("steps", 18)))
        elif action == "click":
            if "selector" in step:
                x, y = _center_of(page, step["selector"])
            else:
                x, y = float(step["x"]), float(step["y"])
            page.mouse.move(x, y, steps=int(step.get("steps", 16)))
            page.wait_for_timeout(int(step.get("pre_ms", 120)))
            page.mouse.click(x, y)
        elif action == "dblclick":
            if "selector" in step:
                x, y = _center_of(page, step["selector"])
            else:
                x, y = float(step["x"]), float(step["y"])
            page.mouse.move(x, y, steps=int(step.get("steps", 16)))
            page.wait_for_timeout(100)
            page.mouse.dblclick(x, y)
        elif action == "drag":
            if "selector" in step:
                sx, sy = _center_of(page, step["selector"])
                ex, ey = sx + float(step.get("dx", 0)), sy + float(step.get("dy", 0))
            else:
                sx, sy = float(step["from_x"]), float(step["from_y"])
                ex, ey = float(step["to_x"]), float(step["to_y"])
            page.mouse.move(sx, sy, steps=10)
            page.mouse.down()
            page.mouse.move(ex, ey, steps=int(step.get("steps", 30)))
            page.mouse.up()
        elif action == "type":
            if "selector" in step:
                x, y = _center_of(page, step["selector"])
                page.mouse.move(x, y, steps=12)
                page.mouse.click(x, y)
            page.keyboard.type(str(step["text"]), delay=int(step.get("delay", 55)))
        elif action == "press":
            page.keyboard.press(str(step["key"]))
        elif action == "scroll":
            if "selector" in step:
                x, y = _center_of(page, step["selector"])
                page.mouse.move(x, y, steps=8)
            page.mouse.wheel(float(step.get("dx", 0)), float(step.get("dy", 300)))
        elif action == "eval":
            page.evaluate(step["script"])
        else:
            raise ValueError(f"Unknown storyboard action at step {idx}: {action!r}")

        if measure_after:
            _capture_effects(step, max(0.0, clock() - recording_start))

        after_ms = int(step.get("after_ms", 0))
        if after_ms > 0:
            page.wait_for_timeout(after_ms)

        if step_clip_durations and step_index in step_clip_durations and pad_steps:
            elapsed = clock() - step_start
            target = float(step_clip_durations[step_index]) + (gap_ms / 1000.0)
            remaining_ms = round((target - elapsed) * 1000)
            if remaining_ms > 0:
                page.wait_for_timeout(remaining_ms)

    return step_starts


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def _escape_ffmpeg_subtitles_path(path: Path) -> str:
    """Escape and single-quote a filesystem path for ffmpeg's subtitles video filter."""
    raw = str(path.resolve())
    raw = raw.replace("\\", "\\\\")
    raw = raw.replace(":", "\\:")
    raw = raw.replace("'", "'\\\\\\''")
    return f"'{raw}'"


def _music_filter_chain(
    input_idx: int,
    music_track: dict[str, Any],
    vid_dur: float,
    out_label: str,
) -> str:
    """Build the ffmpeg audio filter chain for a looped, trimmed, faded background music bed."""
    vol = float(music_track.get("volume", DEFAULT_MUSIC_VOLUME))
    fade_in = min(max(0.0, float(music_track.get("fade_in", DEFAULT_MUSIC_FADE_IN))), vid_dur)
    fade_out = min(max(0.0, float(music_track.get("fade_out", DEFAULT_MUSIC_FADE_OUT))), vid_dur)
    fade_out_start = max(0.0, vid_dur - fade_out)

    chain = (
        f"[{input_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
        f"atrim=0:{vid_dur:.3f},asetpts=PTS-STARTPTS,volume={vol}"
    )
    if fade_in > 0:
        chain += f",afade=t=in:st=0:d={fade_in:.3f}"
    if fade_out > 0:
        chain += f",afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
    return f"{chain}[{out_label}]"


def _build_video_filter_parts(
    input_label: str,
    output_label: str,
    *,
    width: int,
    height: int,
    fps: int,
    highlight_events: list[HighlightEvent] | None = None,
    zoom_events: list[ZoomEvent] | None = None,
    subtitles_filter: str | None = None,
    frame_config: FrameConfig | None = None,
) -> list[str]:
    """Chain highlight, zoom, subtitles, and ray.so presentation framing in deterministic order."""
    stages: list[str] = []
    if highlight_events:
        stages.append("highlight")
    if zoom_events:
        stages.append("zoom")
    if subtitles_filter is not None:
        stages.append("subtitles")
    if frame_config is not None and frame_config.enabled:
        stages.append("frame")

    if not stages:
        return []

    parts: list[str] = []
    cur = input_label
    for idx, stage in enumerate(stages):
        out_lbl = output_label if idx == len(stages) - 1 else f"v_{stage}"
        if stage == "highlight":
            parts.extend(build_highlight_filter(cur, out_lbl, width, height, highlight_events or []))
        elif stage == "zoom":
            parts.extend(build_zoom_filter(cur, out_lbl, width, height, zoom_events or []))
        elif stage == "subtitles":
            parts.append(f"[{cur}]{subtitles_filter}[{out_lbl}]")
        elif stage == "frame" and frame_config is not None:
            parts.extend(build_frame_filter(cur, out_lbl, width, height, fps, frame_config))
        cur = out_lbl
    return parts


def _transcode(
    raw_webm: Path,
    out_dir: Path,
    name: str,
    fps: int,
    crf: int,
    poster_time: float,
    webm: bool,
    audio_tracks: list[dict[str, Any]] | None = None,
    burn_captions_path: Path | None = None,
    music_track: dict[str, Any] | None = None,
    *,
    width: int = 1280,
    height: int = 720,
    frame_config: FrameConfig | None = None,
    zoom_events: list[ZoomEvent] | None = None,
    highlight_events: list[HighlightEvent] | None = None,
) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = out_dir / f"{name}.mp4"
    webm_path = out_dir / f"{name}.webm"
    poster_path = out_dir / f"{name}.png"

    tracks = audio_tracks or []
    has_audio = bool(tracks or music_track)
    cmd: list[str] = ["ffmpeg", "-y", "-i", str(raw_webm)]
    subtitles_filter = (
        f"subtitles=filename={_escape_ffmpeg_subtitles_path(burn_captions_path)}"
        if burn_captions_path is not None
        else None
    )
    has_complex_video = bool(
        zoom_events or highlight_events or (frame_config is not None and frame_config.enabled)
    )

    if has_audio or has_complex_video:
        filter_parts = _build_video_filter_parts(
            "0:v:0",
            "vout",
            width=width,
            height=height,
            fps=fps,
            highlight_events=highlight_events,
            zoom_events=zoom_events,
            subtitles_filter=subtitles_filter,
            frame_config=frame_config,
        )
        video_map = "[vout]" if filter_parts else "0:v:0"

        if has_audio:
            vid_dur = _probe_duration(raw_webm)
            fade_start = max(0.0, vid_dur - 1.2)
            mix_labels: list[str] = []
            for idx, tr in enumerate(tracks, 1):
                t_path = Path(tr["path"]).expanduser().resolve()
                if tr.get("loop"):
                    cmd += ["-stream_loop", "-1"]
                cmd += ["-i", str(t_path)]
                delay_ms = round(float(tr.get("start", 0.0)) * 1000)
                vol = float(tr.get("volume", 1.0))
                lbl = f"a{idx}"
                chain = f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol}"
                if delay_ms > 0:
                    chain += f",adelay={delay_ms}|{delay_ms}"
                chain += f"[{lbl}]"
                filter_parts.append(chain)
                mix_labels.append(f"[{lbl}]")

            if music_track is not None:
                music_idx = len(tracks) + 1
                music_path = Path(music_track["path"]).expanduser().resolve()
                cmd += ["-stream_loop", "-1", "-i", str(music_path)]

                if tracks:
                    joined = "".join(mix_labels)
                    filter_parts.append(
                        f"{joined}amix=inputs={len(tracks)}:duration=longest:normalize=0,"
                        f"apad=whole_dur={vid_dur:.3f},atrim=0:{vid_dur:.3f},asetpts=PTS-STARTPTS,"
                        "asplit=2[narr_mix][narr_sc]"
                    )
                    filter_parts.append(_music_filter_chain(music_idx, music_track, vid_dur, "music"))
                    duck_db = float(music_track.get("duck_db", DEFAULT_MUSIC_DUCK_DB))
                    ratio = min(20.0, max(1.0, 1.0 + abs(duck_db) / 2.0))
                    filter_parts.append(
                        "[music][narr_sc]sidechaincompress="
                        f"threshold=0.02:ratio={ratio:.2f}:attack=20:release=250:makeup=1[music_ducked]"
                    )
                    filter_parts.append(
                        "[narr_mix][music_ducked]amix=inputs=2:duration=longest:normalize=0,"
                        f"atrim=0:{vid_dur:.3f}[aout]"
                    )
                else:
                    filter_parts.append(_music_filter_chain(music_idx, music_track, vid_dur, "aout"))
            else:
                joined = "".join(mix_labels)
                filter_parts.append(
                    f"{joined}amix=inputs={len(tracks)}:duration=longest:normalize=0,"
                    f"atrim=0:{vid_dur:.3f},afade=t=out:st={fade_start:.3f}:d=1.2[aout]"
                )
            cmd += [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                video_map,
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(mp4_path),
            ]
        else:
            cmd += [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                video_map,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-movflags",
                "+faststart",
                "-an",
                str(mp4_path),
            ]
    else:
        if subtitles_filter is not None:
            cmd += ["-vf", subtitles_filter]
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-movflags",
            "+faststart",
            "-an",
            str(mp4_path),
        ]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # WebM transcodes from mp4_path, so mixed audio and any burned-in captions carry over
    # to the WebM output without double-rendering subtitles.
    if webm:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(mp4_path),
                "-c:v",
                "libvpx-vp9",
                "-crf",
                str(min(40, crf + 10)),
                "-b:v",
                "0",
                "-r",
                str(fps),
                *(["-c:a", "libopus", "-b:a", "96k"] if has_audio else ["-an"]),
                str(webm_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(poster_time),
            "-i",
            str(mp4_path),
            "-frames:v",
            "1",
            str(poster_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    mp4_kb = mp4_path.stat().st_size // 1024
    msg = f"Wrote {mp4_path} ({mp4_kb} KB) and poster {poster_path}"
    if webm and webm_path.is_file():
        msg += f" + {webm_path} ({webm_path.stat().st_size // 1024} KB)"
    print(msg)


def _record_browser(
    spec: dict[str, Any],
    raw_dir: Path,
    *,
    width: int,
    height: int,
    headed: bool,
    step_clip_durations: dict[int, float] | None = None,
    pad_steps: bool = True,
    gap_ms: int = 250,
    step_starts_out: dict[int, float] | None = None,
    zoom_events_out: list[ZoomEvent] | None = None,
    highlight_events_out: list[HighlightEvent] | None = None,
) -> Path:
    from playwright.sync_api import sync_playwright

    show_cursor = bool(spec.get("cursor", True))
    color_scheme = spec.get("color_scheme", "dark")
    steps = spec.get("steps") or []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headed,
            args=[
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-webgl",
                "--ignore-gpu-blocklist",
            ],
        )
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
            color_scheme=color_scheme,
            record_video_dir=str(raw_dir),
            record_video_size={"width": width, "height": height},
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        recorded_starts = _run_steps(
            page,
            steps,
            show_cursor,
            step_clip_durations=step_clip_durations,
            pad_steps=pad_steps,
            gap_ms=gap_ms,
            zoom_events_out=zoom_events_out,
            highlight_events_out=highlight_events_out,
        )
        if step_starts_out is not None:
            step_starts_out.update(recorded_starts)
        video = page.video
        context.close()
        browser.close()
        if video is None:
            raise RuntimeError("Playwright produced no video")
        raw_webm = Path(video.path())

    if errors:
        print(f"warning: {len(errors)} pageerror(s) during recording: {errors}", file=sys.stderr)
    return raw_webm


def _record_terminal(
    spec: dict[str, Any],
    raw_dir: Path,
    *,
    name: str,
    out_dir: Path,
    width: int | None,
    height: int | None,
    fps: int | None,
    keep_tape: bool,
    step_clip_durations: dict[int, float] | None = None,
    pad_steps: bool = True,
    gap_ms: int = 250,
    step_starts_out: dict[int, float] | None = None,
    zoom_events_out: list[ZoomEvent] | None = None,
    highlight_events_out: list[HighlightEvent] | None = None,
) -> Path:
    if not shutil.which("vhs"):
        raise RuntimeError("vhs not found on PATH (install Charmbracelet VHS to record terminal demos)")

    raw_video = raw_dir / f"{name}.raw.mp4"
    tape_content, compiled_starts = compile_tape_with_timings(
        spec,
        raw_video,
        width=width,
        height=height,
        fps=fps,
        step_durations=step_clip_durations,
        pad_steps=pad_steps,
        gap_ms=gap_ms,
    )
    if step_starts_out is not None:
        step_starts_out.update(compiled_starts)
    if zoom_events_out is not None or highlight_events_out is not None:
        term_zooms, term_highlights = _extract_terminal_effects(spec.get("steps") or [], compiled_starts)
        if zoom_events_out is not None:
            zoom_events_out.extend(term_zooms)
        if highlight_events_out is not None:
            highlight_events_out.extend(term_highlights)

    tape_path = raw_dir / f"{name}.tape"
    tape_path.write_text(tape_content, encoding="utf-8")

    if keep_tape:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.tape").write_text(tape_content, encoding="utf-8")

    subprocess.run(["vhs", str(tape_path)], check=True)
    if not raw_video.is_file():
        raise RuntimeError("vhs produced no video")
    return raw_video


_INHERITABLE_SCENE_KEYS: tuple[str, ...] = (
    "mode",
    "cursor",
    "color_scheme",
    "terminal",
    "typing_speed",
    "cadence",
    "theme",
    "font_size",
    "padding",
    "window_bar",
    "shell",
    "env",
    "cwd",
    "width",
    "height",
    "fps",
)


def _build_scene_spec(top_spec: dict[str, Any], scene: dict[str, Any], idx: int) -> dict[str, Any]:
    """Merge top-level storyboard defaults with a single scene's overrides."""
    merged: dict[str, Any] = {}
    for key in _INHERITABLE_SCENE_KEYS:
        if key in top_spec:
            merged[key] = top_spec[key]
    merged.update(scene)
    merged.setdefault("name", f"scene_{idx}")

    top_narr = top_spec.get("narration") if isinstance(top_spec.get("narration"), dict) else {}
    scene_narr = scene.get("narration") if isinstance(scene.get("narration"), dict) else {}
    merged_narr: dict[str, Any] = {
        k: v for k, v in top_narr.items() if k in ("model", "voice", "speed", "pad_steps", "gap_ms", "volume")
    }
    merged_narr.update(scene_narr)
    if merged_narr:
        merged["narration"] = merged_narr
    elif "narration" in merged:
        del merged["narration"]
    return merged


def _parse_transition(raw: Any) -> TransitionSpec:
    """Parse a scene transition specification into a validated TransitionSpec."""
    if raw is None:
        return TransitionSpec()
    if isinstance(raw, TransitionSpec):
        return raw
    if isinstance(raw, str):
        return TransitionSpec(type=raw)
    if isinstance(raw, dict):
        t_type = str(raw.get("type", "fade"))
        if "duration" in raw and raw["duration"] is not None:
            duration = float(raw["duration"])
        elif "duration_ms" in raw and raw["duration_ms"] is not None:
            duration = float(raw["duration_ms"]) / 1000.0
        else:
            duration = 0.5
        return TransitionSpec(type=t_type, duration=duration)
    raise ValueError(f"Unsupported transition specification: {raw!r}")


def _resolve_scene_transitions(scenes: list[dict[str, Any]]) -> list[TransitionSpec]:
    """Resolve N-1 TransitionSpecs for N scenes, supporting incoming or outgoing placement."""
    if len(scenes) < 2:
        return []
    use_incoming = scenes[0].get("transition") is None and scenes[-1].get("transition") is not None
    transitions: list[TransitionSpec] = []
    for idx in range(len(scenes) - 1):
        raw = scenes[idx + 1].get("transition") if use_incoming else scenes[idx].get("transition")
        transitions.append(_parse_transition(raw))
    return transitions


def _parse_pip_config(pip_spec: dict[str, Any]) -> PipConfig:
    """Extract a validated PipConfig from an inline scene 'pip' specification."""
    return PipConfig(
        corner=str(pip_spec.get("corner", "bottom-right")),
        scale=float(pip_spec.get("scale", 0.32)),
        margin=int(pip_spec.get("margin", 28)),
        start=float(pip_spec.get("start", 0.0)),
        end=float(pip_spec["end"]) if pip_spec.get("end") is not None else None,
        radius=int(pip_spec.get("radius", 12)),
        border_color=str(pip_spec.get("border_color", "#cdd6f4")),
        border_width=int(pip_spec.get("border_width", 2)),
    )


def _extract_all_multi_scene_cues(
    spec: dict[str, Any],
    scene_specs: list[dict[str, Any]],
) -> tuple[list[list[NarrationCue]], list[NarrationCue]]:
    """Extract per-scene cues and top-level global explicit cues for a multi-scene storyboard."""
    per_scene_cues = [extract_cues(s_spec) for s_spec in scene_specs]
    global_spec = {**spec, "steps": []}
    global_cues = extract_cues(global_spec)
    return per_scene_cues, global_cues


def _build_storyboard_plan(spec: dict[str, Any], narration_dir: Path) -> dict[str, Any]:
    """Build a narration and music synthesis manifest for single-scene or multi-scene storyboards."""
    scenes = spec.get("scenes")
    if scenes is None:
        return build_narration_plan(spec, narration_dir)

    scene_specs = [_build_scene_spec(spec, s, i) for i, s in enumerate(scenes)]
    per_scene_cues, global_cues = _extract_all_multi_scene_cues(spec, scene_specs)
    all_cues: list[NarrationCue] = [cue for group in per_scene_cues for cue in group] + global_cues

    manifest_cues: list[dict[str, Any]] = []
    missing_count = 0
    for cue in all_cues:
        target_path, cached = resolve_cache_path(narration_dir, cue.id)
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

    music = extract_music(spec)
    music_entry: dict[str, Any] | None = None
    if music is not None:
        music_target, music_cached = resolve_cache_path(narration_dir, music.id)
        if not music_cached:
            missing_count += 1
        music_entry = {
            "id": music.id,
            "prompt": music.prompt,
            "model": music.model,
            "duration_sec": music.duration_sec,
            "target_path": str(music_target),
            "cached": music_cached,
        }

    return {
        "narration_dir": str(narration_dir),
        "total": len(manifest_cues),
        "missing_count": missing_count,
        "cues": manifest_cues,
        "music": music_entry,
    }


def _composite_scene_video(
    raw_video: Path,
    out_path: Path,
    *,
    width: int,
    height: int,
    fps: int,
    crf: int,
    zoom_events: list[ZoomEvent],
    highlight_events: list[HighlightEvent],
    pip_video: Path | None,
    pip_config: PipConfig | None,
) -> Path:
    """Composite per-scene highlight, zoom, and optional PiP overlay into a temporary MP4."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")

    cmd: list[str] = ["ffmpeg", "-y", "-i", str(raw_video)]
    if pip_video is not None:
        cmd += ["-i", str(pip_video)]

    has_pip = pip_video is not None and pip_config is not None
    parts: list[str] = []
    cur = "0:v:0"

    if highlight_events:
        out_lbl = "v_hl" if (zoom_events or has_pip) else "v_scene"
        parts.extend(build_highlight_filter(cur, out_lbl, width, height, highlight_events))
        cur = out_lbl
    if zoom_events:
        out_lbl = "v_zoom" if has_pip else "v_scene"
        parts.extend(build_zoom_filter(cur, out_lbl, width, height, zoom_events))
        cur = out_lbl
    if has_pip and pip_config is not None:
        parts.extend(build_pip_filter(cur, "1:v:0", "v_scene", width, height, pip_config))
        cur = "v_scene"

    cmd += [
        "-filter_complex",
        ";".join(parts),
        "-map",
        f"[{cur}]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out_path


def _stitch_scenes_xfade(
    scene_videos: list[Path],
    scene_durations: list[float],
    transitions: list[TransitionSpec],
    out_path: Path,
    *,
    width: int,
    height: int,
    fps: int,
    crf: int,
) -> tuple[Path, list[float]]:
    """Normalise scene streams and stitch them via compositor.build_xfade_filter."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")

    cmd: list[str] = ["ffmpeg", "-y"]
    norm_parts: list[str] = []
    scene_labels: list[str] = []
    for idx, video in enumerate(scene_videos):
        cmd += ["-i", str(video)]
        lbl = f"s{idx}"
        scene_labels.append(lbl)
        norm_parts.append(
            f"[{idx}:v:0]fps={fps},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"format=yuv420p,setpts=PTS-STARTPTS,settb=AVTB[{lbl}]"
        )

    xfade_parts, scene_starts = build_xfade_filter(scene_labels, scene_durations, transitions, "v_xfade")
    cmd += [
        "-filter_complex",
        ";".join(norm_parts + xfade_parts),
        "-map",
        "[v_xfade]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out_path, scene_starts


def _record_single_unit(
    unit_spec: dict[str, Any],
    raw_dir: Path,
    *,
    unit_name: str,
    out_dir: Path,
    width: int,
    height: int,
    fps: int,
    cli_width: int | None,
    cli_height: int | None,
    cli_fps: int | None,
    headed: bool,
    keep_tape: bool,
    step_clip_durations: dict[int, float] | None = None,
    pad_steps: bool = True,
    gap_ms: int = 250,
    step_starts_out: dict[int, float] | None = None,
    zoom_events_out: list[ZoomEvent] | None = None,
    highlight_events_out: list[HighlightEvent] | None = None,
) -> Path:
    mode = unit_spec.get("mode", "browser")
    if mode not in ("browser", "terminal"):
        raise ValueError(f"Unknown storyboard mode: {mode!r}")
    if mode == "browser":
        return _record_browser(
            unit_spec,
            raw_dir,
            width=width,
            height=height,
            headed=headed,
            step_clip_durations=step_clip_durations,
            pad_steps=pad_steps,
            gap_ms=gap_ms,
            step_starts_out=step_starts_out,
            zoom_events_out=zoom_events_out,
            highlight_events_out=highlight_events_out,
        )
    return _record_terminal(
        unit_spec,
        raw_dir,
        name=unit_name,
        out_dir=out_dir,
        width=cli_width,
        height=cli_height,
        fps=cli_fps,
        keep_tape=keep_tape,
        step_clip_durations=step_clip_durations,
        pad_steps=pad_steps,
        gap_ms=gap_ms,
        step_starts_out=step_starts_out,
        zoom_events_out=zoom_events_out,
        highlight_events_out=highlight_events_out,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a scripted browser or terminal product demo video.")
    parser.add_argument("storyboard", type=Path, help="Path to storyboard JSON file")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory for mp4/webm/png")
    parser.add_argument("--name", default=None, help="Output filename stem (defaults to storyboard name)")
    parser.add_argument("--width", type=int, default=None, help="Viewport width (default 1280)")
    parser.add_argument("--height", type=int, default=None, help="Viewport height (default 720)")
    parser.add_argument("--fps", type=int, default=None, help="Output video FPS (default 30)")
    parser.add_argument("--crf", type=int, default=22, help="H.264 CRF quality (default 22)")
    parser.add_argument("--poster-time", type=float, default=None, help="Poster frame timestamp in seconds")
    parser.add_argument("--no-webm", action="store_true", help="Skip WebM transcode")
    parser.add_argument(
        "--no-frame",
        action="store_true",
        help="Disable default ray.so presentation framing",
    )
    parser.add_argument("--headed", action="store_true", help="Show browser window while recording")
    parser.add_argument(
        "--keep-tape",
        action="store_true",
        help="Save generated VHS .tape file into --out-dir (terminal mode)",
    )
    parser.add_argument(
        "--plan-narration",
        "--plan-media",
        dest="plan_narration",
        action="store_true",
        help="Print narration and music synthesis manifest as JSON and exit without recording",
    )
    parser.add_argument(
        "--narration-dir",
        type=Path,
        default=None,
        help="Directory for cached narration audio clips (default: <out-dir>/.narration-cache)",
    )
    parser.add_argument(
        "--burn-captions",
        action="store_true",
        help="Burn synced captions into output videos using ffmpeg's subtitles filter",
    )
    args = parser.parse_args(argv)

    spec = json.loads(args.storyboard.read_text(encoding="utf-8"))
    narration_dir = (
        args.narration_dir if args.narration_dir is not None else args.out_dir / ".narration-cache"
    )
    if args.plan_narration:
        plan = _build_storyboard_plan(spec, narration_dir)
        print(json.dumps(plan, indent=2))
        return 0

    name = args.name or spec.get("name") or args.storyboard.stem
    term_spec = spec.get("terminal") if isinstance(spec.get("terminal"), dict) else {}
    width = int(args.width if args.width is not None else term_spec.get("width", spec.get("width", 1280)))
    height = int(args.height if args.height is not None else term_spec.get("height", spec.get("height", 720)))
    fps = int(args.fps if args.fps is not None else term_spec.get("fps", spec.get("fps", 30)))
    poster_time = float(args.poster_time if args.poster_time is not None else spec.get("poster_time", 1.5))
    frame_config = resolve_frame_config(spec.get("frame"), no_frame=args.no_frame)

    music = extract_music(spec)
    pad_steps, gap_ms, narration_volume = get_narration_options(spec)
    captions_cfg = spec.get("captions") if isinstance(spec.get("captions"), dict) else {}
    burn_captions = bool(args.burn_captions or captions_cfg.get("burn_in", False))
    caption_max_chars = captions_cfg.get("max_chars", 48)

    is_multi_scene = spec.get("scenes") is not None
    if is_multi_scene:
        raw_scenes = spec["scenes"]
        if not isinstance(raw_scenes, list) or not raw_scenes:
            print("error: storyboard has no scenes", file=sys.stderr)
            return 1
        scene_specs = [_build_scene_spec(spec, s, i) for i, s in enumerate(raw_scenes)]
        for idx, s_spec in enumerate(scene_specs):
            s_mode = s_spec.get("mode", "browser")
            if s_mode not in ("browser", "terminal"):
                raise ValueError(f"Unknown storyboard mode: {s_mode!r}")
            if not (s_spec.get("steps") or []):
                print(f"error: scene {idx} has no steps", file=sys.stderr)
                return 1
        per_scene_cues, global_cues = _extract_all_multi_scene_cues(spec, scene_specs)
        all_cues: list[NarrationCue] = [c for grp in per_scene_cues for c in grp] + global_cues
    else:
        mode = spec.get("mode", "browser")
        if mode not in ("browser", "terminal"):
            raise ValueError(f"Unknown storyboard mode: {mode!r}")
        steps = spec.get("steps") or []
        if not steps:
            print("error: storyboard has no steps", file=sys.stderr)
            return 1
        scene_specs = []
        per_scene_cues = []
        global_cues = []
        all_cues = extract_cues(spec)

    missing_cues = find_missing_clips(all_cues, narration_dir) if all_cues else []
    music_path: Path | None = None
    music_missing = False
    if music is not None:
        music_target, music_cached = resolve_cache_path(narration_dir, music.id)
        if music_cached:
            music_path = music_target
        else:
            music_missing = True
            music_path = music_target

    if missing_cues:
        print(
            format_missing_clips_error(
                missing_cues,
                storyboard=args.storyboard,
                narration_dir=narration_dir,
            ),
            file=sys.stderr,
        )
    if music is not None and music_missing and music_path is not None:
        print(
            format_missing_music_error(
                music,
                music_path,
                storyboard=args.storyboard,
                narration_dir=narration_dir,
            ),
            file=sys.stderr,
        )
    if missing_cues or music_missing:
        return 1

    music_track: dict[str, Any] | None = None
    if music is not None and music_path is not None:
        music_track = {
            "path": str(music_path),
            "volume": music.volume,
            "duck_db": music.duck_db,
            "fade_in": music.fade_in,
            "fade_out": music.fade_out,
        }

    with tempfile.TemporaryDirectory(prefix="product-demo-") as tmp:
        raw_dir = Path(tmp)
        combined_audio_tracks: list[dict[str, Any]] = list(spec.get("audio_tracks") or [])
        burn_captions_path: Path | None = None
        final_timed_cues: list[TimedNarrationCue] = []
        transcode_zoom_events: list[ZoomEvent] | None = None
        transcode_highlight_events: list[HighlightEvent] | None = None

        if is_multi_scene:
            scene_videos: list[Path] = []
            scene_local_timelines: list[list[TimedNarrationCue]] = []

            for idx, s_spec in enumerate(scene_specs):
                s_cues = per_scene_cues[idx]
                s_pad_steps, s_gap_ms, _ = get_narration_options(s_spec)
                s_resolved = (
                    resolve_narration_clips(s_cues, narration_dir, probe_duration=_probe_duration)
                    if s_cues
                    else []
                )
                s_clip_durations = {
                    rc.cue.step_index: rc.duration for rc in s_resolved if rc.cue.step_index is not None
                }

                s_step_starts: dict[int, float] = {}
                s_zooms: list[ZoomEvent] = []
                s_highlights: list[HighlightEvent] = []
                s_raw = _record_single_unit(
                    s_spec,
                    raw_dir,
                    unit_name=f"{name}_scene_{idx}",
                    out_dir=args.out_dir,
                    width=width,
                    height=height,
                    fps=fps,
                    cli_width=args.width,
                    cli_height=args.height,
                    cli_fps=args.fps,
                    headed=args.headed,
                    keep_tape=args.keep_tape,
                    step_clip_durations=s_clip_durations or None,
                    pad_steps=s_pad_steps,
                    gap_ms=s_gap_ms,
                    step_starts_out=s_step_starts,
                    zoom_events_out=s_zooms,
                    highlight_events_out=s_highlights,
                )

                pip_video: Path | None = None
                pip_config: PipConfig | None = None
                raw_pip = s_spec.get("pip")
                if isinstance(raw_pip, dict):
                    pip_config = _parse_pip_config(raw_pip)
                    pip_unit_spec = _build_scene_spec(s_spec, raw_pip, idx)
                    pip_unit_spec.pop("pip", None)
                    pip_unit_spec["name"] = f"{name}_scene_{idx}_pip"
                    pip_w = int(raw_pip.get("width", width))
                    pip_h = int(raw_pip.get("height", height))
                    pip_fps = int(raw_pip.get("fps", fps))
                    pip_video = _record_single_unit(
                        pip_unit_spec,
                        raw_dir,
                        unit_name=f"{name}_scene_{idx}_pip",
                        out_dir=args.out_dir,
                        width=pip_w,
                        height=pip_h,
                        fps=pip_fps,
                        cli_width=pip_w,
                        cli_height=pip_h,
                        cli_fps=pip_fps,
                        headed=args.headed,
                        keep_tape=False,
                    )

                if s_zooms or s_highlights or pip_video is not None:
                    scene_vid = _composite_scene_video(
                        s_raw,
                        raw_dir / f"scene_{idx}.mp4",
                        width=width,
                        height=height,
                        fps=fps,
                        crf=args.crf,
                        zoom_events=s_zooms,
                        highlight_events=s_highlights,
                        pip_video=pip_video,
                        pip_config=pip_config,
                    )
                else:
                    scene_vid = s_raw

                scene_videos.append(scene_vid)
                scene_local_timelines.append(
                    resolve_timeline(s_resolved, s_step_starts) if s_resolved else []
                )

            if len(scene_videos) == 1:
                raw_video = scene_videos[0]
                scene_starts = [0.0]
            else:
                scene_durations = [_probe_duration(vid) for vid in scene_videos]
                transitions = _resolve_scene_transitions(scene_specs)
                raw_video, scene_starts = _stitch_scenes_xfade(
                    scene_videos,
                    scene_durations,
                    transitions,
                    raw_dir / f"{name}.merged.mp4",
                    width=width,
                    height=height,
                    fps=fps,
                    crf=args.crf,
                )

            shifted: list[tuple[int, TimedNarrationCue]] = []
            order_idx = 0
            for scene_offset, local_cues in zip(scene_starts, scene_local_timelines, strict=True):
                for timed in local_cues:
                    shifted.append(
                        (
                            order_idx,
                            TimedNarrationCue(
                                cue=timed.cue,
                                path=timed.path,
                                start=timed.start + scene_offset,
                                duration=timed.duration,
                            ),
                        )
                    )
                    order_idx += 1

            if global_cues:
                resolved_global = resolve_narration_clips(
                    global_cues, narration_dir, probe_duration=_probe_duration
                )
                for timed in resolve_timeline(resolved_global, {}):
                    shifted.append((order_idx, timed))
                    order_idx += 1

            shifted.sort(key=lambda pair: (pair[1].start, pair[0]))
            final_timed_cues = [item for _, item in shifted]
        else:
            resolved_cues = (
                resolve_narration_clips(all_cues, narration_dir, probe_duration=_probe_duration)
                if all_cues
                else []
            )
            step_clip_durations = {
                rc.cue.step_index: rc.duration for rc in resolved_cues if rc.cue.step_index is not None
            }
            step_starts: dict[int, float] = {}
            zoom_events: list[ZoomEvent] = []
            highlight_events: list[HighlightEvent] = []
            raw_video = _record_single_unit(
                spec,
                raw_dir,
                unit_name=name,
                out_dir=args.out_dir,
                width=width,
                height=height,
                fps=fps,
                cli_width=args.width,
                cli_height=args.height,
                cli_fps=args.fps,
                headed=args.headed,
                keep_tape=args.keep_tape,
                step_clip_durations=step_clip_durations or None,
                pad_steps=pad_steps,
                gap_ms=gap_ms,
                step_starts_out=step_starts,
                zoom_events_out=zoom_events,
                highlight_events_out=highlight_events,
            )
            transcode_zoom_events = zoom_events or None
            transcode_highlight_events = highlight_events or None
            if resolved_cues:
                final_timed_cues = resolve_timeline(resolved_cues, step_starts)

        if final_timed_cues:
            for timed in final_timed_cues:
                combined_audio_tracks.append(
                    {
                        "path": str(timed.path),
                        "start": timed.start,
                        "volume": narration_volume,
                    }
                )
            caption_cues = [
                CaptionCue(start=timed.start, end=timed.end, text=timed.cue.text)
                for timed in final_timed_cues
            ]
            _vtt_path, srt_path = write_captions(
                caption_cues,
                args.out_dir,
                name,
                max_chars=caption_max_chars,
            )
            if burn_captions:
                burn_captions_path = srt_path

        _transcode(
            raw_video,
            args.out_dir,
            name,
            fps,
            args.crf,
            poster_time,
            not args.no_webm,
            audio_tracks=combined_audio_tracks or None,
            burn_captions_path=burn_captions_path,
            music_track=music_track,
            width=width,
            height=height,
            frame_config=frame_config,
            zoom_events=transcode_zoom_events,
            highlight_events=transcode_highlight_events,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
