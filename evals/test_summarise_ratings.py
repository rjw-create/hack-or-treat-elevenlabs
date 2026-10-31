"""Tests for evals.summarise_ratings. Run: python -m unittest discover -s evals -t ."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evals import summarise_ratings as sr

HEADER = ",".join(sr.COLUMNS)


def line(listener, practice="false", flat_first="true", clarity=(3, 4), immersion=(2, 5),
         preferred="full_cast", comment=""):
    return (f"{listener},2026-10-31T18:00:00.000Z,{practice},{flat_first},{clarity[0]},{clarity[1]},"
            f"{immersion[0]},{immersion[1]},{preferred},{comment}")


class Ratings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *lines):
        # The form exports CRLF line endings, so the tests do too.
        path = Path(self.tmp.name) / "listener_ratings.csv"
        path.write_bytes(("\r\n".join([HEADER, *lines]) + "\r\n").encode("utf-8"))
        return path

    def test_practice_rows_are_left_out(self):
        rows, practice = sr.load_ratings(self.write(line("L01"), line("T1", practice="true")))
        self.assertEqual([r["listener_id"] for r in rows], ["L01"])
        self.assertEqual(practice, 1)

    def test_quoted_comment_from_the_form_is_read(self):
        rows, _ = sr.load_ratings(self.write(line("L01", comment='"\'=SUM(A1), she said ""wow"""')))
        self.assertEqual(len(rows), 1)

    def test_bad_rating_names_the_line(self):
        with self.assertRaisesRegex(ValueError, "line 3 clarity_flat"):
            sr.load_ratings(self.write(line("L01"), line("L02", clarity=(6, 4))))

    def test_repeated_listener_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "appears twice"):
            sr.load_ratings(self.write(line("L01"), line("L01")))

    def test_wrong_columns_are_an_error(self):
        path = Path(self.tmp.name) / "bad.csv"
        path.write_text("listener_id,score\nL01,4\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "columns must be"):
            sr.load_ratings(path)

    def test_sign_test_matches_hand_calculation(self):
        self.assertAlmostEqual(sr.sign_test_p(8, 0), 2 / 2 ** 8)  # all 8 agree: 2 * (1/2)^8
        self.assertAlmostEqual(sr.sign_test_p(3, 3), 1.0)
        self.assertIsNone(sr.sign_test_p(0, 0))

    def test_summary_counts_and_order_check(self):
        rows, _ = sr.load_ratings(self.write(
            line("L01", flat_first="true", preferred="full_cast"),
            line("L02", flat_first="false", preferred="full_cast", clarity=(4, 4)),
            line("L03", flat_first="true", preferred="flat", immersion=(4, 3)),
            line("L04", preferred="no_preference"),
        ))
        s = sr.summarise(rows)
        self.assertEqual(s["preferred"], {"flat": 1, "full_cast": 2, "no_preference": 1})
        self.assertEqual(s["measures"]["clarity"]["same"], 1)
        self.assertEqual(s["measures"]["immersion"]["flat_better"], 1)
        # L02 heard full cast first and chose it; L03 heard flat first and chose it; L01 chose the second clip.
        self.assertEqual((s["chose_first_played"], s["chose"]), (2, 3))

    def test_report_always_has_limits_and_flags_loudness_gap(self):
        rows, _ = sr.load_ratings(self.write(line("L01")))
        clips = {"flat": {"file": "flat.mp3", "duration_s": 18.35, "lufs": -18.0},
                 "full cast excerpt": {"file": "excerpt.mp3", "duration_s": 19.85, "lufs": -15.0}}
        report = sr.render(sr.summarise(rows), 0, "listener_ratings.csv", clips)
        self.assertIn("## Limits", report)
        self.assertIn("Only 1 listener(s)", report)
        self.assertIn("+3.0 LU", report)
        self.assertIn("outside the 1 LU match", report)

    def test_cli_refuses_a_file_with_only_practice_rows(self):
        self.assertEqual(sr.main([str(self.write(line("T1", practice="true")))]), 1)

    def test_cli_writes_the_summary(self):
        out = Path(self.tmp.name) / "summary.md"
        with mock.patch("evals.summarise_ratings.loudness_lufs", return_value=None):
            self.assertEqual(sr.main([str(self.write(line("L01"))), "--out", str(out)]), 0)
        self.assertIn("Loudness match between the two clips was not checked", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
