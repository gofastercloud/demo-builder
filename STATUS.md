# Status (in progress — 3/5 tickets shipped)

## Goal
Add `vhs` terminal recording mode (`mode: "terminal"`) and automatic `fal.ai` OAuth MCP narration with synced `.vtt`/`.srt` captions (plus opt-in burn-in) to `demo-builder` — Spec #2.

## Shipped
- #4 → PR #8 (merged): `scripts/captions.py`, `tests/test_captions.py`
- #3 → PR #9 (merged): `scripts/vhs_compiler.py`, `scripts/record_demo.py`, `tests/test_vhs.py`
- #5 → PR #10 (merged): `scripts/narration.py`, `scripts/record_demo.py`, `tests/test_narration.py`

## In flight
- None.

## Waiting on you
- Optional note: pre-existing `ruff check .` lint errors (`RUF007`, `B905`) exist in `.claude/hooks/gtq.py:258` on `main` (untouched per agency rules).

## Decisions
- Unified `scripts/record_demo.py` with `"mode": "browser" | "terminal"` and lazy Playwright import.
- `fal.ai` OAuth MCP handoff via `--plan-narration` JSON manifest and SHA-256 clip cache (no `FAL_KEY`).
- Both inline `step.narrate` (auto-timed/padded) and explicit `narration.cues`; `.vtt` + `.srt` default, opt-in `--burn-captions`.

## Next
- Run `/next` to dispatch `#6` (now unblocked):
  - #6 (M, unblocked) — Synced narration pacing, audio muxing & captions
  - #7 (S, blocked by #6) — Update `SKILL.md`, schema reference & `README.md`
