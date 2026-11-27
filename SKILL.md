---
name: demo-builder
description: Record polished, deterministic browser and terminal product demo videos from declarative JSON storyboards using Playwright, vhs, fal.ai narration, and ffmpeg, producing web-optimised MP4, WebM and poster PNG assets for landing pages, docs and release notes. Use when the user asks to record a UI or terminal demo video, capture animated feature walkthroughs, or build video showcases for a website or README.
---

# Product Demo Recorder

Turns a declarative JSON storyboard into crisp, web-ready product demo videos (`<name>.mp4`, `<name>.webm`, and `<name>.png` poster, plus synced `<name>.vtt` and `<name>.srt` captions when narrated) using headless Chromium (Playwright), Charmbracelet `vhs`, `fal.ai` OAuth MCP narration, and `ffmpeg`.

- **Browser mode (`"mode": "browser"`, default):** runs deterministically against a live URL (local dev server or static file server) and injects a smooth animated cursor with click ripples so viewers can follow every interaction.
- **Terminal mode (`"mode": "terminal"`):** compiles the storyboard into a Charmbracelet `vhs` `.tape` script (defaulting to the Catppuccin Mocha theme) and renders a crisp terminal recording without Playwright.
- **Narration & captions:** supports timed TTS voiceover cues synthesised via the `fal.ai` OAuth MCP (zero API keys), automatically pads steps to match clip durations, muxes audio with `ffmpeg`, emits synced WebVTT/SRT sidecars, and optionally burns captions into the video.

## Prerequisites

- `ffmpeg` (and `ffprobe`) on `PATH`
- **Browser mode:** `uv` (runs Playwright in an ephemeral environment with `uv run --with playwright` — no repo dependencies needed) and Playwright Chromium installed once (`uv run --with playwright playwright install chromium`)
- **Terminal mode:** Charmbracelet `vhs` on `PATH` (e.g. `brew install vhs`) — Playwright is not required
- **Narration (optional):** the `fal.ai` OAuth MCP server connected in your agent client (no `FAL_KEY` or API keys required)

## Quick Run

Run [scripts/record_demo.py](./scripts/record_demo.py) (resolved relative to this skill's directory).

### Browser demo

```bash
uv run --with playwright python3 <this-skill-dir>/scripts/record_demo.py \
  <storyboard.json> \
  --out-dir <output-folder>
```

### Terminal demo (`vhs` mode, no Playwright needed)

```bash
python3 <this-skill-dir>/scripts/record_demo.py \
  <storyboard.json> \
  --out-dir <output-folder> \
  --keep-tape
```

### CLI Options

- `--name <stem>`: override output filename stem (defaults to storyboard `name` or filename stem)
- `--width <px>` / `--height <px>`: viewport or terminal size (default `1280x720`)
- `--fps <n>`: output framerate (default `30`)
- `--crf <n>`: H.264 quality factor (default `22`, lower is sharper/larger)
- `--no-webm`: skip VP9 WebM transcode (faster when only MP4 is needed)
- `--poster-time <sec>`: timestamp for poster PNG capture (default `1.5` or storyboard `poster_time`)
- `--headed`: run visible browser window for debugging (browser mode)
- `--keep-tape`: save the generated `vhs` `.tape` file into `--out-dir` (terminal mode)
- `--plan-narration`: print the SHA-256 cached narration synthesis manifest as JSON and exit without recording
- `--narration-dir <dir>`: directory for cached narration audio clips (default `<out-dir>/.narration-cache`)
- `--burn-captions`: burn synced captions into the output MP4/WebM using `ffmpeg`'s `subtitles` filter

## Narration Workflow (`fal.ai` OAuth MCP — Zero API Keys)

When a storyboard includes inline `step.narrate` cues or `narration.cues`, use this two-step workflow so narration clips are synthesised via OAuth MCP and cached by SHA-256 hash (`model`, `voice`, `speed`, `text`):

1. **Plan narration cues:** run `record_demo.py` with `--plan-narration` (no Playwright required):

```bash
python3 <this-skill-dir>/scripts/record_demo.py \
  <storyboard.json> \
  --out-dir <output-folder> \
  --plan-narration
```

2. **Synthesise missing clips via `fal.ai` OAuth MCP:** inspect the JSON manifest. For each entry in `cues` with `"cached": false`, call the `fal.ai` OAuth MCP TTS tool using the cue's `model`, `voice`, `speed`, and `text`, and save the downloaded audio to `target_path` (`.wav`, `.mp3`, `.m4a`, and `.ogg` are all supported). Cached cues are automatically skipped on subsequent runs.
3. **Record, mux, and caption:** re-run `record_demo.py` normally (add `--burn-captions` if you want burned-in subtitles). The recorder probes clip durations, pads steps so speech never overlaps the next step, muxes the audio tracks into `<name>.mp4` and `<name>.webm`, and writes synced `<name>.vtt` and `<name>.srt` sidecars.

## Storyboard Workflow

1. **Prepare the target:** for browser demos of static HTML, start a local HTTP server (e.g. `python3 -m http.server 8765 --directory <dir>`) rather than `file://` URLs so fonts, WebGL textures, and relative assets behave identically to production. For terminal demos, set `"mode": "terminal"` and configure `"terminal"` settings.
2. **Author a tight storyboard:** 8–18 seconds per clip works best for landing-page loops. See [references/storyboard-schema.md](./references/storyboard-schema.md) for browser actions, terminal (`vhs`) actions, narration, and caption fields.
3. **Pace for human eyes:** leave `600–1200 ms` pauses after major state transitions so viewers absorb what changed, and use smooth mouse movement (`steps: 20`) instead of teleporting clicks.
4. **Record and verify:** run `record_demo.py`, inspect the generated poster PNG, captions, and file sizes (aim for `< 3–5 MB` per MP4 for snappy GitHub Pages loads), and adjust `crf` or duration if needed.
5. **Embed cleanly in HTML:**

Silent autoplay loop:

```html
<video autoplay loop muted playsinline poster="assets/demos/hero.png">
  <source src="assets/demos/hero.webm" type="video/webm">
  <source src="assets/demos/hero.mp4" type="video/mp4">
</video>
```

Narrated demo with synced WebVTT captions:

```html
<video controls playsinline poster="assets/demos/cli-demo.png">
  <source src="assets/demos/cli-demo.webm" type="video/webm">
  <source src="assets/demos/cli-demo.mp4" type="video/mp4">
  <track kind="captions" src="assets/demos/cli-demo.vtt" srclang="en" label="English" default>
</video>
```

## References

- [references/storyboard-schema.md](./references/storyboard-schema.md): full storyboard JSON schema for browser and terminal modes, `vhs` actions, narration, captions, and working examples.
