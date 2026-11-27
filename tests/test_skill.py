"""Baseline structural checks for the demo-builder Agent Skill."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_skill_frontmatter_present() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    assert "name:" in frontmatter
    assert "description:" in frontmatter


def test_skill_documents_terminal_narration_and_captions() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    for token in (
        "vhs",
        "--keep-tape",
        "--plan-narration",
        "--plan-media",
        "--no-frame",
        "--burn-captions",
        "fal.ai",
        '<track kind="captions"',
        "references/personae/writer.md",
        "references/personae/editor.md",
    ):
        assert token in text, f"Expected {token!r} in SKILL.md"


def test_personae_files_exist_and_cover_creative_workflow() -> None:
    writer = ROOT / "references" / "personae" / "writer.md"
    editor = ROOT / "references" / "personae" / "editor.md"
    assert writer.is_file(), "Expected references/personae/writer.md to exist"
    assert editor.is_file(), "Expected references/personae/editor.md to exist"

    writer_text = writer.read_text(encoding="utf-8").lower()
    for token in ("hook", "payoff", "narration", "zoom", "highlight", "pip", "scene", "music"):
        assert token in writer_text, f"Expected {token!r} in references/personae/writer.md"

    editor_text = editor.read_text(encoding="utf-8").lower()
    for token in ("pacing", "clutter", "zoom", "caption", "ducking", "poster"):
        assert token in editor_text, f"Expected {token!r} in references/personae/editor.md"


def test_storyboard_schema_exists_and_documents_modes_narration_captions() -> None:
    schema = ROOT / "references" / "storyboard-schema.md"
    assert schema.is_file()
    text = schema.read_text(encoding="utf-8")
    for token in (
        "steps",
        "mode",
        "terminal",
        "narration",
        "captions",
        "pad_steps",
        "burn_in",
        "max_chars",
        "frame",
        "catppuccin",
        "zoom",
        "highlight",
        "scenes",
        "transition",
        "pip",
        "cadence",
        "music",
        "duck_db",
    ):
        assert token in text, f"Expected {token!r} in references/storyboard-schema.md"


def test_storyboard_schema_json_examples_are_valid() -> None:
    from scripts.compositor import resolve_frame_config
    from scripts.narration import extract_music
    from scripts.record_demo import _build_storyboard_plan, _parse_pip_config, _resolve_scene_transitions

    text = (ROOT / "references" / "storyboard-schema.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", text, flags=re.DOTALL)
    assert len(blocks) >= 3, "Expected terminal, narrated, and studio polish JSON examples"
    parsed = [json.loads(block) for block in blocks]
    assert any(spec.get("mode") == "terminal" for spec in parsed)
    assert any("narration" in spec for spec in parsed)
    studio_specs = [spec for spec in parsed if "scenes" in spec and "music" in spec and "frame" in spec]
    assert studio_specs, "Expected a multi-scene studio polish JSON example with frame and music"

    for spec in parsed:
        resolve_frame_config(spec.get("frame"))
        extract_music(spec)
        _build_storyboard_plan(spec, ROOT / ".narration-cache")
        if "scenes" in spec:
            _resolve_scene_transitions(spec["scenes"])
            for scene in spec["scenes"]:
                if isinstance(scene.get("pip"), dict):
                    _parse_pip_config(scene["pip"])


def test_readme_lists_terminal_and_narration_as_implemented() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Planned" not in text
    for token in ("vhs", "fal.ai", "captions", "ray.so", "writer", "editor", "music"):
        assert token in text.lower(), f"Expected {token!r} in README.md"


def test_all_scripts_parse_cleanly() -> None:
    scripts = sorted((ROOT / "scripts").glob("*.py"))
    assert scripts, "Expected Python scripts under scripts/"
    for script in scripts:
        src = script.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(script))
        assert isinstance(tree, ast.Module)
