"""Tests for evals.audio and evals.audio_checks. Run: python -m unittest discover -s evals -t .

The MP3 test needs ffmpeg on PATH and is skipped without it.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.interface import load_json
from core.placeholders import DEFAULT_FIXTURE, generate, silence, tone, write_wav
from evals import audio, audio_checks


class Checks(unittest.TestCase):
    """Each test gets its own copy of the placeholders, then breaks one stem on purpose."""

    @classmethod
    def setUpClass(cls):
        # Generating placeholders in pure Python is slow, so do it once and copy the folder per test.
        cls.source_tmp = tempfile.TemporaryDirectory()
        cls.source = generate(DEFAULT_FIXTURE, Path(cls.source_tmp.name) / "placeholder")

    @classmethod
    def tearDownClass(cls):
        cls.source_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(shutil.copytree(self.source, Path(self.tmp.name) / "placeholder"))
        self.segments = load_json(self.folder / "segments.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_checks(self):
        results = audio_checks.measure_all(self.folder, self.segments)
        key, _ = audio_checks.loudness_key(results)
        audio_checks.flag_loudness(results, key)
        audio_checks.effective_gaps(results, self.segments)
        return results

    def replace(self, stem_id, samples):
        stem = next(s for s in self.segments["segments"] if s["id"] == stem_id)
        write_wav(self.folder / stem["file"], samples)

    def test_placeholders_have_no_errors_or_warnings(self):
        results = self.run_checks()
        self.assertEqual([r["errors"] + r["warnings"] for r in results.values() if r["errors"] or r["warnings"]], [])
        self.assertAlmostEqual(results["s01-d001"]["peak_dbfs"], -10.5, places=1)  # placeholder tone amplitude 0.3

    def test_clipping_is_an_error(self):
        self.replace("s01-x001", [0.2] * 1000 + [1.0] * 10 + [0.2] * 1000)
        self.assertTrue(any("clipped" in e for e in self.run_checks()["s01-x001"]["errors"]))

    def test_single_full_scale_peak_is_not_clipping(self):
        self.replace("s01-x001", [0.2] * 1000 + [1.0] + [0.2] * 1000)
        self.assertEqual(self.run_checks()["s01-x001"]["errors"], [])

    def test_silent_stem_is_an_error(self):
        self.replace("s02-d001", silence(2.0))
        self.assertTrue(any("silent" in e for e in self.run_checks()["s02-d001"]["errors"]))

    def test_quiet_dialogue_is_flagged_against_the_median(self):
        self.replace("s02-d001", tone(220, 3.0, 0.03))  # 20 dB below the other dialogue stems
        self.assertTrue(any("dialogue median" in w for w in self.run_checks()["s02-d001"]["warnings"]))

    def test_long_silence_inside_dialogue_is_flagged(self):
        self.replace("s02-d001", tone(220, 1.0, 0.3) + silence(3.0) + tone(220, 1.0, 0.3))
        self.assertTrue(any("silence inside" in w for w in self.run_checks()["s02-d001"]["warnings"]))

    def test_trailing_silence_stretches_the_gap(self):
        self.replace("s02-d001", tone(220, 1.0, 0.3) + silence(1.0))
        results = self.run_checks()
        gap = next(g for g in audio_checks.effective_gaps(results, self.segments) if g["from"] == "s02-d001")
        self.assertAlmostEqual(gap["effective_gap_ms"], 300 + 1000, delta=60)  # 50 ms windows
        self.assertTrue(any("stretches the gap" in w for w in results["s02-d001"]["warnings"]))

    def test_missing_stem_is_an_error(self):
        (self.folder / self.segments["segments"][0]["file"]).unlink()
        self.assertIn("missing", self.run_checks()["s01-d001"]["errors"])
        self.assertEqual(audio_checks.main([str(self.folder)]), 1)

    def test_without_ffmpeg_loudness_falls_back_to_labelled_rms(self):
        with mock.patch("evals.audio.shutil.which", return_value=None):
            results = self.run_checks()
            key, label = audio_checks.loudness_key(results)
        self.assertEqual(key, "rms_dbfs")
        self.assertIn("not LUFS", label)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe on PATH")
class Mp3(unittest.TestCase):
    """Real stems are MP3, so check the ffmpeg path against a WAV whose values are known."""

    def test_mp3_matches_its_wav_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav, mp3 = Path(tmp) / "tone.wav", Path(tmp) / "tone.mp3"
            write_wav(wav, tone(220, 3.0, 0.3))
            subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(wav), "-b:a", "128k", str(mp3)], check=True)
            # MP3 encoders pad the start and end, so allow a little extra length.
            self.assertAlmostEqual(audio.duration_s(mp3), 3.0, delta=0.1)
            m = audio.measure(mp3)
            self.assertAlmostEqual(m["peak_dbfs"], -10.5, delta=0.5)
            self.assertEqual(m["clip_runs"], 0)
            self.assertAlmostEqual(audio.loudness_lufs(mp3), audio.loudness_lufs(wav), delta=0.5)


if __name__ == "__main__":
    unittest.main()
