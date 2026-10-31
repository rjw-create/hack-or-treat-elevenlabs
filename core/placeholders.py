"""Write placeholder stems that match the sample interface files, without calling any API.

Surface and Proof can build the mix and the checks against these before any credits are spent.
Only the standard library is used, so this runs in any worktree with plain Python 3.11.

Usage: python -m core.placeholders --out output/placeholder [--fixture core/fixtures/sample]
"""
import argparse
import array
import json
import math
import random
import shutil
import sys
import wave
from datetime import datetime, timedelta
from pathlib import Path

from core.interface import check_folder, load_json, script_lines, strip_tags

SAMPLE_RATE_HZ = 44100
CHARS_PER_SECOND = 15  # rough speaking rate, so placeholder lines last about as long as real ones
LINE_PAUSE_S = 0.15
FULL_SCALE = 32767  # 16-bit PCM peak
DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "sample"


def write_wav(path, samples):
    """Write mono 16-bit samples given as floats in -1..1."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * FULL_SCALE) for s in samples))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE_HZ)
        w.writeframes(pcm.tobytes())


def tone(freq_hz, duration_s, amplitude_fraction):
    n = int(duration_s * SAMPLE_RATE_HZ)
    fade_n = min(n // 2, int(0.02 * SAMPLE_RATE_HZ))  # 20 ms fades avoid clicks at the edges
    out = []
    for i in range(n):
        envelope = min(1.0, i / fade_n, (n - i) / fade_n) if fade_n else 1.0
        out.append(amplitude_fraction * envelope * math.sin(2 * math.pi * freq_hz * i / SAMPLE_RATE_HZ))
    return out


def noise(duration_s, amplitude_fraction, rng, decay_per_s=0.0):
    n = int(duration_s * SAMPLE_RATE_HZ)
    return [amplitude_fraction * math.exp(-decay_per_s * i / SAMPLE_RATE_HZ) * rng.uniform(-1, 1)
            for i in range(n)]


def silence(duration_s):
    return [0.0] * int(duration_s * SAMPLE_RATE_HZ)


def speech_like(lines, pitch_hz_by_speaker):
    """One tone per line at the speaker's pitch, as long as the line would take to say."""
    out = []
    for line in lines:
        duration_s = max(0.5, len(strip_tags(line["text"])) / CHARS_PER_SECOND)
        out += tone(pitch_hz_by_speaker[line["speaker"]], duration_s, 0.3) + silence(LINE_PAUSE_S)
    return out


def sample_usage(segments, lines, start):
    """A fake usage log in the documented shape, so Proof can build its accounting early."""
    rows = []
    t = start
    for seg in segments["segments"]:
        if seg["kind"] == "dialogue":
            chars = sum(len(lines[i][1]["text"]) for i in seg["line_ids"])
            row = {"feature": "dialogue", "endpoint": "text-to-dialogue", "model_id": "eleven_v4",
                   "chars": chars, "audio_ms": None, "credits_estimated": chars}
        else:
            row = {"feature": "sfx", "endpoint": "sound-generation", "model_id": None,
                   "chars": len(seg["cue"]), "audio_ms": 1000, "credits_estimated": None}
        t += timedelta(seconds=7)
        rows.append({"ts": t.isoformat(timespec="seconds"), "run_id": start.strftime("%Y-%m-%dT%H-%M-%S"),
                     **row, "credits_actual": None, "cache_hit": False,
                     "item_id": seg["id"], "output": seg["file"], "sample": True})
    return rows


def generate(fixture, out):
    fixture, out = Path(fixture), Path(out)
    errors = check_folder(fixture)
    if errors:
        raise ValueError("fixture does not match the interface:\n" + "\n".join(errors))

    script = load_json(fixture / "script.json")
    segments = load_json(fixture / "segments.json")
    lines = script_lines(script)
    # Spread speakers 40 Hz apart so each "voice" is easy to tell apart by ear.
    pitch_hz = {c["id"]: 140 + 40 * i for i, c in enumerate(script["characters"])}
    rng = random.Random(31)  # fixed seed: same placeholders on every machine

    for seg in segments["segments"]:
        if seg["kind"] == "dialogue":
            samples = speech_like([lines[i][1] for i in seg["line_ids"]], pitch_hz)
        else:
            samples = noise(0.8, 0.6, rng, decay_per_s=5.0)
        write_wav(out / seg["file"], samples)

    for bed in segments["beds"]:
        if bed["kind"] == "ambience":
            samples = noise(20.0, 0.15, rng)
        else:
            # Slow two-note chord, so ducking under dialogue is easy to hear.
            low, high = tone(110, 30.0, 0.25), tone(165, 30.0, 0.2)
            samples = [a + b for a, b in zip(low, high)]
        write_wav(out / bed["file"], samples)

    flat = segments["flat_clip"]
    flat_lines = [dict(lines[i][1], speaker=flat["voice"]) for i in flat["line_ids"]]
    write_wav(out / flat["file"], speech_like(flat_lines, pitch_hz))

    for name in ("script.json", "voices.json", "segments.json"):
        shutil.copyfile(fixture / name, out / name)
    start = datetime(2026, 10, 31, 14, 0, 0).astimezone()
    with open(out / "usage.jsonl", "w", encoding="utf-8") as f:
        for row in sample_usage(segments, lines, start):
            f.write(json.dumps(row) + "\n")
    return out


def main(argv):
    parser = argparse.ArgumentParser(description="Write placeholder Full Cast stems (no API calls).")
    parser.add_argument("--out", required=True, help="folder to write into, e.g. output/placeholder")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="folder with sample JSON files")
    args = parser.parse_args(argv)
    try:
        out = generate(args.fixture, args.out)
    except ValueError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    stems = sorted(p.relative_to(out).as_posix() for p in (out / "stems").rglob("*.wav"))
    print(f"wrote {len(stems)} placeholder stems to {out}")
    for s in stems:
        print(f"  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
