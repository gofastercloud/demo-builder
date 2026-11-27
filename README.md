# demo-builder

A reusable, vendor-agnostic **Agent Skill** (Claude Code, Antigravity, Codex) for recording studio-polished, deterministic, web-optimised product demo videos (`MP4`, `WebM`, and poster `PNG`) from declarative JSON storyboards.

## Features

- **2-pass Writer → Editor creative workflow**: [references/personae/writer.md](./references/personae/writer.md) turns a product brief into a hook/build/payoff storyboard JSON; [references/personae/editor.md](./references/personae/editor.md) audits the storyboard, poster, frames, and captions for pacing bloat, visual clutter, zoom framing, caption wrapping, and audio ducking balance before final render.
- **Browser & terminal recorders (`scripts/record_demo.py`, `scripts/vhs_compiler.py`)**: Playwright Chromium with smooth animated cursor and click ripples, plus Charmbracelet `vhs` terminal mode (Catppuccin Mocha default, `--keep-tape`, and realistic typing cadences: `smooth`, `brisk`, `human`, `typewriter`).
- **Studio polish compositor (`scripts/compositor.py`)**: default `ray.so`-style gradient presentation framing (`catppuccin`, `midnight`, `sunset`, `aurora`, optional macOS window bar, or `--no-frame`), synced camera zooms and spotlight/callout highlights, and multi-scene `xfade` transitions with Picture-in-Picture (`pip`) overlays.
- **`fal.ai` OAuth MCP narration, ducked music & captions (`scripts/narration.py`, `scripts/captions.py`)**: zero-API-key two-step media planning (`--plan-media` / `--plan-narration`), SHA-256 clip caching, automatic step padding, sidechain-ducked background music, synced `.vtt`/`.srt` caption sidecars, and optional `--burn-captions`.

## Install as an Agent Skill

Symlink this repository into your agent skills directory (`~/.gemini/antigravity/skills/demo-builder`, `~/.claude/skills/demo-builder`, or `~/.codex/skills/demo-builder`).

## Develop

```nu
uv sync; make verify
```

MIT licensed.
