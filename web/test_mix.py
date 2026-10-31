"""Tests for the mixer's timing rules. No ffmpeg needed. Run: python -m unittest web.test_mix"""
import unittest

from core.interface import load_json
from core.placeholders import DEFAULT_FIXTURE
from web.mix import absolute_line_times, build_timeline, duck_gain_expr, filter_graph


def eval_gain(expr, t_s):
    """Evaluate the ffmpeg gain expression in Python, using the same clip/min meaning as ffmpeg."""
    def clip(x, low, high):
        return max(low, min(high, x))
    return eval(expr, {"__builtins__": {}}, {"clip": clip, "min": min, "t": t_s})


class TimelineTest(unittest.TestCase):
    def setUp(self):
        self.segments = load_json(DEFAULT_FIXTURE / "segments.json")
        self.segment_ms = {s["id"]: 1000 for s in self.segments["segments"]}
        self.bed_ms = {"s01-amb": 500, "s02-amb": 500, "theme": 300}
        self.timeline = build_timeline(self.segments, self.segment_ms, self.bed_ms, flat_ms=4000)
        self.by_id = {s["id"]: s for s in self.timeline["segments"]}

    def test_segments_follow_each_other_with_their_gaps(self):
        placed = self.timeline["segments"]
        for prev, seg, spec in zip(placed, placed[1:], self.segments["segments"]):
            self.assertEqual(seg["start_ms"], prev["end_ms"] + spec["gap_after_ms"])
        self.assertEqual(placed[0]["start_ms"], 0)

    def test_total_includes_every_stem_and_gap(self):
        expected_ms = sum(self.segment_ms.values()) + sum(s["gap_after_ms"] for s in self.segments["segments"])
        self.assertEqual(self.timeline["duration_ms"], expected_ms)

    def test_looping_bed_fills_its_whole_span(self):
        bed = next(b for b in self.timeline["beds"] if b["id"] == "s01-amb")
        self.assertEqual(bed["start_ms"], self.by_id["s01-d001"]["start_ms"])
        self.assertEqual(bed["end_ms"], self.by_id["s01-d002"]["end_ms"])

    def test_non_looping_bed_stops_when_its_file_ends(self):
        theme = next(b for b in self.timeline["beds"] if b["id"] == "theme")
        self.assertEqual(theme["end_ms"] - theme["start_ms"], 300)

    def test_chapters_start_at_their_segment(self):
        part_two = self.timeline["chapters"][1]
        self.assertEqual(part_two["start_ms"], self.by_id["s02-d001"]["start_ms"])

    def test_compare_covers_the_lines_of_the_flat_clip(self):
        compare = self.timeline["compare"]
        self.assertEqual(compare["full_start_ms"], self.by_id["s01-d001"]["start_ms"])
        self.assertEqual(compare["full_end_ms"], self.by_id["s01-d002"]["end_ms"])
        self.assertEqual(compare["excerpt_file"], "excerpt.mp3")

    def test_no_compare_without_a_flat_clip(self):
        self.assertIsNone(build_timeline(self.segments, self.segment_ms, self.bed_ms)["compare"])

    def test_graph_has_one_input_per_stem_and_ducks_only_ducked_beds(self):
        inputs, graph = filter_graph(self.timeline)
        self.assertEqual(len(inputs), len(self.segments["segments"]) + len(self.segments["beds"]))
        self.assertEqual(graph.count("eval=frame"), 1)  # only "theme" has duck_under_dialogue


class LineTimesTest(unittest.TestCase):
    SEG = {"id": "s01-d002", "line_ids": ["s01-l004", "s01-l005"]}

    def test_times_move_onto_the_drama_timeline(self):
        seg = dict(self.SEG, line_times_ms=[{"line_id": "s01-l004", "start_ms": 0, "end_ms": 2000},
                                            {"line_id": "s01-l005", "start_ms": 2100, "end_ms": 4000}])
        self.assertEqual(absolute_line_times(seg, 10000, 14500),
                         [{"line_id": "s01-l004", "start_ms": 10000, "end_ms": 12000},
                          {"line_id": "s01-l005", "start_ms": 12100, "end_ms": 14000}])

    def test_times_past_the_stem_end_are_clamped(self):
        seg = dict(self.SEG, line_times_ms=[{"line_id": "s01-l004", "start_ms": 0, "end_ms": 2000},
                                            {"line_id": "s01-l005", "start_ms": 2100, "end_ms": 4900}])
        self.assertEqual(absolute_line_times(seg, 10000, 14500)[1]["end_ms"], 14500)

    def test_missing_field_falls_back_to_the_segment(self):
        self.assertIsNone(absolute_line_times(self.SEG, 0, 5000))

    def test_one_untimed_line_falls_back_to_the_segment(self):
        seg = dict(self.SEG, line_times_ms=[{"line_id": "s01-l004", "start_ms": 0, "end_ms": 2000}])
        self.assertIsNone(absolute_line_times(seg, 0, 5000))

    def test_timeline_carries_line_times_only_where_given(self):
        segments = load_json(DEFAULT_FIXTURE / "segments.json")
        segments["segments"][2]["line_times_ms"] = [{"line_id": "s01-l004", "start_ms": 0, "end_ms": 400},
                                                    {"line_id": "s01-l005", "start_ms": 500, "end_ms": 900}]
        timeline = build_timeline(segments, {s["id"]: 1000 for s in segments["segments"]}, {"s01-amb": 1, "s02-amb": 1, "theme": 1})
        timed = [s["id"] for s in timeline["segments"] if s["line_times"]]
        self.assertEqual(timed, ["s01-d002"])


class DuckTest(unittest.TestCase):
    def test_no_windows_means_full_level(self):
        self.assertEqual(duck_gain_expr([]), "1")

    def test_gain_is_ducked_inside_and_full_well_outside(self):
        expr = duck_gain_expr([(2000, 4000)], duck_db=-10, ramp_ms=250)
        ducked = 10 ** (-10 / 20)
        self.assertAlmostEqual(eval_gain(expr, 3.0), ducked, places=3)
        self.assertAlmostEqual(eval_gain(expr, 2.0), ducked, places=3)  # already down when dialogue starts
        self.assertAlmostEqual(eval_gain(expr, 1.0), 1.0, places=3)
        self.assertAlmostEqual(eval_gain(expr, 5.0), 1.0, places=3)
        self.assertGreater(eval_gain(expr, 1.875), ducked)  # halfway down the ramp
        self.assertLess(eval_gain(expr, 1.875), 1.0)

    def test_close_windows_never_duck_deeper_than_the_set_amount(self):
        expr = duck_gain_expr([(1000, 2000), (2100, 3000)], duck_db=-10, ramp_ms=250)
        self.assertAlmostEqual(eval_gain(expr, 2.05), 10 ** (-10 / 20), places=3)


if __name__ == "__main__":
    unittest.main()
