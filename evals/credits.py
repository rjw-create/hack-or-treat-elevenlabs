"""Credit report from Core's usage.jsonl: spend by feature, budget, credits per finished minute, cache hits.

Every number says what it rests on: "actual" (credits_actual, which Core measures from the balance),
"estimated" (credits_estimated, from Core's budget rules) or "unknown" (neither was logged).
Rows marked "sample": true are placeholder data. They are refused unless --allow-sample is given, and
then the report is stamped as sample data so it can't be mistaken for real spend.

Usage: python -m evals.credits [output folder] [--budget-credits 10000] [--out report.md] [--allow-sample]
The folder defaults to the shared real output folder (core.config.output_dir()).
"""
import argparse
import json
import sys
from pathlib import Path

from core.config import output_dir
from core.interface import load_json
from evals.audio import duration_s

FEATURES = ("dialogue", "sfx", "music", "flat", "voice_design")
DEFAULT_BUDGET_CREDITS = 10_000
COUNTERS = ("calls", "cache_hits", "actual_calls", "estimated_calls", "unknown_calls",
            "actual_credits", "estimated_credits")


class SampleDataError(ValueError):
    """usage.jsonl holds placeholder rows, which must never be reported as real spend."""


def load_usage(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}: line {n} is not valid JSON ({e.msg})") from e
    return rows


def row_cost(row):
    """(credits, basis) for one logged call. Cache hits cost 0 by definition (interface doc)."""
    if row.get("cache_hit"):
        return 0, "cache_hit"
    if row.get("credits_actual") is not None:
        return row["credits_actual"], "actual"
    if row.get("credits_estimated") is not None:
        return row["credits_estimated"], "estimated"
    return 0, "unknown"


def summarise(rows, allow_sample=False):
    sample_rows = sum(1 for r in rows if r.get("sample"))
    if sample_rows and not allow_sample:
        raise SampleDataError(
            f"{sample_rows} of {len(rows)} usage rows are marked sample: true (placeholder data); "
            "refusing to report them as real spend. Use --allow-sample to build a report stamped as sample.")
    unknown_features = sorted({str(r.get("feature")) for r in rows} - set(FEATURES))
    if unknown_features:
        raise ValueError(f"usage.jsonl has features outside {list(FEATURES)}: {unknown_features}")

    by_feature = {f: dict.fromkeys(COUNTERS, 0) for f in FEATURES}
    for r in rows:
        credits, basis = row_cost(r)
        t = by_feature[r["feature"]]
        t["calls"] += 1
        if basis == "cache_hit":
            t["cache_hits"] += 1
        else:
            t[f"{basis}_calls"] += 1
            if basis != "unknown":
                t[f"{basis}_credits"] += credits
    total = {k: sum(t[k] for t in by_feature.values()) for k in COUNTERS}
    runs = sorted({r.get("run_id") for r in rows if r.get("run_id")})
    return {"by_feature": by_feature, "total": total, "sample": sample_rows > 0, "runs": runs}


def credits_of(t):
    return t["actual_credits"] + t["estimated_credits"]


def basis_label(t):
    """Say which kind of number a credit total is."""
    kinds = [k for k in ("actual", "estimated") if t[f"{k}_calls"]]
    if not kinds and not t["unknown_calls"]:
        return "no paid calls" if t["calls"] else "-"
    label = " + ".join(kinds) if kinds else "unknown"
    if t["unknown_calls"]:
        label += f"; {t['unknown_calls']} call(s) with no cost logged, so this is a lower bound"
    return label


def finished_audio_s(folder, segments):
    """Dialogue and SFX stems plus their gaps, in play order: (seconds, note).

    Beds play under the segments and the flat clip is a separate comparison, so neither adds time.
    Surface owns the final mix, so this is an estimate of the finished runtime.
    """
    total_s = 0.0
    for seg in segments["segments"]:
        path = Path(folder) / seg["file"]
        if not path.is_file():
            return None, f"stem {seg['file']} is missing"
        d_s = duration_s(path)
        if d_s is None:
            return None, f"can't read the length of {seg['file']} yet (needs ffprobe)"
        total_s += d_s + seg["gap_after_ms"] / 1000
    return total_s, "dialogue + SFX stems + gaps; beds and the flat clip are not counted"


def render(summary, folder, budget_credits, audio_s, audio_note):
    t = summary["total"]
    out = ["# Credit report", ""]
    if summary["sample"]:
        out += ["**SAMPLE DATA: these rows are placeholders (sample: true). None of these numbers are real spend.**", ""]
    out += [f"Source: `{Path(folder).as_posix()}/usage.jsonl`, {t['calls']} logged calls across "
            f"{len(summary['runs'])} run(s).", ""]

    out += ["| Feature | Calls | Cache hits | Credits | Based on |", "| --- | --- | --- | --- | --- |"]
    for name, f in summary["by_feature"].items():
        out.append(f"| {name} | {f['calls']} | {f['cache_hits']} | {credits_of(f):,} | {basis_label(f)} |")
    out += [f"| **total** | {t['calls']} | {t['cache_hits']} | {credits_of(t):,} | {basis_label(t)} |", ""]

    spent = credits_of(t)
    out.append(f"- **Budget:** {spent:,} of {budget_credits:,} credits used ({100 * spent / budget_credits:.1f}%), "
               f"{budget_credits - spent:,} left. Based on: {basis_label(t)}.")
    if audio_s:
        out.append(f"- **Finished audio:** {audio_s:.1f} s ({audio_s / 60:.2f} min), {audio_note}.")
        out.append(f"- **Credits per minute of finished audio:** {spent / (audio_s / 60):,.0f} "
                   f"(all credits logged, including re-renders, divided by the finished length). "
                   f"Based on: {basis_label(t)}.")
    else:
        out.append(f"- **Credits per minute of finished audio:** not available ({audio_note}).")
    hit_pct = 100 * t["cache_hits"] / t["calls"] if t["calls"] else 0
    out.append(f"- **Cache hits:** {t['cache_hits']} of {t['calls']} calls ({hit_pct:.0f}%), each costing 0 credits.")
    return "\n".join(out) + "\n"


def main(argv):
    parser = argparse.ArgumentParser(description="Credit report from usage.jsonl (no API calls).")
    parser.add_argument("folder", nargs="?", default=None, help="output folder (default: shared real output)")
    parser.add_argument("--budget-credits", type=int, default=DEFAULT_BUDGET_CREDITS)
    parser.add_argument("--out", help="also write the report to this file")
    parser.add_argument("--allow-sample", action="store_true", help="accept placeholder rows; report is stamped SAMPLE")
    args = parser.parse_args(argv)
    folder = Path(args.folder) if args.folder else output_dir()

    try:
        summary = summarise(load_usage(folder / "usage.jsonl"), allow_sample=args.allow_sample)
    except (OSError, ValueError) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    audio_s, audio_note = finished_audio_s(folder, load_json(folder / "segments.json"))
    report = render(summary, folder, args.budget_credits, audio_s, audio_note)
    print(report, end="")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
