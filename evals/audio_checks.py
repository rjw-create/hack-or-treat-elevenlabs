"""Audio checks on every stem in segments.json: length, silence, clipping, loudness, effective gaps.

Errors (exit code 1): a stem is missing, unreadable, silent or clipped.
Warnings (reported, exit code 0): loudness far from the median for its kind, long silence inside a
dialogue stem, and silence at stem edges that stretches a planned gap.

Loudness is integrated LUFS from ffmpeg when it is installed; otherwise RMS dBFS, labelled as such.
Usage: python -m evals.audio_checks [output folder] [--out report.md]
"""
import argparse
import statistics
import subprocess
import sys
import wave
from pathlib import Path

from core.config import output_dir
from core.interface import load_json
from evals.audio import loudness_lufs, measure

SILENT_STEM_DBFS = -60.0  # a whole stem this quiet is almost certainly a failed render
FAR_FROM_MEDIAN_DB = 6.0  # wide enough for acted whispers and shouts, narrow enough to catch a stem at the wrong level
LONG_INNER_SILENCE_S = 2.0  # dead air this long inside a dialogue stem is likely a generation glitch
EXTRA_GAP_WARN_MS = 500  # edge silence adding more than this to a planned gap is audible as dead air


def stems(segments):
    """(id, kind, file) for every stem, segments first in play order."""
    out = [(s["id"], s["kind"], s["file"]) for s in segments["segments"]]
    out += [(b["id"], b["kind"], b["file"]) for b in segments.get("beds", [])]
    if segments.get("flat_clip"):
        out.append(("flat", "flat", segments["flat_clip"]["file"]))
    return out


def measure_all(folder, segments):
    results = {}
    for stem_id, kind, name in stems(segments):
        path = Path(folder) / name
        row = {"id": stem_id, "kind": kind, "file": name, "errors": [], "warnings": []}
        results[stem_id] = row
        if not path.is_file():
            row["errors"].append("missing")
            continue
        try:
            m = measure(path)
            lufs = loudness_lufs(path)
        except (subprocess.CalledProcessError, ValueError, wave.Error, EOFError) as e:
            row["errors"].append(f"unreadable ({e})")
            continue
        if m is None:
            row["errors"].append("not checked: needs ffmpeg")
            continue
        row.update(m, lufs=lufs)
        if m["rms_dbfs"] < SILENT_STEM_DBFS:
            row["errors"].append(f"silent (RMS {m['rms_dbfs']:.1f} dBFS)")
        if m["clip_runs"]:
            row["errors"].append(f"clipped ({m['clip_runs']} run(s) at full scale)")
        if kind == "dialogue" and m["longest_inner_silence_s"] > LONG_INNER_SILENCE_S:
            row["warnings"].append(f"{m['longest_inner_silence_s']:.2f} s of silence inside the stem")
    return results


def loudness_key(results):
    """Use LUFS only when every measured stem has it, so stems are never compared across two scales."""
    measured = [r for r in results.values() if "rms_dbfs" in r]
    if measured and all(r["lufs"] is not None for r in measured):
        return "lufs", "LUFS (integrated, EBU R128 via ffmpeg ebur128)"
    return "rms_dbfs", "RMS dBFS (not LUFS: ffmpeg was not available for every stem)"


def flag_loudness(results, key):
    """Compare each segment with the median of its own kind; beds and the flat clip are mixed separately."""
    medians = {}
    for kind in ("dialogue", "sfx"):
        values = [r[key] for r in results.values() if r["kind"] == kind and key in r and r[key] != float("-inf")]
        if len(values) < 2:
            continue
        medians[kind] = statistics.median(values)
        for r in results.values():
            if r["kind"] == kind and key in r and abs(r[key] - medians[kind]) > FAR_FROM_MEDIAN_DB:
                r["warnings"].append(f"{r[key] - medians[kind]:+.1f} dB from the {kind} median")
    return medians


