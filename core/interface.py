"""Load and check the files Core hands to Surface and Proof.

The rules here are the ones written down in docs/2026-10-31-interface.md. The real pipeline runs
the same checks on its own output, so the sample files and the real files can't drift apart.

Usage: python -m core.interface <folder with script.json, voices.json, segments.json>
"""
import json
import re
import sys
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = 1
MAX_VOICES = 10  # Text to Dialogue accepts at most 10 unique voice ids per request
MAX_DIALOGUE_CHARS = 2000  # ElevenLabs docs: keep each Text to Dialogue request at or below this
VOICE_DESCRIPTION_CHARS = (20, 1000)  # Voice Design accepts descriptions in this range
SEGMENT_KINDS = {"dialogue", "sfx"}
BED_KINDS = {"ambience", "music"}
VOICE_SOURCES = {"library", "voice_design"}
AUDIO_TAG = re.compile(r"\[[^\]]*\]")
LINE_ID = re.compile(r"^s\d{2}-l\d{3}$")


def strip_tags(text):
    """Remove audio tags like [whispers] and collapse spaces, for display and word matching."""
    return " ".join(AUDIO_TAG.sub(" ", text).split())


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def script_lines(script):
    """Map line id -> (scene number, line dict), in script order."""
    lines = {}
    for scene in script.get("scenes", []):
        for line in scene.get("lines", []):
            lines[line.get("id")] = (scene.get("number"), line)
    return lines


def _check_version(data, name):
    if data.get("version") != SCHEMA_VERSION:
        return [f"{name}: version must be {SCHEMA_VERSION}, got {data.get('version')!r}"]
    return []


def _check_relative_path(path, where):
    # Paths come from JSON that other roles read, so refuse anything that could point outside the folder.
    if not isinstance(path, str) or not path:
        return [f"{where}: file must be a non-empty string"]
    p = PurePosixPath(path)
    if "\\" in path or p.is_absolute() or ":" in path or ".." in p.parts:
        return [f"{where}: file {path!r} must be a relative forward-slash path inside the output folder"]
    return []


def check_script(script):
    errors = _check_version(script, "script.json")
    characters = script.get("characters", [])
    ids = [c.get("id") for c in characters]
    if not characters:
        errors.append("script.json: no characters")
    if len(ids) != len(set(ids)):
        errors.append("script.json: character ids are not unique")
    if len(ids) > MAX_VOICES:
        errors.append(f"script.json: {len(ids)} characters, Text to Dialogue allows at most {MAX_VOICES}")
    low, high = VOICE_DESCRIPTION_CHARS
    for c in characters:
        if not low <= len(c.get("description", "")) <= high:
            errors.append(f"script.json: character {c.get('id')!r} description must be {low}-{high} characters")

    seen = set()
    for scene in script.get("scenes", []):
        for line in scene.get("lines", []):
            line_id = line.get("id")
            if not isinstance(line_id, str) or not LINE_ID.match(line_id):
                errors.append(f"script.json: bad line id {line_id!r} (expected like s01-l001)")
            if line_id in seen:
                errors.append(f"script.json: duplicate line id {line_id!r}")
            seen.add(line_id)
            if line.get("speaker") not in ids:
                errors.append(f"script.json: line {line_id!r} has unknown speaker {line.get('speaker')!r}")
            if not strip_tags(line.get("text", "")):
                errors.append(f"script.json: line {line_id!r} has no spoken text")
    if not seen:
        errors.append("script.json: no lines")
    return errors


def check_voices(voices, script):
    errors = _check_version(voices, "voices.json")
    table = voices.get("voices", {})
    for c in script.get("characters", []):
        entry = table.get(c.get("id"))
        if not entry:
            errors.append(f"voices.json: no voice for character {c.get('id')!r}")
            continue
        if not entry.get("voice_id"):
            errors.append(f"voices.json: empty voice_id for {c.get('id')!r}")
        if entry.get("source") not in VOICE_SOURCES:
            errors.append(f"voices.json: source for {c.get('id')!r} must be one of {sorted(VOICE_SOURCES)}")
    return errors


