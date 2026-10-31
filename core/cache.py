"""Content-addressed audio cache: the same request is paid for once, ever.

The key is a hash of the endpoint and every parameter that changes the audio, so editing one
line in script.json re-renders only the segments that contain it.
"""
import hashlib
import json

from core import config


def cache_key(endpoint, params):
    blob = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def lookup(key, cache_dir=None):
    """Return (audio bytes, meta dict) for a cached request, or None."""
    cache_dir = cache_dir or config.CACHE_DIR
    audio, meta = cache_dir / f"{key}.mp3", cache_dir / f"{key}.json"
    if not (audio.exists() and meta.exists()):
        return None
    return audio.read_bytes(), json.loads(meta.read_text(encoding="utf-8"))


def store(key, audio_bytes, meta, cache_dir=None):
    cache_dir = cache_dir or config.CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Meta is written last, so an interrupted write leaves no half entry that lookup would trust.
    (cache_dir / f"{key}.mp3").write_bytes(audio_bytes)
    (cache_dir / f"{key}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
