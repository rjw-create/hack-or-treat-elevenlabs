"""Summarise listener A/B ratings (flat clip vs full cast) from the CSV exported by evals/listener_form.html.

Practice rows are left out, the same way placeholder usage rows are refused by evals.credits.
With --flat and --full the two clips' loudness is measured too, because listeners tend to prefer
the louder of two clips, and that belongs in the limits.

Usage: python -m evals.summarise_ratings [results/listener_ratings.csv] [--out results/summary.md]
                                         [--flat flat.mp3 --full excerpt.mp3]
"""
import argparse
import csv
import math
import sys
from pathlib import Path

from evals.audio import duration_s, loudness_lufs

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "results" / "listener_ratings.csv"
COLUMNS = ["listener_id", "rated_at", "practice", "flat_first", "clarity_flat", "clarity_full_cast",
           "immersion_flat", "immersion_full_cast", "preferred", "comment"]
MEASURES = ("clarity", "immersion")
PREFERENCES = ("flat", "full_cast", "no_preference")
LOUDNESS_MATCH_LU = 1.0  # a gap bigger than this is enough for "louder sounds better" to bias the choice
FEW_LISTENERS = 10  # below this, a sign test can only detect a near-unanimous result


def parse_bool(value, where):
    if value in ("true", "false"):
        return value == "true"
    raise ValueError(f"{where}: expected true or false, got {value!r}")


def parse_rating(value, where):
    if value in ("1", "2", "3", "4", "5"):
        return int(value)
    raise ValueError(f"{where}: rating must be a whole number 1-5, got {value!r}")


def load_ratings(path):
    """(real rows, practice row count). Raises ValueError naming the first bad cell."""
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path}: columns must be {COLUMNS}, got {reader.fieldnames}")
        rows, practice, seen = [], 0, set()
        for n, raw in enumerate(reader, 2):
            where = f"{Path(path).name} line {n}"
            if parse_bool(raw["practice"], f"{where} practice"):
                practice += 1
                continue
            if raw["listener_id"] in seen:
                raise ValueError(f"{where}: listener {raw['listener_id']!r} appears twice")
            seen.add(raw["listener_id"])
            if raw["preferred"] not in PREFERENCES:
                raise ValueError(f"{where}: preferred must be one of {PREFERENCES}, got {raw['preferred']!r}")
            row = {"listener_id": raw["listener_id"], "preferred": raw["preferred"],
                   "flat_first": parse_bool(raw["flat_first"], f"{where} flat_first")}
            for measure in MEASURES:
                for side in ("flat", "full_cast"):
                    column = f"{measure}_{side}"
                    row[column] = parse_rating(raw[column], f"{where} {column}")
            rows.append(row)
    return rows, practice


def sign_test_p(wins, losses):
    """Two-sided exact sign test; ties are dropped before calling. Standard library only."""
    n = wins + losses
    if n == 0:
        return None
    tail = sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def summarise(rows):
    out = {"n": len(rows), "measures": {}}
    for measure in MEASURES:
        flat = [r[f"{measure}_flat"] for r in rows]
        full = [r[f"{measure}_full_cast"] for r in rows]
        diffs = [b - a for a, b in zip(flat, full)]
        better = sum(d > 0 for d in diffs)
        worse = sum(d < 0 for d in diffs)
        out["measures"][measure] = {
            "mean_flat": sum(flat) / len(flat), "mean_full_cast": sum(full) / len(full),
            "mean_diff": sum(diffs) / len(diffs), "full_better": better, "same": len(diffs) - better - worse,
            "flat_better": worse, "p": sign_test_p(better, worse)}
    counts = {p: sum(r["preferred"] == p for r in rows) for p in PREFERENCES}
    out["preferred"] = counts
    out["preferred_p"] = sign_test_p(counts["full_cast"], counts["flat"])
    chose = [r for r in rows if r["preferred"] != "no_preference"]
    out["chose"] = len(chose)
    out["chose_first_played"] = sum((r["preferred"] == "flat") == r["flat_first"] for r in chose)
    return out


def measure_clips(flat, full):
    clips = {}
    for name, path in (("flat", flat), ("full cast excerpt", full)):
        clips[name] = {"file": Path(path).name, "duration_s": duration_s(path), "lufs": loudness_lufs(path)}
    return clips


