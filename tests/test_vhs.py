"""Offline unit tests for VHS terminal recording mode and .tape compilation."""

from __future__ import annotations

import builtins
import importlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import record_demo, vhs_compiler  # noqa: E402


class TestCompileTapeSettings:
    """Verify top-level/terminal settings and Catppuccin Mocha defaults."""

    def test_defaults_catppuccin_mocha(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "steps": [{"action": "type", "text": "echo hi", "enter": True}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/raw.mp4"))

        assert 'Output "/tmp/raw.mp4"' in tape
        assert 'Set Theme "Catppuccin Mocha"' in tape
        assert "Set Width 1280" in tape
        assert "Set Height 720" in tape
        assert "Set Framerate 30" in tape
        assert "Set FontSize 16" in tape
        assert "Set Padding 24" in tape
        assert "Set WindowBar Colorful" in tape
        assert "Set TypingSpeed 45ms" in tape

    def test_custom_top_level_and_terminal_settings(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "width": 1600,
            "height": 900,
            "fps": 60,
            "terminal": {
                "theme": "Dracula",
                "font_family": "JetBrains Mono",
                "font_size": 20,
                "padding": 32,
                "window_bar": "Rings",
                "typing_speed": "30ms",
                "shell": "zsh",
                "env": {"DEMO_ENV": "1", "TERM": "xterm-256color"},
                "cwd": "/tmp/my project",
            },
            "steps": [{"action": "enter"}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))

        assert "Set Width 1600" in tape
        assert "Set Height 900" in tape
        assert "Set Framerate 60" in tape
        assert 'Set Theme "Dracula"' in tape
        assert 'Set FontFamily "JetBrains Mono"' in tape
        assert "Set FontSize 20" in tape
        assert "Set Padding 32" in tape
        assert "Set WindowBar Rings" in tape
        assert "Set TypingSpeed 30ms" in tape
        assert 'Set Shell "zsh"' in tape
        assert 'Env DEMO_ENV "1"' in tape
        assert 'Env TERM "xterm-256color"' in tape
        # cwd emitted inside Hide/Show preamble
        assert "Hide\n" in tape
        assert "cd '/tmp/my project'" in tape
        assert "\nShow\n" in tape

    def test_theme_dict_inline_json(self) -> None:
        theme = {"name": "Custom", "background": "#1e1e2e", "foreground": "#cdd6f4"}
        spec: dict[str, Any] = {
            "mode": "terminal",
            "theme": theme,
            "steps": [{"action": "enter"}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        assert f"Set Theme {json.dumps(theme)}" in tape

    def test_cli_overrides_precedence(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "width": 1280,
            "height": 720,
            "fps": 30,
            "steps": [{"action": "enter"}],
        }
        tape = vhs_compiler.compile_tape(
            spec,
            Path("/tmp/out.mp4"),
            width=1920,
            height=1080,
            fps=60,
        )
        assert "Set Width 1920" in tape
        assert "Set Height 1080" in tape
        assert "Set Framerate 60" in tape

    def test_numeric_typing_speed_formatted_as_ms(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "typing_speed": 60,
            "steps": [{"action": "enter"}],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/out.mp4"))
        assert "Set TypingSpeed 60ms" in tape


class TestCompileTapeActions:
    """Verify all supported terminal step actions, escaping, and errors."""

    def test_all_actions_and_after_ms(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "steps": [
                {"action": "hide"},
                {"action": "type", "text": "export PS1='$ '", "enter": True},
                {"action": "show", "after_ms": 200},
                {"action": "type", "text": "ls -la", "speed": "25ms", "enter": True, "after_ms": 400},
                {"action": "pause", "ms": 750},
                {"action": "sleep", "ms": 500},
                {"action": "enter"},
                {"action": "key", "key": "Tab"},
                {"action": "key", "key": "Down", "count": 3},
                {"action": "key", "key": "Up", "count": 2},
                {"action": "key", "key": "Escape"},
                {"action": "key", "key": "Backspace", "count": 4},
                {"action": "ctrl", "key": "l"},
                {"action": "ctrl", "key": "c", "after_ms": 150},
                {"action": "wait"},
                {"action": "wait", "pattern": "ready>", "timeout": "5s"},
                {"action": "wait", "timeout": 3000},
            ],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/raw.mp4"))
        lines = tape.splitlines()

        assert "Hide" in lines
        assert "Type \"export PS1='$ '\"" in lines
        assert "Show" in lines
        assert "Sleep 200ms" in lines
        assert 'Type@25ms "ls -la"' in lines
        assert "Sleep 400ms" in lines
        assert "Sleep 750ms" in lines
        assert "Sleep 500ms" in lines
        assert "Enter" in lines
        assert "Tab" in lines
        assert "Down 3" in lines
        assert "Up 2" in lines
        assert "Escape" in lines
        assert "Backspace 4" in lines
        assert "Ctrl+L" in lines
        assert "Ctrl+C" in lines
        assert "Sleep 150ms" in lines
        assert "Wait" in lines
        assert "Wait@5s /ready>/" in lines
        assert "Wait@3000ms" in lines

    def test_quoting_and_escaping(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "steps": [
                {"action": "type", "text": 'echo "hello world"'},
                {"action": "type", "text": """echo "a" 'b'"""},
                {"action": "type", "text": """a"b'c`d"""},
                {"action": "wait", "pattern": "a/b/c"},
            ],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/raw.mp4"))
        lines = tape.splitlines()

        # Double quotes present -> wrapped in single quotes
        assert """Type 'echo "hello world"'""" in lines
        # Both single and double quotes present -> wrapped in backticks
        assert """Type `echo "a" 'b'`""" in lines
        # All three quote types present -> split safely across Type lines
        reconstructed = ""
        for line in lines:
            if line.startswith("Type ") and ("a" in line or "b" in line or "c" in line or "d" in line):
                if line in ("""Type 'echo "hello world"'""", """Type `echo "a" 'b'`"""):
                    continue
                payload = line[len("Type ") :]
                assert payload[0] == payload[-1]
                assert payload[0] not in payload[1:-1]
                reconstructed += payload[1:-1]
        assert reconstructed == """a"b'c`d"""
        # Slash in wait regex escaped
        assert r"Wait /a\/b\/c/" in lines

    def test_multiline_type_and_key_aliases(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "steps": [
                {"action": "type", "text": "line1\nline2"},
                {"action": "key", "key": "esc"},
                {"action": "key", "key": "tab", "count": 2},
            ],
        }
        tape = vhs_compiler.compile_tape(spec, Path("/tmp/raw.mp4"))
        lines = tape.splitlines()
        assert lines[-5:] == ['Type "line1"', "Enter", 'Type "line2"', "Escape", "Tab 2"]

    def test_unknown_action_raises_value_error(self) -> None:
        spec: dict[str, Any] = {
            "mode": "terminal",
            "steps": [{"action": "teleport", "target": "mars"}],
        }
        with pytest.raises(ValueError, match="Unknown terminal storyboard action"):
            vhs_compiler.compile_tape(spec, Path("/tmp/raw.mp4"))

    def test_missing_required_fields_raise_value_error(self) -> None:
        with pytest.raises(ValueError, match="text"):
            vhs_compiler.compile_tape({"steps": [{"action": "type"}]}, Path("/tmp/raw.mp4"))
        with pytest.raises(ValueError, match="key"):
            vhs_compiler.compile_tape({"steps": [{"action": "key"}]}, Path("/tmp/raw.mp4"))
        with pytest.raises(ValueError, match="key"):
            vhs_compiler.compile_tape({"steps": [{"action": "ctrl"}]}, Path("/tmp/raw.mp4"))


class TestLazyPlaywrightImport:
    """Ensure playwright is never imported at module load or during terminal mode."""

    def test_import_record_demo_without_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_import = builtins.__import__

        def block_playwright(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "playwright" or name.startswith("playwright."):
                raise ModuleNotFoundError("No module named 'playwright'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", block_playwright)
        monkeypatch.delitem(sys.modules, "scripts.record_demo", raising=False)
        monkeypatch.delitem(sys.modules, "playwright", raising=False)
        monkeypatch.delitem(sys.modules, "playwright.sync_api", raising=False)

        mod = importlib.import_module("scripts.record_demo")
        assert hasattr(mod, "main")

    def test_direct_script_invocation_imports_vhs_compiler(self) -> None:
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "record_demo.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "--keep-tape" in proc.stdout


class TestRecordDemoTerminalExecution:
    """Verify record_demo.py dispatch, missing vhs error, --keep-tape, and transcode."""

    def test_terminal_mode_runs_vhs_and_transcode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        storyboard = tmp_path / "cli.json"
        out_dir = tmp_path / "out"
        storyboard.write_text(
            json.dumps(
                {
                    "name": "cli-demo",
                    "mode": "terminal",
                    "steps": [
                        {"action": "type", "text": "echo hello", "enter": True},
                        {"action": "pause", "ms": 500},
                    ],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(record_demo.shutil, "which", lambda cmd: f"/usr/local/bin/{cmd}")

        vhs_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            vhs_calls.append(cmd)
            assert cmd[0] == "vhs"
            tape_file = Path(cmd[1])
            tape_text = tape_file.read_text(encoding="utf-8")
            # Parse Output "..." line and create the raw video file
            for line in tape_text.splitlines():
                if line.startswith("Output "):
                    raw_out = Path(line.split(" ", 1)[1].strip('"'))
                    raw_out.write_bytes(b"fake-video-bytes")
                    break
            return MagicMock(returncode=0)

        transcode_mock = MagicMock()
        monkeypatch.setattr(record_demo.subprocess, "run", fake_run)
        monkeypatch.setattr(record_demo, "_transcode", transcode_mock)

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir)])
        assert rc == 0
        assert len(vhs_calls) == 1
        assert transcode_mock.call_count == 1
        call_args = transcode_mock.call_args
        assert call_args.args[1] == out_dir
        assert call_args.args[2] == "cli-demo"
        assert not (out_dir / "cli-demo.tape").exists()

    def test_keep_tape_saves_tape_into_out_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        storyboard = tmp_path / "cli.json"
        out_dir = tmp_path / "out"
        storyboard.write_text(
            json.dumps(
                {
                    "name": "kept-demo",
                    "mode": "terminal",
                    "steps": [{"action": "type", "text": "pwd", "enter": True}],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(record_demo.shutil, "which", lambda cmd: f"/usr/local/bin/{cmd}")

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            tape_text = Path(cmd[1]).read_text(encoding="utf-8")
            for line in tape_text.splitlines():
                if line.startswith("Output "):
                    Path(line.split(" ", 1)[1].strip('"')).write_bytes(b"raw")
                    break
            return MagicMock(returncode=0)

        monkeypatch.setattr(record_demo.subprocess, "run", fake_run)
        monkeypatch.setattr(record_demo, "_transcode", MagicMock())

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir), "--keep-tape"])
        assert rc == 0
        saved_tape = out_dir / "kept-demo.tape"
        assert saved_tape.is_file()
        content = saved_tape.read_text(encoding="utf-8")
        assert 'Set Theme "Catppuccin Mocha"' in content
        assert 'Type "pwd"' in content

    def test_missing_vhs_fails_cleanly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        storyboard = tmp_path / "cli.json"
        out_dir = tmp_path / "out"
        storyboard.write_text(
            json.dumps(
                {
                    "mode": "terminal",
                    "steps": [{"action": "enter"}],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(record_demo.shutil, "which", lambda _cmd: None)

        with pytest.raises(RuntimeError, match="vhs not found on PATH"):
            record_demo.main([str(storyboard), "--out-dir", str(out_dir)])

    def test_vhs_producing_no_video_raises_runtime_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        storyboard = tmp_path / "cli.json"
        out_dir = tmp_path / "out"
        storyboard.write_text(
            json.dumps({"mode": "terminal", "steps": [{"action": "enter"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(record_demo.shutil, "which", lambda cmd: f"/usr/local/bin/{cmd}")
        monkeypatch.setattr(record_demo.subprocess, "run", lambda cmd, **kw: MagicMock(returncode=0))

        with pytest.raises(RuntimeError, match="vhs produced no video"):
            record_demo.main([str(storyboard), "--out-dir", str(out_dir)])

    def test_unknown_mode_raises_value_error(self, tmp_path: Path) -> None:
        storyboard = tmp_path / "bad.json"
        storyboard.write_text(
            json.dumps({"mode": "hologram", "steps": [{"action": "pause", "ms": 100}]}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Unknown storyboard mode"):
            record_demo.main([str(storyboard), "--out-dir", str(tmp_path / "out")])

    def test_browser_mode_default_dispatches_to_browser_recorder(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        storyboard = tmp_path / "web.json"
        out_dir = tmp_path / "out"
        storyboard.write_text(
            json.dumps({"steps": [{"action": "pause", "ms": 100}]}),
            encoding="utf-8",
        )

        browser_mock = MagicMock(return_value=tmp_path / "raw.webm")
        transcode_mock = MagicMock()
        monkeypatch.setattr(record_demo, "_record_browser", browser_mock)
        monkeypatch.setattr(record_demo, "_transcode", transcode_mock)

        rc = record_demo.main([str(storyboard), "--out-dir", str(out_dir)])
        assert rc == 0
        assert browser_mock.call_count == 1
        assert transcode_mock.call_count == 1
