"""Tests for timestamp formatting and subtitle rendering."""

from __future__ import annotations

import pytest

from app.subtitles import (
    Cue,
    cues_from_segments,
    format_timestamp,
    merge_short_cues,
    render,
    to_markdown,
    to_srt,
    to_txt,
    to_vtt,
)


class TestFormatTimestamp:
    def test_zero(self):
        assert format_timestamp(0) == "00:00:00,000"

    def test_simple_seconds(self):
        assert format_timestamp(5.5) == "00:00:05,500"

    def test_minutes_and_hours(self):
        assert format_timestamp(3661.25) == "01:01:01,250"

    def test_vtt_uses_dot(self):
        assert format_timestamp(1.5, comma=False) == "00:00:01.500"

    def test_negative_clamps_to_zero(self):
        assert format_timestamp(-10) == "00:00:00,000"

    def test_nan_is_zero(self):
        assert format_timestamp(float("nan")) == "00:00:00,000"

    def test_hours_not_capped_at_24(self):
        # A 25-hour recording should read 25:00:00, not wrap to 01:00:00.
        assert format_timestamp(25 * 3600) == "25:00:00,000"

    def test_rounding_carries_into_seconds(self):
        # 0.9996 rounds to 1000ms, which must become 1s not 0.1000s.
        assert format_timestamp(0.9996) == "00:00:01,000"


class TestSrt:
    def test_basic_block(self):
        out = to_srt([Cue(0.0, 1.5, "Hello there")])
        assert out == "1\n00:00:00,000 --> 00:00:01,500\nHello there\n"

    def test_numbering_is_sequential(self):
        cues = [Cue(0, 1, "one"), Cue(1, 2, "two"), Cue(2, 3, "three")]
        out = to_srt(cues)
        assert out.startswith("1\n")
        assert "\n2\n" in out
        assert "\n3\n" in out

    def test_blank_text_is_skipped(self):
        out = to_srt([Cue(0, 1, "real"), Cue(1, 2, "   ")])
        assert "real" in out
        assert out.count("-->") == 1

    def test_empty_input(self):
        assert to_srt([]) == ""


class TestVtt:
    def test_has_header(self):
        out = to_vtt([Cue(0, 1, "hi")])
        assert out.startswith("WEBVTT")

    def test_uses_dot_separator(self):
        out = to_vtt([Cue(1.5, 2.5, "hi")])
        assert "00:00:01.500 --> 00:00:02.500" in out


class TestTxt:
    def test_joins_without_timestamps(self):
        out = to_txt([Cue(0, 1, "one"), Cue(1, 2, "two")])
        assert out.strip() == "one two"

    def test_with_timestamps(self):
        out = to_txt([Cue(65, 70, "later")], timestamps=True)
        assert out.strip() == "[01:05] later"


class TestMarkdown:
    def test_has_title_and_timestamps(self):
        out = to_markdown([Cue(30, 35, "text here")], title="My Talk")
        assert out.startswith("# My Talk")
        assert "**00:30** — text here" in out


class TestMergeShortCues:
    def test_short_cue_is_extended(self):
        cues = [Cue(0.0, 0.2, "quick"), Cue(5.0, 6.0, "next")]
        merged = merge_short_cues(cues, min_duration=1.0)
        assert merged[0].end == pytest.approx(1.0)

    def test_never_overlaps_next_cue(self):
        cues = [Cue(0.0, 0.2, "quick"), Cue(0.5, 1.5, "next")]
        merged = merge_short_cues(cues, min_duration=1.0)
        assert merged[0].end <= 0.5

    def test_long_cue_untouched(self):
        cues = [Cue(0.0, 3.0, "long enough")]
        merged = merge_short_cues(cues, min_duration=1.0)
        assert merged[0].end == 3.0


class TestCuesFromSegments:
    def test_adapts_objects_with_attributes(self):
        class Seg:
            start = 1.0
            end = 2.0
            text = "hello"

        cues = cues_from_segments([Seg()])
        assert cues[0].start == 1.0
        assert cues[0].text == "hello"

    def test_end_before_start_is_repaired(self):
        class Seg:
            start = 5.0
            end = 2.0
            text = "backwards"

        cues = cues_from_segments([Seg()])
        assert cues[0].end == 5.0


class TestRender:
    @pytest.mark.parametrize("fmt", ["txt", "srt", "vtt", "md", "markdown"])
    def test_all_formats_work(self, fmt):
        out = render([Cue(0, 1, "hello")], fmt)
        assert "hello" in out

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="unsupported format"):
            render([Cue(0, 1, "x")], "docx")

    def test_case_insensitive(self):
        assert "hello" in render([Cue(0, 1, "hello")], "SRT")
