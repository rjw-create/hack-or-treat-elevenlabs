"""Tests for evals.coverage. Run: python -m unittest discover -s evals -t ."""
import copy
import tempfile
import unittest
from pathlib import Path

from core.interface import load_json
from core.placeholders import DEFAULT_FIXTURE, generate
from evals import coverage


class Coverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = generate(DEFAULT_FIXTURE, Path(cls.tmp.name) / "placeholder")
        cls.script = load_json(cls.folder / "script.json")
        cls.segments = load_json(cls.folder / "segments.json")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def edited(self):
        return copy.deepcopy(self.segments)

    def test_placeholders_pass(self):
        self.assertEqual(coverage.check_lines(self.script, self.segments), [])
        self.assertEqual(coverage.check_stems(self.folder, self.segments), [])
        self.assertEqual(coverage.main([str(self.folder)]), 0)

    def test_missing_line(self):
        segs = self.edited()
        segs["segments"][0]["line_ids"].remove("s01-l002")
        self.assertIn("line s01-l002 is not in any dialogue segment", coverage.check_lines(self.script, segs))

    def test_repeated_line(self):
        segs = self.edited()
        segs["segments"][2]["line_ids"].insert(0, "s01-l003")
        self.assertIn("line s01-l003 is in 2 dialogue segments", coverage.check_lines(self.script, segs))

    def test_out_of_order(self):
        segs = self.edited()
        segs["segments"][0]["line_ids"] = ["s01-l002", "s01-l001", "s01-l003"]
        problems = coverage.check_lines(self.script, segs)
        self.assertIn("line s01-l001 plays after s01-l002 but comes before it in the script", problems)

    def test_missing_and_empty_stems(self):
        segs = self.edited()
        segs["segments"][0]["file"] = "stems/dialogue/nope.wav"
        empty = self.folder / "stems" / "sfx" / "empty.wav"
        empty.write_bytes(b"")
        segs["segments"][1]["file"] = "stems/sfx/empty.wav"
        segs["beds"][0]["file"] = "../outside.wav"
        problems = coverage.check_stems(self.folder, segs)
        self.assertIn("stem stems/dialogue/nope.wav is missing", problems)
        self.assertIn("stem stems/sfx/empty.wav is empty (0 bytes)", problems)
        self.assertTrue(any("outside the output folder" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