def check_segments(segments, script):
    errors = _check_version(segments, "segments.json")
    lines = script_lines(script)
    order = {seg.get("id"): i for i, seg in enumerate(segments.get("segments", []))}
    if len(order) != len(segments.get("segments", [])):
        errors.append("segments.json: segment ids are not unique")

    covered = []
    for seg in segments.get("segments", []):
        where = f"segments.json: segment {seg.get('id')!r}"
        if seg.get("kind") not in SEGMENT_KINDS:
            errors.append(f"{where}: kind must be one of {sorted(SEGMENT_KINDS)}")
        errors += _check_relative_path(seg.get("file"), where)
        gap_ms = seg.get("gap_after_ms")
        if not isinstance(gap_ms, int) or gap_ms < 0:
            errors.append(f"{where}: gap_after_ms must be a whole number >= 0")
        if seg.get("kind") == "dialogue":
            line_ids = seg.get("line_ids") or []
            if not line_ids:
                errors.append(f"{where}: dialogue needs line_ids")
            missing = [i for i in line_ids if i not in lines]
            if missing:
                errors.append(f"{where}: unknown line ids {missing}")
            if any(lines[i][0] != seg.get("scene") for i in line_ids if i in lines):
                errors.append(f"{where}: all lines must belong to scene {seg.get('scene')}")
            chars = sum(len(lines[i][1].get("text", "")) for i in line_ids if i in lines)
            if chars > MAX_DIALOGUE_CHARS:
                errors.append(f"{where}: {chars} characters, over the {MAX_DIALOGUE_CHARS} per-request limit")
            covered += line_ids
        elif seg.get("kind") == "sfx" and not seg.get("cue"):
            errors.append(f"{where}: sfx needs a cue")

    # Proof relies on this: every line spoken exactly once, in script order.
    if covered != list(lines):
        errors.append("segments.json: dialogue segments must cover every script line exactly once, in order")

    for bed in segments.get("beds", []):
        where = f"segments.json: bed {bed.get('id')!r}"
        if bed.get("kind") not in BED_KINDS:
            errors.append(f"{where}: kind must be one of {sorted(BED_KINDS)}")
        errors += _check_relative_path(bed.get("file"), where)
        start, end = bed.get("from_segment"), bed.get("to_segment")
        if start not in order or end not in order:
            errors.append(f"{where}: from_segment/to_segment must name existing segments")
        elif order[start] > order[end]:
            errors.append(f"{where}: from_segment comes after to_segment")
        gain_db = bed.get("gain_db")
        if not isinstance(gain_db, (int, float)) or gain_db > 0:
            errors.append(f"{where}: gain_db must be a number <= 0")

    for chapter in segments.get("chapters", []):
        if chapter.get("starts_at_segment") not in order:
            errors.append(f"segments.json: chapter {chapter.get('title')!r} starts at an unknown segment")

    flat = segments.get("flat_clip")
    if flat:
        errors += _check_relative_path(flat.get("file"), "segments.json: flat_clip")
        missing = [i for i in flat.get("line_ids", []) if i not in lines]
        if missing or not flat.get("line_ids"):
            errors.append(f"segments.json: flat_clip needs known line_ids (unknown: {missing})")
    return errors


def check_folder(folder):
    folder = Path(folder)
    script = load_json(folder / "script.json")
    errors = check_script(script)
    errors += check_voices(load_json(folder / "voices.json"), script)
    errors += check_segments(load_json(folder / "segments.json"), script)
    return errors


def main(argv):
    if len(argv) != 1:
        print("usage: python -m core.interface <folder>", file=sys.stderr)
        return 2
    errors = check_folder(argv[0])
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    if errors:
        return 1
    print(f"interface OK: {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
