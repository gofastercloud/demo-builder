---
name: demo-builder
description: Record polished, deterministic browser and terminal product demo videos from declarative JSON storyboards using Playwright, vhs, fal.ai narration, and ffmpeg, producing web-optimised MP4, WebM and poster PNG assets for landing pages, docs and release notes. Use when the user asks to record a UI or terminal demo video, capture animated feature walkthroughs, or build video showcases for a website or README.
---

# Product Demo Recorder

Turns a declarative JSON storyboard into crisp, web-ready product demo videos (`<name>.mp4`, `<name>.webm`, and `<name>.png` poster) using headless Chromium (Playwright) and `ffmpeg`.

Every recording runs deterministically against a live URL (local dev server or static file server), injects a smooth animated cursor with click ripples so viewers can follow every interaction, and outputs muted autoplay-friendly H.264 MP4 + VP9 WebM + poster PNG files ready to embed in HTML `<video>` tags.

## Prerequisites

- `uv` (runs Playwright in an ephemeral environment with `uv run --with playwright` — no repo dependencies needed)
- `ffmpeg` on `PATH`
- Playwright Chromium installed once: `uv run --with playwright playwright install chromium`

## Quick Run

Run [scripts/record_demo.py](./scripts/record_demo.py) (resolved relative to this skill's directory):

```bash
uv run --with playwright python3 <this-skill-dir>/scripts/record_demo.py \
  <storyboard.json> \
  --out-dir <output-folder>
```

Options:
- `--name <stem>`: override output filename stem (defaults to storyboard `name` or filename stem)
- `--width <px>` / `--height <px>`: viewport size (default `1280x720`)
- `--fps <n>`: output framerate (default `30`)
- `--crf <n>`: H.264 quality factor (default `22`, lower is sharper/larger)
- `--no-webm`: skip VP9 WebM transcode (faster when only MP4 is needed)
- `--poster-time <sec>`: timestamp for poster PNG capture (default `1.0` or storyboard `poster_time`)
- `--headed`: run visible browser window for debugging

## Storyboard Workflow

1. **Start a local HTTP server** if your target is static HTML (e.g. `python3 -m http.server 8765 --directory <dir>`). Avoid `file://` URLs so fonts, WebGL textures and relative assets behave identically to production.
2. **Author a tight storyboard** (8–18 seconds per clip works best for landing-page loops). See [references/storyboard-schema.md](./references/storyboard-schema.md) for all supported actions (`goto`, `wait_for`, `pause`, `move`, `click`, `dblclick`, `hover`, `type`, `press`, `drag`, `scroll`, `eval`).
3. **Pace for human eyes:** leave `600–1200 ms` pauses after major state transitions so viewers absorb what changed, and use smooth mouse movement (`steps: 20`) instead of teleporting clicks.
4. **Record and verify:** run `record_demo.py`, inspect the generated poster PNG and file sizes (aim for `< 3–5 MB` per MP4 for snappy GitHub Pages loads), and adjust `crf` or duration if needed.
5. **Embed cleanly in HTML:**

```html
<video autoplay loop muted playsinline poster="assets/demos/hero.png">
  <source src="assets/demos/hero.webm" type="video/webm">
  <source src="assets/demos/hero.mp4" type="video/mp4">
</video>
```

## References

- [references/storyboard-schema.md](./references/storyboard-schema.md): full storyboard JSON schema, action types, cursor styling and encoding tips.