def fmt_p(p):
    return "n/a (no one chose a side)" if p is None else f"{p:.3f}"


def render(summary, practice, source, clips):
    n = summary["n"]
    out = ["# Listener A/B summary: flat clip vs full cast", "",
           f"Source: `{source}`. {n} listener(s); {practice} practice row(s) left out.", "",
           "## Ratings (1-5)", "",
           "| Measure | Mean, flat | Mean, full cast | Mean difference | Full cast higher / same / lower | Sign test p |",
           "| --- | --- | --- | --- | --- | --- |"]
    for measure, m in summary["measures"].items():
        out.append(f"| {measure} | {m['mean_flat']:.2f} | {m['mean_full_cast']:.2f} | {m['mean_diff']:+.2f} | "
                   f"{m['full_better']} / {m['same']} / {m['flat_better']} | {fmt_p(m['p'])} |")
    c = summary["preferred"]
    out += ["", "## Preference", "",
            f"- Full cast: {c['full_cast']} of {n}. Flat: {c['flat']} of {n}. No preference: {c['no_preference']} of {n}.",
            f"- Sign test (full cast vs flat, no-preference left out): p = {fmt_p(summary['preferred_p'])}.",
            f"- Order check: {summary['chose_first_played']} of {summary['chose']} listeners who chose a side "
            "picked the clip that was labelled A (shown first).", ""]
    if clips:
        out += ["## Clips played", "", "| Clip | File | duration_s | Loudness (LUFS) |", "| --- | --- | --- | --- |"]
        for name, clip in clips.items():
            lufs = "not measured (needs ffmpeg)" if clip["lufs"] is None else f"{clip['lufs']:.1f}"
            length = "-" if clip["duration_s"] is None else f"{clip['duration_s']:.2f}"
            out.append(f"| {name} | `{clip['file']}` | {length} | {lufs} |")
        out.append("")

    out += ["## Limits", ""]
    if n < FEW_LISTENERS:
        out.append(f"- Only {n} listener(s). With fewer than {FEW_LISTENERS}, a sign test reaches p < 0.05 only "
                   "when almost everyone agrees, so treat these numbers as a pilot, not proof.")
    out += ["- Not truly blind: a single voice and a full cast with sound effects are easy to tell apart by ear. "
            "The random A/B labels only control the play order.",
            "- Listeners were not sampled at random, and they knew the project. Note who they were next to this file.",
            "- One short excerpt of one story. The result may not hold for the full five minutes or other material.",
            "- Ratings are ordinal (1-5). Means are shown for convenience; the sign tests do not assume equal steps."]
    if clips and all(clip["lufs"] is not None for clip in clips.values()):
        gap_lu = clips["full cast excerpt"]["lufs"] - clips["flat"]["lufs"]
        verdict = ("within" if abs(gap_lu) <= LOUDNESS_MATCH_LU else "outside")
        out.append(f"- Loudness: the full cast excerpt is {gap_lu:+.1f} LU relative to the flat clip, {verdict} the "
                   f"{LOUDNESS_MATCH_LU:.0f} LU match. Listeners tend to prefer the louder clip.")
    else:
        out.append("- Loudness match between the two clips was not checked (run with --flat and --full, with ffmpeg).")
    return "\n".join(out) + "\n"


def main(argv):
    parser = argparse.ArgumentParser(description="Summarise listener A/B ratings (no API calls).")
    parser.add_argument("csv", nargs="?", default=str(DEFAULT_CSV), help="ratings CSV from listener_form.html")
    parser.add_argument("--out", help="also write the summary here, e.g. results/summary.md")
    parser.add_argument("--flat", help="flat clip that was played, to measure loudness")
    parser.add_argument("--full", help="full cast excerpt that was played, to measure loudness")
    args = parser.parse_args(argv)
    if bool(args.flat) != bool(args.full):
        parser.error("give both --flat and --full, or neither")

    try:
        rows, practice = load_ratings(args.csv)
    except (OSError, ValueError) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    if not rows:
        print(f"ERROR no real ratings in {args.csv} ({practice} practice row(s)); nothing to summarise", file=sys.stderr)
        return 1
    clips = measure_clips(args.flat, args.full) if args.flat else None
    report = render(summarise(rows), practice, Path(args.csv).as_posix(), clips)
    print(report, end="")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
