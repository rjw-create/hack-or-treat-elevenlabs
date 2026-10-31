"""Read audio stems for the Proof checks."""
import wave
from pathlib import Path


def duration_s(path):
    """Length of a stem in seconds, or None when this format can't be read yet.

    Placeholder stems are WAV, which the standard library reads. Real stems are MP3; reading those
    needs ffprobe, which is added together with the audio checks.
    """
    path = Path(path)
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    return None
