#!/usr/bin/env python3
"""Record deterministic product demo videos from a JSON storyboard using Playwright + ffmpeg.

Run with:
    uv run --with playwright python3 record_demo.py storyboard.json --out-dir docs/assets/demos
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

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


def _center_of(page: Page, selector: str, timeout: int = 8000) -> tuple[float, float]:
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=timeout)
    box = loc.bounding_box()
    if not box:
        raise RuntimeError(f"Element {selector!r} has no bounding box")
    return box["x"] + box["width"] / 2.0, box["y"] + box["height"] / 2.0


def _run_steps(page: Page, steps: list[dict[str, Any]], show_cursor: bool) -> None:
    for idx, step in enumerate(steps, 1):
        action = step.get("action")
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

        after_ms = int(step.get("after_ms", 0))
        if after_ms > 0:
            page.wait_for_timeout(after_ms)


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


def _transcode(
    raw_webm: Path,
    out_dir: Path,
    name: str,
    fps: int,
    crf: int,
    poster_time: float,
    webm: bool,
    audio_tracks: list[dict[str, Any]] | None = None,
) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = out_dir / f"{name}.mp4"
    webm_path = out_dir / f"{name}.webm"
    poster_path = out_dir / f"{name}.png"

    tracks = audio_tracks or []
    cmd: list[str] = ["ffmpeg", "-y", "-i", str(raw_webm)]

    if tracks:
        vid_dur = _probe_duration(raw_webm)
        fade_start = max(0.0, vid_dur - 1.2)
        filter_parts: list[str] = []
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
        joined = "".join(mix_labels)
        filter_parts.append(
            f"{joined}amix=inputs={len(tracks)}:duration=longest:normalize=0,"
            f"atrim=0:{vid_dur:.3f},afade=t=out:st={fade_start:.3f}:d=1.2[aout]"
        )
        cmd += [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v:0",
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
                *(["-c:a", "libopus", "-b:a", "96k"] if tracks else ["-an"]),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a scripted browser product demo video.")
    parser.add_argument("storyboard", type=Path, help="Path to storyboard JSON file")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory for mp4/webm/png")
    parser.add_argument("--name", default=None, help="Output filename stem (defaults to storyboard name)")
    parser.add_argument("--width", type=int, default=None, help="Viewport width (default 1280)")
    parser.add_argument("--height", type=int, default=None, help="Viewport height (default 720)")
    parser.add_argument("--fps", type=int, default=30, help="Output video FPS (default 30)")
    parser.add_argument("--crf", type=int, default=22, help="H.264 CRF quality (default 22)")
    parser.add_argument("--poster-time", type=float, default=None, help="Poster frame timestamp in seconds")
    parser.add_argument("--no-webm", action="store_true", help="Skip WebM transcode")
    parser.add_argument("--headed", action="store_true", help="Show browser window while recording")
    args = parser.parse_args(argv)

    spec = json.loads(args.storyboard.read_text(encoding="utf-8"))
    name = args.name or spec.get("name") or args.storyboard.stem
    width = int(args.width or spec.get("width", 1280))
    height = int(args.height or spec.get("height", 720))
    poster_time = float(args.poster_time if args.poster_time is not None else spec.get("poster_time", 1.5))
    show_cursor = bool(spec.get("cursor", True))
    color_scheme = spec.get("color_scheme", "dark")
    steps = spec.get("steps") or []
    if not steps:
        print("error: storyboard has no steps", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="product-demo-") as tmp:
        raw_dir = Path(tmp)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=not args.headed,
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
            _run_steps(page, steps, show_cursor)
            video = page.video
            context.close()
            browser.close()
            if video is None:
                raise RuntimeError("Playwright produced no video")
            raw_webm = Path(video.path())

        if errors:
            print(f"warning: {len(errors)} pageerror(s) during recording: {errors}", file=sys.stderr)

        _transcode(
            raw_webm,
            args.out_dir,
            name,
            args.fps,
            args.crf,
            poster_time,
            not args.no_webm,
            audio_tracks=spec.get("audio_tracks"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
