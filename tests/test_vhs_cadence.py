"""Offline unit tests for VHS typing cadence presets, overrides, quoting, and duration math."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import vhs_compiler  # noqa: E402

_TYPE_RE = re.compile(r"^Type(?:@(\d+)ms)? (.+)$")
_SLEEP_RE = re.compile(r"^Sleep (\d+)ms$")


def _extract_step_lines(tape: str) -> list[str]:
    """Return the compiled step directives after the VHS header blank line."""
    blocks = tape.strip().split("\n\n")
    return blocks[-1].splitlines() if len(blocks) > 1 else []


def _unquote_vhs(payload: str) -> str:
    """Validate VHS delimiter quoting and return the raw string payload."""
    assert len(payload) >= 2
    delim = payload[0]
    assert delim in ('"', "'", "`")
    assert payload[-1] == delim
    inner = payload[1:-1]
    assert delim not in inner
    return inner


def _reconstruct_typed_text(lines: list[str], *, trailing_enter: bool = False) -> str:
    """Reconstruct exact typed text from emitted Type and Enter directives."""
    parts: list[str] = []
    for line in lines:
        m = _TYPE_RE.match(line)
        if m:
            parts.append(_unquote_vhs(m.group(2)))
        elif line == "Enter":
            parts.append("\n")
    result = "".join(parts)
    if trailing_enter:
        assert result.endswith("\n")
        return result[:-1]
    return result


def _sum_emitted_duration_ms(lines: list[str], default_typing_ms: float) -> float:
    """Compute exact duration in ms directly from emitted VHS directives."""
    total = 0.0
    for line in lines:
        m_type = _TYPE_RE.match(line)
        if m_type:
            ms = float(m_type.group(1)) if m_type.group(1) is not None else default_typing_ms
            total += len(_unquote_vhs(m_type.group(2))) * ms
            continue
        m_sleep = _SLEEP_RE.match(line)
        if m_sleep:
            total += float(m_sleep.group(1))
            continue
        if line == "Enter":
            total += default_typing_ms
    return total


class TestCadencePresets:
    """Verify each supported typing cadence preset."""

    def test_smooth_cadence_35ms_and_90ms_breath_pauses(self) -> None:
        cmd = "git status && git diff | head -n 5; echo done"
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "smooth"},
            "steps": [{"action": "type", "text": cmd, "enter": True}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)

        assert _reconstruct_typed_text(step_lines, trailing_enter=True) == cmd
        type_speeds = [int(m.group(1)) for line in step_lines if (m := _TYPE_RE.match(line)) and m.group(1)]
        assert type_speeds and all(ms == 35 for ms in type_speeds)
        # Three operators (&&, |, ;) followed by more text -> three 90ms breath pauses
        assert step_lines.count("Sleep 90ms") == 3

    def test_smooth_cadence_no_trailing_pause_at_end_of_line(self) -> None:
        cmd = "echo done;"
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "smooth"},
            "steps": [{"action": "type", "text": cmd}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)

        assert _reconstruct_typed_text(step_lines) == cmd
        assert "Sleep 90ms" not in step_lines

    def test_brisk_cadence_22ms_uniform(self) -> None:
        cmd = "uv run pytest -q && echo ok"
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "brisk"},
            "steps": [{"action": "type", "text": cmd, "enter": True}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)

        assert _reconstruct_typed_text(step_lines, trailing_enter=True) == cmd
        assert step_lines[0] == f'Type@22ms "{cmd}"'
        assert not any(line.startswith("Sleep ") for line in step_lines)

    def test_typewriter_cadence_55ms_uniform(self) -> None:
        cmd = "echo hello | cat"
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "typewriter"},
            "steps": [{"action": "type", "text": cmd, "enter": True}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)

        assert _reconstruct_typed_text(step_lines, trailing_enter=True) == cmd
        assert step_lines[0] == f'Type@55ms "{cmd}"'
        assert not any(line.startswith("Sleep ") for line in step_lines)

    def test_human_cadence_varied_30_to_65ms_with_punctuation_pauses(self) -> None:
        cmd = "curl -s https://example.com, | jq .status; echo ready"
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "human"},
            "steps": [{"action": "type", "text": cmd, "enter": True}],
        }
        tape_a = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        tape_b = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        # Deterministic output across runs
        assert tape_a == tape_b

        step_lines = _extract_step_lines(tape_a)
        assert _reconstruct_typed_text(step_lines, trailing_enter=True) == cmd

        type_speeds = [int(m.group(1)) for line in step_lines if (m := _TYPE_RE.match(line)) and m.group(1)]
        assert len(type_speeds) >= 4
        assert all(30 <= ms <= 65 for ms in type_speeds)
        assert len(set(type_speeds)) >= 2

        sleeps = [int(m.group(1)) for line in step_lines if (m := _SLEEP_RE.match(line))]
        assert len(sleeps) >= 3
        assert all(0 < ms <= 120 for ms in sleeps)


class TestCadenceOverrides:
    """Verify per-step cadence and speed override precedence."""

    def test_step_cadence_overrides_terminal_cadence(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "typewriter"},
            "steps": [
                {"action": "type", "text": "echo one"},
                {"action": "type", "text": "echo a && echo b", "cadence": "smooth"},
                {"action": "type", "text": "echo fast", "cadence": "brisk"},
            ],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)

        assert 'Type@55ms "echo one"' in step_lines
        assert 'Type@35ms "echo a &&"' in step_lines
        assert "Sleep 90ms" in step_lines
        assert 'Type@35ms " echo b"' in step_lines
        assert 'Type@22ms "echo fast"' in step_lines

    def test_step_speed_overrides_cadence_base_speed(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "smooth"},
            "steps": [
                {"action": "type", "text": "echo a && echo b", "speed": "18ms"},
                {"action": "type", "text": "echo slow", "cadence": "brisk", "speed": 70},
            ],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)

        # Smooth keeps its 90ms breath pause while honouring explicit 18ms typing speed
        assert 'Type@18ms "echo a &&"' in step_lines
        assert "Sleep 90ms" in step_lines
        assert 'Type@18ms " echo b"' in step_lines
        assert 'Type@70ms "echo slow"' in step_lines

    def test_step_speed_overrides_human_cadence_base_speed(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "steps": [
                {"action": "type", "text": "echo one two three four", "cadence": "human", "speed": "20ms"},
            ],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)
        speeds = [int(m.group(1)) for line in step_lines if (m := _TYPE_RE.match(line)) and m.group(1)]
        assert len(speeds) >= 4
        assert all(10 <= ms <= 30 for ms in speeds)
        assert len(set(speeds)) >= 2

    def test_step_cadence_none_falls_back_to_terminal_cadence(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "brisk"},
            "steps": [{"action": "type", "text": "echo hi", "cadence": None}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        assert 'Type@22ms "echo hi"' in _extract_step_lines(tape)


class TestCadenceQuotingAndNewlines:
    """Verify cadence emission never breaks VHS quoting or multi-line commands."""

    @pytest.mark.parametrize("cadence", ["smooth", "brisk", "human", "typewriter"])
    def test_quotes_and_multiline_preserved_for_all_presets(self, cadence: str) -> None:
        tricky = """echo "hello" && echo 'world' | printf `ok`; a"b'c`d\necho "line 2" | cat"""
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": cadence},
            "steps": [{"action": "type", "text": tricky, "enter": True}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)

        assert _reconstruct_typed_text(step_lines, trailing_enter=True) == tricky


