"""Mix Full Cast stems into one drama file, following segments.json (docs/2026-10-31-interface.md).

Step 1 measures every stem with ffprobe and works out where each one starts (build_timeline).
Step 2 hands ffmpeg one filter graph that places, loops, ducks and mixes everything, and
converts the flat clip to MP3 for the before/after comparison.

Usage, from the repo root:
  python -m web.mix --src output/placeholder --out output/mix/placeholder
  python -m web.mix --src ../elevenlabs-shared/output --out output/mix/real
Needs ffmpeg and ffprobe on PATH. Never calls ElevenLabs or Claude.

The out folder holds everything the player page needs: full-cast.mp3, flat.mp3, timeline.json
and a copy of script.json, plus excerpt.mp3: the stretch of the full cast that speaks the same
lines as the flat clip, for Proof's A/B listener test.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from core.interface import check_folder, load_json

SAMPLE_RATE_HZ = 44100
DUCK_DB = -10  # how far a ducked bed drops while dialogue plays
DUCK_RAMP_MS = 250  # slow enough not to pump, quick enough to be down before the first word
BED_FADE_MS = 800  # beds fade at the edges of their span instead of cutting off
EXCERPT_FADE_MS = 300  # the A/B excerpt stops mid-ambience, so fade it rather than click
LIMIT_FRACTION = 0.89  # about -1 dBFS peak, so the MP3 encoder never clips
MP3_QUALITY = "2"  # LAME VBR quality 2, roughly 190 kbps
TIMELINE_VERSION = 1


def absolute_line_times(seg, start_ms, end_ms):
    """Move Core's per-line times (relative to the stem) onto the drama's timeline.

    Returns None unless every line in the segment has a time: with one line missing, the line before
    it would stay highlighted while it is spoken, so the player highlights the whole segment instead.
    """
    times = {t["line_id"]: t for t in seg.get("line_times_ms") or []}
    line_ids = seg.get("line_ids") or []
    if not line_ids or any(i not in times for i in line_ids):
        return None
    return [{"line_id": i, "start_ms": min(start_ms + times[i]["start_ms"], end_ms),
             "end_ms": min(start_ms + times[i]["end_ms"], end_ms)} for i in line_ids]


def build_timeline(segments, segment_ms, bed_ms, flat_ms=None):
    """Work out where every segment, bed and chapter lands, in ms from the start of the drama.

    segment_ms and bed_ms map ids to measured stem lengths. No files and no ffmpeg here,
    so the timing rules can be tested on their own.
    """
    placed = []
    t_ms = 0
    for seg in segments["segments"]:
        end_ms = t_ms + segment_ms[seg["id"]]
        placed.append({"id": seg["id"], "kind": seg["kind"], "scene": seg["scene"], "file": seg["file"],
                       "start_ms": t_ms, "end_ms": end_ms, "line_ids": seg.get("line_ids", []),
                       "line_times": absolute_line_times(seg, t_ms, end_ms), "cue": seg.get("cue")})
        t_ms = end_ms + seg["gap_after_ms"]
    by_id = {s["id"]: s for s in placed}

    beds = []
    for bed in segments["beds"]:
        start_ms = by_id[bed["from_segment"]]["start_ms"]
        span_ms = by_id[bed["to_segment"]]["end_ms"] - start_ms
        # A bed that does not loop stops when its file runs out, even if the span is longer.
        length_ms = span_ms if bed["loop"] else min(span_ms, bed_ms[bed["id"]])
        beds.append({"id": bed["id"], "kind": bed["kind"], "file": bed["file"],
                     "start_ms": start_ms, "end_ms": start_ms + length_ms, "gain_db": bed["gain_db"],
                     "loop": bed["loop"], "duck": bed["duck_under_dialogue"]})

    chapters = [{"title": c["title"], "segment": c["starts_at_segment"],
                 "start_ms": by_id[c["starts_at_segment"]]["start_ms"]}
                for c in segments.get("chapters", [])]

    compare = None
    flat = segments.get("flat_clip")
    if flat and flat_ms is not None:
        # The "after" side is the stretch of the full cast that speaks the same lines as the flat clip.
        wanted = set(flat["line_ids"])
        spoken = [s for s in placed if wanted & set(s["line_ids"])]
        compare = {"flat_file": "flat.mp3", "flat_ms": flat_ms, "line_ids": flat["line_ids"],
                   "full_start_ms": spoken[0]["start_ms"], "full_end_ms": spoken[-1]["end_ms"],
                   "excerpt_file": "excerpt.mp3"}

    return {"version": TIMELINE_VERSION, "file": "full-cast.mp3", "duration_ms": t_ms,
            "segments": placed, "beds": beds, "chapters": chapters, "compare": compare}


def duck_gain_expr(windows_ms, duck_db=DUCK_DB, ramp_ms=DUCK_RAMP_MS):
    """ffmpeg expression in t (seconds): 1 normally, duck_db during each dialogue window.

    The gain ramps down over ramp_ms before a window starts and back up over ramp_ms after it ends.
    """
    if not windows_ms:
        return "1"
    depth = 1 - 10 ** (duck_db / 20)
    ramp_s = ramp_ms / 1000
    terms = []
    for start_ms, end_ms in windows_ms:
        down_s = start_ms / 1000 - ramp_s
        up_s = end_ms / 1000 + ramp_s
        terms.append(f"clip((t-{down_s:.3f})/{ramp_s:.3f},0,1)*clip(({up_s:.3f}-t)/{ramp_s:.3f},0,1)")
    # min(1, ...) because two ramps overlap when the gap between lines is shorter than two ramps.
    return f"1-{depth:.4f}*min(1,{'+'.join(terms)})"


def filter_graph(timeline):
    """Return (inputs, graph): inputs are (relative file, loop) pairs in ffmpeg input order."""
    fmt = f"aformat=sample_rates={SAMPLE_RATE_HZ}:channel_layouts=stereo"
    inputs, chains, labels = [], [], []

    for seg in timeline["segments"]:
        i = len(inputs)
        inputs.append((seg["file"], False))
        chains.append(f"[{i}:a]{fmt},adelay={seg['start_ms']}:all=1[a{i}]")
        labels.append(f"[a{i}]")

    dialogue = [(s["start_ms"], s["end_ms"]) for s in timeline["segments"] if s["kind"] == "dialogue"]
    for bed in timeline["beds"]:
        i = len(inputs)
        inputs.append((bed["file"], bed["loop"]))
        length_s = (bed["end_ms"] - bed["start_ms"]) / 1000
        fade_s = min(BED_FADE_MS / 1000, length_s / 2)
        steps = [fmt, f"atrim=duration={length_s:.3f}", f"afade=t=in:d={fade_s:.3f}",
                 f"afade=t=out:st={length_s - fade_s:.3f}:d={fade_s:.3f}",
                 f"volume={bed['gain_db']}dB", f"adelay={bed['start_ms']}:all=1"]
        if bed["duck"]:
            # After adelay, t is time from the start of the drama, so dialogue times apply directly.
            windows = [(a, b) for a, b in dialogue if a < bed["end_ms"] and b > bed["start_ms"]]
            steps.append(f"volume='{duck_gain_expr(windows)}':eval=frame")
        chains.append(f"[{i}:a]" + ",".join(steps) + f"[a{i}]")
        labels.append(f"[a{i}]")

    total_s = timeline["duration_ms"] / 1000
    # normalize=0 keeps every stem at its own level; the default divides by the number of inputs.
    # level=0 stops alimiter from boosting the mix; latency=1 keeps the audio in step with the script.
    chains.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,"
                  f"alimiter=limit={LIMIT_FRACTION}:level=0:latency=1,apad=whole_dur={total_s:.3f}[out]")
    return inputs, ";\n".join(chains)


def require_tools():
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        raise RuntimeError(f"{' and '.join(missing)} not found on PATH (install: winget install Gyan.FFmpeg, "
                           "then open a new terminal)")


def probe_ms(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {path}: {result.stderr.strip()}")
    return round(float(result.stdout.strip()) * 1000)


def run_ffmpeg(args):
    result = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr.strip()}")


def mix(src, out):
    src, out = Path(src), Path(out)
    errors = check_folder(src)
    if errors:
        raise RuntimeError(f"{src} does not match the interface:\n" + "\n".join(errors))
    require_tools()
    segments = load_json(src / "segments.json")

    segment_ms = {s["id"]: probe_ms(src / s["file"]) for s in segments["segments"]}
    bed_ms = {b["id"]: probe_ms(src / b["file"]) for b in segments["beds"]}
    flat = segments.get("flat_clip")
    flat_ms = probe_ms(src / flat["file"]) if flat else None
    timeline = build_timeline(segments, segment_ms, bed_ms, flat_ms)

    out.mkdir(parents=True, exist_ok=True)
    inputs, graph = filter_graph(timeline)
    args = []
    for rel, loop in inputs:
        if loop:
            args += ["-stream_loop", "-1"]
        args += ["-i", str(src / rel)]
    mp3 = ["-c:a", "libmp3lame", "-q:a", MP3_QUALITY]
    # The graph grows with every ducked dialogue window, so it goes in a file, not on the command line.
    with tempfile.TemporaryDirectory() as tmp:
        graph_file = Path(tmp) / "graph.txt"
        graph_file.write_text(graph, encoding="utf-8")
        # Mix once to lossless WAV, then encode the full drama and the A/B excerpt from it, so the
        # excerpt is not an MP3 cut from an MP3 (a second encode would make the listener test unfair).
        master = Path(tmp) / "master.wav"
        run_ffmpeg([*args, "-/filter_complex", str(graph_file), "-map", "[out]", str(master)])
        run_ffmpeg(["-i", str(master), *mp3, str(out / timeline["file"])])
        compare = timeline["compare"]
        if compare:
            length_s = (compare["full_end_ms"] - compare["full_start_ms"]) / 1000
            fade_s = min(EXCERPT_FADE_MS / 1000, length_s / 2)
            run_ffmpeg(["-ss", f"{compare['full_start_ms'] / 1000:.3f}", "-t", f"{length_s:.3f}",
                        "-i", str(master), "-af", f"afade=t=out:st={length_s - fade_s:.3f}:d={fade_s:.3f}",
                        *mp3, str(out / compare["excerpt_file"])])
    if flat:
        run_ffmpeg(["-i", str(src / flat["file"]), "-ar", str(SAMPLE_RATE_HZ), "-ac", "2", *mp3,
                    str(out / "flat.mp3")])

    shutil.copyfile(src / "script.json", out / "script.json")
    (out / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    return timeline


def main(argv):
    parser = argparse.ArgumentParser(description="Mix Full Cast stems into one MP3 (no API calls).")
    parser.add_argument("--src", required=True, help="output folder from Core, e.g. output/placeholder")
    parser.add_argument("--out", required=True, help="where to write the mix, e.g. output/mix/placeholder")
    args = parser.parse_args(argv)
    try:
        timeline = mix(args.src, args.out)
    except RuntimeError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    print(f"mixed {len(timeline['segments'])} segments and {len(timeline['beds'])} beds "
          f"into {Path(args.out) / timeline['file']} ({timeline['duration_ms'] / 1000:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