def effective_gaps(results, segments):
    """Planned gap plus the silence at the end of one segment and the start of the next."""
    gaps = []
    segs = segments["segments"]
    for a, b in zip(segs, segs[1:]):
        ra, rb = results[a["id"]], results[b["id"]]
        if "trail_silence_s" not in ra or "lead_silence_s" not in rb:
            continue
        effective_ms = round(a["gap_after_ms"] + 1000 * (ra["trail_silence_s"] + rb["lead_silence_s"]))
        gaps.append({"from": a["id"], "to": b["id"], "gap_after_ms": a["gap_after_ms"], "effective_gap_ms": effective_ms})
        if effective_ms - a["gap_after_ms"] > EXTRA_GAP_WARN_MS:
            ra["warnings"].append(f"edge silence stretches the gap to {b['id']} from "
                                  f"{a['gap_after_ms']} ms to {effective_ms} ms")
    return gaps


def fmt(value, digits=1):
    return "-" if value is None else f"{value:.{digits}f}"


def render(folder, results, key, label, medians, gaps, sample):
    out = ["# Audio checks", ""]
    if sample:
        out += ["**PLACEHOLDER STEMS: this folder's usage log is sample data, so these are test tones, not real audio.**", ""]
    out += [f"Folder: `{Path(folder).as_posix()}`. Loudness column: {label}.", ""]
    out += ["| Stem | Kind | duration_s | Loudness | Peak dBFS | Lead / trail silence_s | Problems |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results.values():
        problems = "; ".join([f"**ERROR** {e}" for e in r["errors"]] + r["warnings"]) or "ok"
        if "duration_s" in r:
            out.append(f"| {r['id']} | {r['kind']} | {r['duration_s']:.2f} | {fmt(r.get(key))} | "
                       f"{fmt(r['peak_dbfs'])} | {r['lead_silence_s']:.2f} / {r['trail_silence_s']:.2f} | {problems} |")
        else:
            out.append(f"| {r['id']} | {r['kind']} | - | - | - | - | {problems} |")
    out.append("")
    for kind, median in medians.items():
        out.append(f"- Median {kind} loudness: {median:.1f}. Flagged when more than {FAR_FROM_MEDIAN_DB:.0f} dB away.")
    if gaps:
        out += ["", "| From | To | gap_after_ms (planned) | effective_gap_ms |", "| --- | --- | --- | --- |"]
        out += [f"| {g['from']} | {g['to']} | {g['gap_after_ms']} | {g['effective_gap_ms']} |" for g in gaps]
        out += ["", "effective_gap_ms = planned gap + silence at the end of one stem and the start of the next "
                    f"(windows quieter than -50 dBFS, measured in 50 ms steps, so +/- 50 ms)."]
    errors = sum(len(r["errors"]) for r in results.values())
    warnings = sum(len(r["warnings"]) for r in results.values())
    out += ["", f"**{errors} error(s), {warnings} warning(s).**"]
    return "\n".join(out) + "\n", errors


def is_sample(folder):
    path = Path(folder) / "usage.jsonl"
    return path.is_file() and '"sample": true' in path.read_text(encoding="utf-8")


def main(argv):
    parser = argparse.ArgumentParser(description="Audio checks on every stem (no API calls).")
    parser.add_argument("folder", nargs="?", default=None, help="output folder (default: shared real output)")
    parser.add_argument("--out", help="also write the report to this file")
    args = parser.parse_args(argv)
    folder = Path(args.folder) if args.folder else output_dir()

    try:
        segments = load_json(folder / "segments.json")
    except (OSError, ValueError) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    results = measure_all(folder, segments)
    key, label = loudness_key(results)
    medians = flag_loudness(results, key)
    gaps = effective_gaps(results, segments)
    report, errors = render(folder, results, key, label, medians, gaps, is_sample(folder))
    print(report, end="")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
