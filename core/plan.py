"""Turn script.json into the segments.json mix plan. Pure: no files, no API.

Rules (docs/2026-10-31-interface.md): dialogue segments of about 3-6 lines and at most ~600
characters, split at natural beats; an SFX segment follows any line with sfx_after.
"""
from core.interface import SCHEMA_VERSION, strip_tags

MAX_SEGMENT_CHARS = 600
MAX_SEGMENT_LINES = 6
MIN_LINES_BEFORE_BEAT = 3  # a narrator line starts a new segment once the current one has this many
GAP_BETWEEN_SEGMENTS_MS = 350
GAP_AFTER_SFX_MS = 300
GAP_AFTER_SCENE_MS = 1500
FLAT_CLIP_MAX_CHARS = 450  # spoken characters in the before/after clip
MUSIC_LENGTH_MS = 45_000
AMBIENCE_LENGTH_S = 20
STEM_EXT = "mp3"


def _dialogue_chunks(lines):
    """Group one scene's lines into dialogue chunks; a chunk always ends at a line with sfx_after."""
    chunks, current, chars = [], [], 0
    for line in lines:
        n = len(line["text"])
        beat = line["speaker"] == "narrator" and len(current) >= MIN_LINES_BEFORE_BEAT
        too_big = current and (chars + n > MAX_SEGMENT_CHARS or len(current) >= MAX_SEGMENT_LINES)
        if beat or too_big:
            chunks.append(current)
            current, chars = [], 0
        current.append(line)
        chars += n
        if line.get("sfx_after"):
            chunks.append(current)
            current, chars = [], 0
    if current:
        chunks.append(current)
    return chunks


def build_segments(script, scenes=None):
    """Return a segments.json dict. scenes: optional set of scene numbers to include (preview runs)."""
    segments, beds, chapters = [], [], []
    picked = [s for s in script["scenes"] if scenes is None or s["number"] in scenes]
    for scene in picked:
        tag = f"s{scene['number']:02d}"
        first_id = None
        d = x = 0
        for chunk in _dialogue_chunks(scene["lines"]):
            d += 1
            seg_id = f"{tag}-d{d:03d}"
            first_id = first_id or seg_id
            segments.append({"id": seg_id, "scene": scene["number"], "kind": "dialogue",
                             "file": f"stems/dialogue/{seg_id}.{STEM_EXT}",
                             "line_ids": [l["id"] for l in chunk], "gap_after_ms": GAP_BETWEEN_SEGMENTS_MS})
            cue = chunk[-1].get("sfx_after")
            if cue:
                x += 1
                sfx_id = f"{tag}-x{x:03d}"
                segments.append({"id": sfx_id, "scene": scene["number"], "kind": "sfx",
                                 "file": f"stems/sfx/{sfx_id}.{STEM_EXT}", "cue": cue,
                                 "gap_after_ms": GAP_AFTER_SFX_MS})
        segments[-1]["gap_after_ms"] = GAP_AFTER_SCENE_MS
        last_id = segments[-1]["id"]
        chapters.append({"title": scene["title"], "starts_at_segment": first_id})
        beds.append({"id": f"{tag}-amb", "kind": "ambience", "file": f"stems/beds/{tag}-amb.{STEM_EXT}",
                     "from_segment": first_id, "to_segment": last_id, "gain_db": -20, "loop": True,
                     "duck_under_dialogue": False, "prompt": scene["ambience"]})
        if scene is script["scenes"][0]:
            # One theme only (credit budget): it opens the drama and is ducked under speech.
            beds.append({"id": "theme", "kind": "music", "file": f"stems/beds/theme.{STEM_EXT}",
                         "from_segment": first_id, "to_segment": last_id, "gain_db": -14, "loop": False,
                         "duck_under_dialogue": True, "prompt": scene["music_mood"]})
    segments[-1]["gap_after_ms"] = 0

    plan = {"version": SCHEMA_VERSION, "segments": segments, "beds": beds, "chapters": chapters}
    first_scene = script["scenes"][0]
    if any(s is first_scene for s in picked):
        plan["flat_clip"] = {"file": f"stems/flat/flat.{STEM_EXT}", "voice": "narrator",
                             "line_ids": _flat_lines(first_scene)}
    return plan


def _flat_lines(scene):
    ids, chars = [], 0
    for line in scene["lines"]:
        n = len(strip_tags(line["text"]))
        if ids and chars + n > FLAT_CLIP_MAX_CHARS:
            break
        ids.append(line["id"])
        chars += n
    return ids


def scene_subset(script, scenes):
    """A script.json limited to some scenes, so a preview folder passes the interface check."""
    return dict(script, scenes=[s for s in script["scenes"] if s["number"] in scenes])
