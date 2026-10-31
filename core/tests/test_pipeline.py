"""Offline tests for plan, cast, ledger and render. A fake client stands in for ElevenLabs, so no
credits, keys or network are used. Run: python -m unittest discover -s core/tests -t ."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core import cache, ledger
from core.cast import choose
from core.config import ADAPTATION_DIR
from core.interface import check_folder, check_segments, load_json, script_lines
from core.plan import MAX_SEGMENT_CHARS, MAX_SEGMENT_LINES, build_segments, scene_subset
from core.render import run

SCRIPT = load_json(ADAPTATION_DIR / "script.json")
VOICES = {"version": 1, "voices": {c["id"]: {"voice_id": f"v-{c['id']}", "source": "library", "label": c["id"]}
                                   for c in SCRIPT["characters"]}}


class FakeClient:
    """Mimics the SDK calls Core uses. Each paid call adds credits_per_call to the account usage."""

    def __init__(self, credits_per_call=10, remaining=9000):
        self.calls = []
        self.used = 0
        self.limit = remaining
        self.credits_per_call = credits_per_call
        self.user = SimpleNamespace(subscription=SimpleNamespace(get=self._sub))
        self.text_to_dialogue = SimpleNamespace(convert_with_timestamps=self._dialogue_ts,
                                                convert=self._bytes("flat"))
        self.text_to_sound_effects = SimpleNamespace(convert=self._bytes("sfx"))
        self.music = SimpleNamespace(compose=self._bytes("music"))

    def _sub(self):
        return SimpleNamespace(character_count=self.used, character_limit=self.limit)

    def _charge(self, name, kwargs):
        self.calls.append((name, kwargs))
        self.used += self.credits_per_call

    def _dialogue_ts(self, **kwargs):
        self._charge("dialogue", kwargs)
        segs = [SimpleNamespace(dialogue_input_index=i, start_time_seconds=i * 2.0, end_time_seconds=i * 2.0 + 1.5)
                for i in range(len(kwargs["inputs"]))]
        return SimpleNamespace(audio_base_64=base64.b64encode(b"fake-mp3").decode(), voice_segments=segs)

    def _bytes(self, name):
        def call(**kwargs):
            self._charge(name, kwargs)
            return iter([b"fake-", name.encode()])
        return call


class PlanTests(unittest.TestCase):
    def test_real_script_segments_are_small_and_valid(self):
        plan = build_segments(SCRIPT)
        self.assertEqual(check_segments(plan, SCRIPT), [])
        lines = {k: v[1] for k, v in script_lines(SCRIPT).items()}
        for seg in plan["segments"]:
            if seg["kind"] == "dialogue":
                self.assertLessEqual(len(seg["line_ids"]), MAX_SEGMENT_LINES)
                self.assertLessEqual(sum(len(lines[i]["text"]) for i in seg["line_ids"]), MAX_SEGMENT_CHARS)

    def test_every_sfx_cue_follows_its_line(self):
        plan = build_segments(SCRIPT)
        lines = {k: v[1] for k, v in script_lines(SCRIPT).items()}
        segs = plan["segments"]
        cues = [l["sfx_after"] for l in lines.values() if l.get("sfx_after")]
        self.assertEqual([s["cue"] for s in segs if s["kind"] == "sfx"], cues)
        for before, seg in zip(segs, segs[1:]):
            if seg["kind"] == "sfx":
                self.assertEqual(lines[before["line_ids"][-1]].get("sfx_after"), seg["cue"])

    def test_scene_preview_is_self_consistent(self):
        plan = build_segments(SCRIPT, {2})
        self.assertEqual(check_segments(plan, scene_subset(SCRIPT, {2})), [])
        self.assertNotIn("flat_clip", plan)


class CastTests(unittest.TestCase):
    def test_distinct_voices_and_gender_respected(self):
        library = [{"voice_id": f"m{i}", "name": f"Man {i}", "labels": {"gender": "male", "accent": "british",
                                                                         "age": "old" if i % 2 else "young"}}
                   for i in range(6)]
        library += [{"voice_id": "f0", "name": "Woman", "labels": {"gender": "female", "accent": "british", "age": "old"}}]
        picks = choose(library, [c["id"] for c in SCRIPT["characters"]])
        self.assertEqual(len({p["voice_id"] for p in picks.values()}), len(picks))
        self.assertEqual(picks["mrs-white"]["voice_id"], "f0")


class LedgerTests(unittest.TestCase):
    def test_unknown_price_is_a_pessimistic_probe_then_measured(self):
        est, basis = ledger.estimate("sfx", 30, {})
        self.assertEqual(est, ledger.UNKNOWN_PRICE_ALLOWANCE_CREDITS)
        self.assertTrue(basis.startswith("unknown"))
        prices = ledger.record_price({}, "sfx", 30, 120)
        self.assertEqual(ledger.estimate("sfx", 30, prices), (120, "measured"))

    def test_measured_dialogue_rate_replaces_assumption_and_never_drops(self):
        prices = {"dialogue_credits_per_char": 1.0, "dialogue_basis": "assumed"}
        prices = ledger.record_price(prices, "dialogue", 100, 80)  # cheaper than assumed: still adopted
        self.assertEqual(prices["dialogue_credits_per_char"], 0.8)
        prices = ledger.record_price(prices, "dialogue", 100, 50)  # later lower reading: keep the higher
        self.assertEqual(prices["dialogue_credits_per_char"], 0.8)

    def test_budget_guard_blocks_cap_and_reserve(self):
        with self.assertRaises(ledger.BudgetError):
            ledger.check_budget(ledger.SPEND_CAP_CREDITS - 10, 11)
        with self.assertRaises(ledger.BudgetError):
            ledger.check_budget(0, 600, account_remaining=ledger.RESERVE_CREDITS + 500)
        ledger.check_budget(0, 100, account_remaining=5000)  # fine

    def test_cache_hits_and_samples_cost_nothing(self):
        rows = [{"credits_actual": 40, "credits_estimated": 50}, {"credits_actual": None, "credits_estimated": 30},
                {"cache_hit": True, "credits_estimated": 99}, {"sample": True, "credits_estimated": 99}]
        self.assertEqual(ledger.credits_spent(rows), 70)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out = root / "output"
        self._old_cache = cache.config.CACHE_DIR
        cache.config.CACHE_DIR = root / "cache"
        self.prices = {"dialogue_credits_per_char": 1.0, "dialogue_basis": "assumed",
                       "sfx_credits_per_call": 20, "ambience_credits_per_call": 20, "music_credits_per_call": 200}

    def tearDown(self):
        cache.config.CACHE_DIR = self._old_cache
        self.tmp.cleanup()

    def _run(self, client, **kw):
        ledger.save_prices(self.out / "pricing.json", self.prices)
        return run(client, SCRIPT, VOICES, self.out, log=lambda *_: None, **kw)

    def test_scene_preview_renders_logs_and_passes_interface(self):
        client = FakeClient()
        rows = self._run(client, scenes={1})
        folder = self.out / "preview-s01"
        self.assertEqual(check_folder(folder), [])
        self.assertTrue(rows and all(not r["cache_hit"] for r in rows))
        self.assertTrue(all((self.out / r["output"]).exists() for r in rows))
        segs = load_json(folder / "segments.json")["segments"]
        first = next(s for s in segs if s["kind"] == "dialogue")
        self.assertEqual([t["line_id"] for t in first["line_times_ms"]], first["line_ids"])
        self.assertEqual(first["line_times_ms"][1], {"line_id": first["line_ids"][1], "start_ms": 2000, "end_ms": 3500})
        usage = ledger.read_usage(self.out / "usage.jsonl")
        self.assertEqual(len(usage), len(rows))
        self.assertTrue(all(r["credits_actual"] == 10 for r in usage))

    def test_second_run_is_all_cache_hits_and_free(self):
        self._run(FakeClient(), scenes={1})
        again = FakeClient()
        rows = self._run(again, scenes={1})
        self.assertEqual(again.calls, [])
        self.assertTrue(all(r["cache_hit"] and r["credits_estimated"] == 0 for r in rows))

    def test_full_run_reuses_preview_stems(self):
        self._run(FakeClient(), scenes={1})
        full = FakeClient()
        self._run(full)
        self.assertEqual(check_folder(self.out), [])
        # Scene 1's dialogue and SFX were cached by the preview; only scenes 2-3 cost again.
        self.assertFalse(any(str(c[1].get("inputs", [{}])[0].get("text", "")).startswith("Without, the night")
                             for c in full.calls))

    def test_budget_guard_stops_before_paying(self):
        client = FakeClient(remaining=ledger.RESERVE_CREDITS + 50)
        with self.assertRaises(ledger.BudgetError):
            self._run(client, scenes={1})
        self.assertEqual(client.calls, [])

    def test_dry_run_calls_nothing_and_writes_nothing(self):
        out_lines = []
        run(None, SCRIPT, VOICES, self.out, dry_run=True, log=out_lines.append)
        self.assertFalse(self.out.exists())
        self.assertIn("dry run:", out_lines[-1])

    def test_usage_features_match_proofs_report(self):
        from evals.credits import FEATURES as PROOF_FEATURES

        rows = self._run(FakeClient(), scenes={1})
        self.assertLessEqual({r["feature"] for r in rows}, set(PROOF_FEATURES))


if __name__ == "__main__":
    unittest.main()
