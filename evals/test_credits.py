"""Tests for evals.credits. Run: python -m unittest discover -s evals -t ."""
import json
import tempfile
import unittest
from pathlib import Path

from core.interface import load_json
from core.placeholders import DEFAULT_FIXTURE, generate
from evals import credits


def row(feature="dialogue", estimated=None, actual=None, cache_hit=False, **extra):
    return {"feature": feature, "credits_estimated": estimated, "credits_actual": actual,
            "cache_hit": cache_hit, "run_id": "r1", **extra}


class SampleRows(unittest.TestCase):
    def test_sample_rows_are_refused(self):
        with self.assertRaises(credits.SampleDataError):
            credits.summarise([row(estimated=10), row(estimated=5, sample=True)])

    def test_allow_sample_stamps_the_report(self):
        summary = credits.summarise([row(estimated=10, sample=True)], allow_sample=True)
        self.assertTrue(summary["sample"])
        self.assertIn("SAMPLE DATA", credits.render(summary, ".", 10_000, None, "n/a"))


class Accounting(unittest.TestCase):
    def test_actual_beats_estimated_and_cache_hits_cost_nothing(self):
        summary = credits.summarise([
            row(estimated=100, actual=120),
            row(estimated=50),
            row(estimated=50, cache_hit=True),
            row(feature="sfx"),
        ])
        dialogue = summary["by_feature"]["dialogue"]
        self.assertEqual(dialogue["actual_credits"], 120)
        self.assertEqual(dialogue["estimated_credits"], 50)
        self.assertEqual(dialogue["cache_hits"], 1)
        self.assertEqual(credits.credits_of(summary["total"]), 170)
        self.assertEqual(credits.basis_label(dialogue), "actual + estimated")

    def test_unknown_cost_is_called_a_lower_bound(self):
        summary = credits.summarise([row(feature="sfx")])
        self.assertIn("lower bound", credits.basis_label(summary["by_feature"]["sfx"]))

    def test_preview_spend_is_split_out(self):
        summary = credits.summarise([
            row(estimated=100, output="preview-s01/stems/dialogue/s01-d001.mp3"),
            row(estimated=300, output="stems/dialogue/s01-d001.mp3"),
        ])
        self.assertEqual(credits.credits_of(summary["preview"]), 100)
        self.assertEqual(credits.credits_of(summary["total"]), 400)
        self.assertIn("Of which previews", credits.render(summary, ".", 10_000, None, "n/a"))

    def test_unknown_feature_is_an_error(self):
        with self.assertRaises(ValueError):
            credits.summarise([row(feature="speech_to_text")])


class OnPlaceholders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = generate(DEFAULT_FIXTURE, Path(cls.tmp.name) / "placeholder")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_finished_audio_adds_segment_stems_and_gaps(self):
        segments = load_json(self.folder / "segments.json")
        audio_s, _ = credits.finished_audio_s(self.folder, segments)
        gaps_s = sum(s["gap_after_ms"] for s in segments["segments"]) / 1000
        self.assertGreater(audio_s, gaps_s)

    def test_placeholder_log_is_refused_by_the_cli(self):
        self.assertEqual(credits.main([str(self.folder)]), 1)

    def test_placeholder_log_reports_with_allow_sample(self):
        out = self.folder / "report.md"
        self.assertEqual(credits.main([str(self.folder), "--allow-sample", "--out", str(out)]), 0)
        self.assertIn("SAMPLE DATA", out.read_text(encoding="utf-8"))

    def test_report_works_before_segments_json_exists(self):
        # A one-scene preview can log spend before the full render writes segments.json.
        early = self.folder / "preview-only"
        early.mkdir()
        (early / "usage.jsonl").write_text(
            json.dumps(row(estimated=50, output="preview-s01/stems/dialogue/s01-d001.mp3")) + "\n", encoding="utf-8")
        out = early / "report.md"
        self.assertEqual(credits.main([str(early), "--out", str(out)]), 0)
        self.assertIn("no segments.json in this folder yet", out.read_text(encoding="utf-8"))

    def test_bad_json_line_is_reported(self):
        bad = self.folder / "bad-usage"
        bad.mkdir()
        (bad / "usage.jsonl").write_text(json.dumps(row(estimated=1)) + "\n{not json\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "line 2"):
            credits.load_usage(bad / "usage.jsonl")


if __name__ == "__main__":
    unittest.main()
