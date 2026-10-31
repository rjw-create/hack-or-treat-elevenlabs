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

    def with_sfx_after(self, line_id):
        script = copy.deepcopy(self.script)
        for scene in script["scenes"]:
            for line in scene["lines"]:
                if line["id"] == line_id:
                    line["sfx_after"] = "a log shifts in the fireplace"
        return script

    def test_sfx_after_followed_by_sfx_passes(self):
        # In the sample, s01-l003 ends segment s01-d001, which is followed by sfx s01-x001.
        self.assertEqual(coverage.check_sfx_after(self.with_sfx_after("s01-l003"), self.segments), [])

    def test_sfx_after_mid_segment_is_reported(self):
        problems = coverage.check_sfx_after(self.with_sfx_after("s01-l002"), self.segments)
        self.assertEqual(problems, ["line s01-l002 has sfx_after but is not the last line of segment s01-d001"])

    def test_sfx_after_without_following_sfx_is_reported(self):
        # s01-l005 ends s01-d002, which is followed by dialogue s02-d001.
        problems = coverage.check_sfx_after(self.with_sfx_after("s01-l005"), self.segments)
        self.assertEqual(problems, ["line s01-l005 has sfx_after but segment s01-d002 is not followed by an sfx segment"])

    def test_sfx_after_on_the_final_line_is_reported(self):
        problems = coverage.check_sfx_after(self.with_sfx_after("s02-l003"), self.segments)
        self.assertEqual(len(problems), 1)

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
