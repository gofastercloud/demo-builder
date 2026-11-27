"""Baseline structural checks for the demo-builder Agent Skill."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_skill_frontmatter_present() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    assert "name:" in frontmatter
    assert "description:" in frontmatter


def test_storyboard_schema_exists() -> None:
    schema = ROOT / "references" / "storyboard-schema.md"
    assert schema.is_file()
    assert "steps" in schema.read_text(encoding="utf-8")


def test_record_demo_parses_cleanly() -> None:
    src = (ROOT / "scripts" / "record_demo.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert isinstance(tree, ast.Module)
