"""Coverage check: every script line is spoken exactly once, in order, and every stem file exists.

core.interface checks the same rule but reports one combined error; this names each missing,
repeated, unknown or out-of-order line, so a broken render is quick to trace.

Usage: python -m evals.coverage [output folder]
The folder defaults to the shared real output folder (core.config.output_dir()).
"""
import argparse
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

from core.config import output_dir
from core.interface import load_json, script_lines


def check_lines(script, segments):
    expected = list(script_lines(script))
    spoken = [line_id for seg in segments["segments"] if seg.get("kind") == "dialogue"
              for line_id in seg.get("line_ids", [])]
    counts = Counter(spoken)
    problems = [f"line {i} is not in any dialogue segment" for i in expected if i not in counts]
    problems += [f"line {i} is in {n} dialogue segments" for i, n in counts.items() if n > 1]
    problems += [f"line {i} is not in script.json" for i in counts if i not in expected]

    position = {line_id: n for n, line_id in enumerate(expected)}
    known = [i for i in spoken if i in position]
    problems += [f"line {b} plays after {a} but comes before it in the script"
                 for a, b in zip(known, known[1:]) if position[b] < position[a]]
    return problems


def stem_files(segments):
    files = [seg["file"] for seg in segments["segments"]]
    files += [bed["file"] for bed in segments.get("beds", [])]
    if segments.get("flat_clip"):
        files.append(segments["flat_clip"]["file"])
    return files


def check_stems(folder, segments):
    problems = []
    for name in stem_files(segments):
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or ":" in name:
            problems.append(f"stem path {name!r} points outside the output folder")
            continue
        path = Path(folder) / name
        if not path.is_file():
            problems.append(f"stem {name} is missing")
        elif path.stat().st_size == 0:
            problems.append(f"stem {name} is empty (0 bytes)")
    return problems


def main(argv):
    parser = argparse.ArgumentParser(description="Line and stem coverage check (no API calls).")
    parser.add_argument("folder", nargs="?", default=None, help="output folder (default: shared real output)")
    args = parser.parse_args(argv)
    folder = Path(args.folder) if args.folder else output_dir()

    try:
        script = load_json(folder / "script.json")
        segments = load_json(folder / "segments.json")
    except (OSError, ValueError) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    problems = check_lines(script, segments) + check_stems(folder, segments)
    for p in problems:
        print(f"ERROR {p}", file=sys.stderr)
    if problems:
        return 1
    dialogue = sum(1 for s in segments["segments"] if s.get("kind") == "dialogue")
    print(f"coverage OK: {len(script_lines(script))} lines in {dialogue} dialogue segments, "
          f"{len(stem_files(segments))} stems present ({folder.as_posix()})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
