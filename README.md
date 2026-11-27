# demo-builder

A reusable, vendor-agnostic **Agent Skill** (Claude Code, Antigravity, Codex) for recording deterministic, web-optimised product demo videos (`MP4`, `WebM`, and poster `PNG`) from declarative JSON storyboards.

## Features

- **Browser recorder (`scripts/record_demo.py`)**: Playwright Chromium + `ffmpeg` with smooth animated cursor, click ripples, and deterministic pacing.
- **Terminal recorder (`vhs` mode)**: declarative JSON storyboard → `.tape` (`scripts/vhs_compiler.py`) → Catppuccin Mocha terminal video with zero Playwright dependency and optional `--keep-tape`.
- **`fal.ai` OAuth MCP narration & captions**: zero-API-key two-step synthesis (`--plan-narration`), SHA-256 clip caching, automatic step padding, `ffmpeg` audio muxing, synced `.vtt`/`.srt` caption sidecars, and optional `--burn-captions`.

## Install as an Agent Skill

Symlink this repository into your agent skills directory (`~/.gemini/antigravity/skills/demo-builder`, `~/.claude/skills/demo-builder`, or `~/.codex/skills/demo-builder`).

## Develop

```nu
uv sync; make verify
```

MIT licensed.
