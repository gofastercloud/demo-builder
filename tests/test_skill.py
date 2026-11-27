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
        "--burn-captions",
        "fal.ai",
        '<track kind="captions"',
    ):
        assert token in text, f"Expected {token!r} in SKILL.md"


def test_storyboard_schema_exists_and_documents_modes_narration_captions() -> None:
    schema = ROOT / "references" / "storyboard-schema.md"
    assert schema.is_file()
    text = schema.read_text(encoding="utf-8")
    for token in ("steps", "mode", "terminal", "narration", "captions", "pad_steps", "burn_in", "max_chars"):
        assert token in text, f"Expected {token!r} in references/storyboard-schema.md"


def test_storyboard_schema_json_examples_are_valid() -> None:
    text = (ROOT / "references" / "storyboard-schema.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", text, flags=re.DOTALL)
    assert len(blocks) >= 2, "Expected at least terminal and narrated JSON examples"
    parsed = [json.loads(block) for block in blocks]
    assert any(spec.get("mode") == "terminal" for spec in parsed)
    assert any("narration" in spec for spec in parsed)


def test_readme_lists_terminal_and_narration_as_implemented() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Planned" not in text
    for token in ("vhs", "fal.ai", "captions"):
        assert token in text.lower(), f"Expected {token!r} in README.md"


def test_all_scripts_parse_cleanly() -> None:
    scripts = sorted((ROOT / "scripts").glob("*.py"))
    assert scripts, "Expected Python scripts under scripts/"
    for script in scripts:
        src = script.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(script))
        assert isinstance(tree, ast.Module)
