"""Cast each character from the premade voice library (free: reading voices costs no credits).

Matching is by keywords against each voice's labels, description and name, because label values
are free text. Every character gets a different voice, and the result is locked in voices.json.
"""
import json

from core.interface import SCHEMA_VERSION

# What we look for per character. Gender is a hard preference; the rest only adds points.
CASTING = {
    "narrator": {"gender": "male", "age": ("old", "middle"), "words": ("narrat", "deep", "calm", "story", "warm")},
    "mr-white": {"gender": "male", "age": ("old",), "words": ("old", "gentle", "friendly", "warm")},
    "mrs-white": {"gender": "female", "age": ("old", "middle", "mature"), "words": ("warm", "mature", "calm")},
    "herbert": {"gender": "male", "age": ("young",), "words": ("young", "energetic", "friendly", "upbeat")},
    "morris": {"gender": "male", "age": ("middle", "old"), "words": ("gravel", "rough", "deep", "strong", "raspy")},
    "maw-meggins-man": {"gender": "male", "age": ("middle",), "words": ("formal", "neutral", "calm", "professional")},
}
BRITISH_WORDS = ("british", "english", "uk")


def _text(voice):
    labels = voice.get("labels") or {}
    return " ".join([voice.get("name") or "", voice.get("description") or "", *labels.values()]).lower()


def score(voice, wanted):
    labels = {k.lower(): (v or "").lower() for k, v in (voice.get("labels") or {}).items()}
    text = _text(voice)
    points = 0
    gender = labels.get("gender")
    if gender:
        points += 5 if gender == wanted["gender"] else -10
    accent = labels.get("accent", "")
    if any(w in accent or w in text for w in BRITISH_WORDS):
        points += 3
    if any(a in labels.get("age", "") for a in wanted["age"]):
        points += 2
    points += sum(1 for w in wanted["words"] if w in text)
    return points


def choose(voices, character_ids):
    """Pick a distinct voice per character, best match first, in script order."""
    taken, picks = set(), {}
    for cid in character_ids:
        wanted = CASTING.get(cid)
        if wanted is None:
            raise ValueError(f"no casting rule for character {cid!r}; add one to core/cast.py")
        options = [v for v in voices if v["voice_id"] not in taken]
        if not options:
            raise ValueError("not enough voices in the library for every character")
        best = max(options, key=lambda v: score(v, wanted))
        taken.add(best["voice_id"])
        picks[cid] = {"voice_id": best["voice_id"], "source": "library", "label": best.get("name") or "",
                      "score": score(best, wanted)}
    return picks


def fetch_premade(client):
    response = client.voices.search(page_size=100, category="premade")
    voices = [v.model_dump() for v in response.voices]
    if not voices:  # some accounts list library voices without the premade category
        voices = [v.model_dump() for v in client.voices.search(page_size=100).voices]
    return voices


def cast(client, script, voices_path, recast=False):
    if voices_path.exists() and not recast:
        raise FileExistsError(f"{voices_path} is locked; pass --recast to choose voices again")
    picks = choose(fetch_premade(client), [c["id"] for c in script["characters"]])
    voices_path.parent.mkdir(parents=True, exist_ok=True)
    voices_path.write_text(json.dumps({"version": SCHEMA_VERSION, "voices": picks}, indent=2), encoding="utf-8")
    return picks