class TestCadenceErrors:
    """Verify invalid cadence names raise ValueError."""

    def test_unknown_terminal_cadence_raises_value_error(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "turbo"},
            "steps": [{"action": "type", "text": "echo hi"}],
        }
        with pytest.raises(ValueError, match="cadence"):
            vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))

    def test_unknown_step_cadence_raises_value_error(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "steps": [{"action": "type", "text": "echo hi", "cadence": "robotic"}],
        }
        with pytest.raises(ValueError, match="cadence"):
            vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))

    def test_empty_or_non_string_cadence_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="cadence"):
            vhs_compiler.compile_tape(
                {"terminal": {"cadence": ""}, "steps": [{"action": "type", "text": "ls"}]},
                Path("/tmp/out.mp4"),
            )
        with pytest.raises(ValueError, match="cadence"):
            vhs_compiler.compile_tape(
                {"steps": [{"action": "type", "text": "ls", "cadence": 123}]},
                Path("/tmp/out.mp4"),
            )


class TestCadenceDurationAccounting:
    """Verify cumulative duration math includes cadence typing and breath pauses."""

    @pytest.mark.parametrize("cadence", ["smooth", "brisk", "human", "typewriter"])
    def test_step_start_matches_exact_emitted_directives(self, cadence: str) -> None:
        cmd = "git status && git diff | head -n 5; echo done"
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": cadence},
            "steps": [
                {"action": "type", "text": cmd, "enter": True, "after_ms": 150},
                {"action": "pause", "ms": 300},
            ],
        }
        tape, step_starts = vhs_compiler.compile_tape_with_timings(spec, Path("/tmp/out.mp4"))
        step_lines = _extract_step_lines(tape)

        # Last line is the pause step ("Sleep 300ms"); all preceding lines belong to step 0
        assert step_lines[-1] == "Sleep 300ms"
        step0_lines = step_lines[:-1]

        # Extract Set TypingSpeed from header to verify Enter duration
        header_match = re.search(r"Set TypingSpeed (\d+)ms", tape)
        assert header_match is not None
        header_typing_ms = float(header_match.group(1))

        expected_step0_ms = _sum_emitted_duration_ms(step0_lines, header_typing_ms)
        assert step_starts[0] == pytest.approx(0.0, abs=1e-6)
        assert step_starts[1] == pytest.approx(expected_step0_ms / 1000.0, abs=1e-6)

    def test_smooth_narration_padding_accounts_for_breath_pauses(self) -> None:
        # "a && b" = 6 chars * 35ms (210ms) + 1 breath pause (90ms) + Enter (35ms) = 335ms
        spec: dict[str, Any] = {
            "mode": "terminal",
            "terminal": {"cadence": "smooth"},
            "narration": {"pad_steps": True, "gap_ms": 250},
            "steps": [
                {"action": "type", "text": "a && b", "enter": True, "narrate": "Run both."},
                {"action": "pause", "ms": 100},
            ],
        }
        tape, step_starts = vhs_compiler.compile_tape_with_timings(
            spec,
            Path("/tmp/out.mp4"),
            step_durations={0: 1.0},
        )
        # Target = 1000ms + 250ms = 1250ms; step0 = 335ms -> padding = 915ms
        assert "Sleep 915ms" in tape
        assert step_starts[1] == pytest.approx(1.25, abs=1e-6)
