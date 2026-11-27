---
name: demo-builder
description: Record polished, deterministic browser and terminal product demo videos from declarative JSON storyboards using Playwright, vhs, fal.ai narration and music, and ffmpeg, producing web-optimised MP4, WebM and poster PNG assets for landing pages, docs and release notes. Use when the user asks to record a UI or terminal demo video, capture animated feature walkthroughs, or build video showcases for a website or README.
---

# Product Demo Recorder

Turns a declarative JSON storyboard into crisp, studio-polished product demo videos (`<name>.mp4`, `<name>.webm`, and `<name>.png` poster, plus synced `<name>.vtt` and `<name>.srt` captions when narrated) using headless Chromium (Playwright), Charmbracelet `vhs`, `fal.ai` OAuth MCP narration and background music, and `ffmpeg`.

- **Browser mode (`"mode": "browser"`, default):** runs deterministically against a live URL (local dev server or static file server) and injects a smooth animated cursor with click ripples so viewers can follow every interaction.
- **Terminal mode (`"mode": "terminal"`):** compiles the storyboard into a Charmbracelet `vhs` `.tape` script (defaulting to the Catppuccin Mocha theme with realistic typing cadences: `smooth`, `brisk`, `human`, `typewriter`) and renders a crisp terminal recording without Playwright.
- **Studio polish (`ffmpeg` compositor):** applies `ray.so`-style gradient presentation framing by default (`catppuccin`, `midnight`, `sunset`, `aurora`, or disabled via `--no-frame`), synced camera zooms and spotlight/callout highlights, and multi-scene `xfade` transitions with Picture-in-Picture (`pip`) overlays.
- **Narration, music & captions:** synthesises timed TTS voiceover cues and instrumental background music via the `fal.ai` OAuth MCP (zero API keys), pads steps to match clip durations, auto-ducks music beneath speech, emits synced WebVTT/SRT sidecars, and optionally burns captions into the video.

## Prerequisites

- `ffmpeg` (and `ffprobe`) on `PATH`
- **Browser mode:** `uv` (runs Playwright in an ephemeral environment with `uv run --with playwright` — no repo dependencies needed) and Playwright Chromium installed once (`uv run --with playwright playwright install chromium`)
- **Terminal mode:** Charmbracelet `vhs` on `PATH` (e.g. `brew install vhs`) — Playwright is not required
- **Narration & music (optional):** the `fal.ai` OAuth MCP server connected in your agent client (no `FAL_KEY` or API keys required)

## Creative & Production Workflow (2-Pass)

Follow this four-stage pipeline when producing a demo from a product feature or user brief:

1. **Writer pass ([references/personae/writer.md](./references/personae/writer.md)):** Adopt the Writer persona to draft a tight, story-driven storyboard JSON with hook/build/payoff pacing, narration cues, `frame` preset, `zoom`/`highlight` beats, `scenes`/`pip` structure, terminal `cadence`, and an instrumental `music` prompt.
2. **Editor pass ([references/personae/editor.md](./references/personae/editor.md)):** Adopt the Editor persona to audit the draft JSON for pacing bloat, visual clutter, zoom framing, caption line wrapping, and audio ducking balance, applying concrete tightening edits before synthesis.
3. **Media planning & synthesis (`--plan-media` via `fal.ai` OAuth MCP):** Run `record_demo.py --plan-media` (alias `--plan-narration`) to emit the SHA-256 synthesis manifest for both narration `cues` and `music`. For every entry with `"cached": false`, call the `fal.ai` OAuth MCP TTS or music tool and save the audio to `target_path`.
4. **Render & post-draft review (`record_demo.py`):** Run `record_demo.py` to record, composite framing/zooms/highlights/transitions/PiP, duck music, mux audio, and write `.vtt`/`.srt` captions. Inspect `<name>.png` poster, captions, and file sizes (aim for `< 3–5 MB` per MP4); run a quick Editor pass if anything needs tightening.

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
- `--no-frame`: disable the default `ray.so`-style gradient presentation frame
- `--poster-time <sec>`: timestamp for poster PNG capture (default `1.5` or storyboard `poster_time`)
- `--headed`: run visible browser window for debugging (browser mode)
- `--keep-tape`: save the generated `vhs` `.tape` file into `--out-dir` (terminal mode)
- `--plan-media` (alias `--plan-narration`): print the SHA-256 cached narration and music synthesis manifest as JSON and exit without recording
- `--narration-dir <dir>`: directory for cached narration and music audio clips (default `<out-dir>/.narration-cache`)
- `--burn-captions`: burn synced captions into the output MP4/WebM using `ffmpeg`'s `subtitles` filter

## Media Synthesis Workflow (`fal.ai` OAuth MCP — Zero API Keys)

When a storyboard includes inline `step.narrate` cues, `narration.cues`, or a top-level `music` track, use this two-step workflow so clips are synthesised via OAuth MCP and cached by SHA-256 hash:

1. **Plan media assets:** run `record_demo.py` with `--plan-media` (no Playwright required):

```bash
python3 <this-skill-dir>/scripts/record_demo.py \
  <storyboard.json> \
  --out-dir <output-folder> \
  --plan-media
```

2. **Synthesise missing clips via `fal.ai` OAuth MCP:** inspect the JSON manifest:
   - For each entry in `cues` with `"cached": false`, call the `fal.ai` OAuth MCP TTS tool using `model`, `voice`, `speed`, and `text`, and save the downloaded audio to `target_path` (`.wav`, `.mp3`, `.m4a`, and `.ogg` are all supported).
   - If `music` is non-null and `"cached": false`, call the `fal.ai` OAuth MCP music generation tool using `model`, `prompt`, and `duration_sec`, and save the track to `music.target_path`.
   - Cached entries are automatically skipped on subsequent runs.
3. **Record, composite, mux, and caption:** re-run `record_demo.py` normally (add `--burn-captions` for burned-in subtitles or `--no-frame` for raw unframed video). The recorder probes clip durations, pads steps so speech never overlaps, ducks background music beneath narration, muxes audio into `<name>.mp4` and `<name>.webm`, and writes synced `<name>.vtt` and `<name>.srt` sidecars.

## Target Preparation & Embedding

- **Browser demos of static HTML:** start a local HTTP server (e.g. `python3 -m http.server 8765 --directory <dir>`) rather than `file://` URLs so fonts, WebGL textures, and relative assets behave identically to production.
- **Embed cleanly in HTML:**

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

- [references/personae/writer.md](./references/personae/writer.md): Writer persona for turning product briefs into story-driven storyboard JSON.
- [references/personae/editor.md](./references/personae/editor.md): Editor persona for reviewing storyboard JSON, posters, frames, and captions before final render.
- [references/storyboard-schema.md](./references/storyboard-schema.md): full storyboard JSON schema for browser/terminal modes, `frame` presets, `zoom`/`highlight` effects, multi-scene `scenes`/`transition`/`pip`, terminal `cadence`, `narration`, `music`, `captions`, and working examples.
