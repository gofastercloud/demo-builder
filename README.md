# demo-builder

A reusable, vendor-agnostic **Agent Skill** (Claude Code, Antigravity, Codex) for recording deterministic, web-optimised product demo videos (`MP4`, `WebM`, and poster `PNG`) from declarative JSON storyboards.

## Features

- **Browser recorder (`scripts/record_demo.py`)**: Playwright Chromium + `ffmpeg` with smooth animated cursor, click ripples, and deterministic pacing.
- **Planned (built via `groundhog-agency`)**:
  - **Terminal recorder (`vhs`)**: declarative JSON storyboard → `.tape` → Catppuccin Mocha terminal video.
  - **Automatic `fal.ai` narration**: timed TTS voiceover cues muxed with `ffmpeg` + optional captions (`.srt`/`.vtt`).

## Install as an Agent Skill

Symlink this repository into your agent skills directory (`~/.gemini/antigravity/skills/demo-builder`, `~/.claude/skills/demo-builder`, or `~/.codex/skills/demo-builder`).

## Develop

```nu
uv sync; make verify
```

MIT licensed.
