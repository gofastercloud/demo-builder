"""Unit tests for WebVTT and SubRip caption generation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from captions import CaptionCue, render_srt, render_vtt, write_captions


def test_render_vtt_basic_formatting() -> None:
    cues = [
        CaptionCue(start=0.0, end=2.5, text="Welcome to the demo."),
        CaptionCue(start=3.125, end=6.0, text="Let us walk through the dashboard."),
    ]
    vtt = render_vtt(cues)
    assert vtt.startswith("WEBVTT\n\n")
    assert vtt == (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.500\n"
        "Welcome to the demo.\n\n"
        "00:00:03.125 --> 00:00:06.000\n"
        "Let us walk through the dashboard.\n"
    )


def test_render_srt_basic_formatting() -> None:
    cues = [
        CaptionCue(start=0.0, end=2.5, text="Welcome to the demo."),
        CaptionCue(start=3.125, end=6.0, text="Let us walk through the dashboard."),
    ]
    srt = render_srt(cues)
    assert srt == (
        "1\n"
        "00:00:00,000 --> 00:00:02,500\n"
        "Welcome to the demo.\n\n"
        "2\n"
        "00:00:03,125 --> 00:00:06,000\n"
        "Let us walk through the dashboard.\n"
    )


def test_timestamp_millisecond_rounding_and_rollover() -> None:
    cues = [
        CaptionCue(start=0.9999, end=59.9999, text="Second and minute rollover."),
        CaptionCue(start=3599.9999, end=3661.0046, text="Hour rollover and rounding."),
    ]
    vtt = render_vtt(cues)
    assert "00:00:01.000 --> 00:01:00.000" in vtt
    assert "01:00:00.000 --> 01:01:01.005" in vtt

    srt = render_srt(cues)
    assert "00:00:01,000 --> 00:01:00,000" in srt
    assert "01:00:00,000 --> 01:01:01,005" in srt


def test_line_wrapping_at_word_boundaries() -> None:
    text = "Click the deploy button to publish your application straight to production."
    cues = [CaptionCue(start=1.0, end=5.0, text=text)]

    vtt = render_vtt(cues, max_chars=24)
    cue_body = vtt.split("00:00:01.000 --> 00:00:05.000\n", 1)[1].strip()
    lines = cue_body.splitlines()
    assert len(lines) > 1
    assert all(len(line) <= 24 for line in lines)
    assert " ".join(lines) == text


def test_line_wrapping_preserves_long_single_word_without_dropping() -> None:
    long_url = "https://example.com/very/long/endpoint/path/for/demo"
    text = f"Open {long_url} now"
    cues = [CaptionCue(start=0.0, end=3.0, text=text)]

    vtt = render_vtt(cues, max_chars=20)
    cue_body = vtt.split("00:00:00.000 --> 00:00:03.000\n", 1)[1].strip()
    assert cue_body.split() == text.split()
    assert long_url in cue_body.splitlines()


def test_line_wrapping_can_be_disabled() -> None:
    text = "This is a deliberately long line that should not wrap when max_chars is None."
    cues = [CaptionCue(start=0.0, end=2.0, text=text)]
    vtt = render_vtt(cues, max_chars=None)
    assert f"\n{text}\n" in vtt


def test_overlap_clamping() -> None:
    cues = [
        CaptionCue(start=0.0, end=5.0, text="First cue overlaps second."),
        CaptionCue(start=3.25, end=7.5, text="Second cue overlaps third."),
        CaptionCue(start=6.0, end=8.0, text="Final cue."),
    ]
    vtt = render_vtt(cues)
    assert "00:00:00.000 --> 00:00:03.250" in vtt
    assert "00:00:03.250 --> 00:00:06.000" in vtt
    assert "00:00:06.000 --> 00:00:08.000" in vtt

    srt = render_srt(cues)
    assert "00:00:00,000 --> 00:00:03,250" in srt
    assert "00:00:03,250 --> 00:00:06,000" in srt
    assert "00:00:06,000 --> 00:00:08,000" in srt


def test_negative_timestamps_clamped_to_zero() -> None:
    cues = [
        CaptionCue(start=-2.5, end=-0.5, text="Both negative."),
        CaptionCue(start=-1.0, end=2.0, text="Negative start."),
    ]
    vtt = render_vtt(cues)
    assert "00:00:00.000 --> 00:00:00.000" in vtt
    assert "00:00:00.000 --> 00:00:02.000" in vtt


def test_empty_cue_list_produces_valid_empty_outputs() -> None:
    assert render_vtt([]) == "WEBVTT\n\n"
    assert render_srt([]) == ""


def test_invalid_max_chars_raises_value_error() -> None:
    cues = [CaptionCue(start=0.0, end=1.0, text="Hello")]
    with pytest.raises(ValueError, match="max_chars"):
        render_vtt(cues, max_chars=0)
    with pytest.raises(ValueError, match="max_chars"):
        render_srt(cues, max_chars=-5)


def test_write_captions_creates_vtt_and_srt_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "nested" / "captions"
    cues = [
        CaptionCue(start=0.0, end=1.5, text="Hello world."),
        CaptionCue(start=1.5, end=3.0, text="Goodbye world."),
    ]
    vtt_path, srt_path = write_captions(cues, out_dir, "product-demo", max_chars=48)

    assert vtt_path == out_dir / "product-demo.vtt"
    assert srt_path == out_dir / "product-demo.srt"
    assert vtt_path.is_file()
    assert srt_path.is_file()
    assert vtt_path.read_text(encoding="utf-8") == render_vtt(cues, max_chars=48)
    assert srt_path.read_text(encoding="utf-8") == render_srt(cues, max_chars=48)


def test_write_captions_empty_cues_writes_valid_empty_files(tmp_path: Path) -> None:
    vtt_path, srt_path = write_captions([], tmp_path, "empty-demo")
    assert vtt_path.read_text(encoding="utf-8") == "WEBVTT\n\n"
    assert srt_path.read_text(encoding="utf-8") == ""
