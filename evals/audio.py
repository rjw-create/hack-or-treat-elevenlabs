"""Read and measure audio stems for the Proof checks.

WAV (the placeholders) is read with the standard library. Other formats (real stems are MP3) are
decoded with ffmpeg, and loudness in LUFS always needs ffmpeg. When ffmpeg is missing those values
come back as None, so reports can say "not checked" instead of guessing.
"""
import array
import math
import operator
import re
import shutil
import subprocess
import wave
from pathlib import Path

DECODE_RATE_HZ = 44100  # ffmpeg decodes every non-WAV stem to this rate, mono, 16-bit
FULL_SCALE = 32768  # 16-bit PCM
CLIP_FRACTION = 0.999  # a sample this close to full scale counts as at the ceiling
CLIP_RUN_SAMPLES = 3  # one sample at the ceiling can be a real peak; three in a row is a flattened wave
WINDOW_S = 0.05  # silence is judged in 50 ms windows, short enough to catch gaps between words
SILENCE_DBFS = -50.0  # quieter than this is silence; room tone in generated speech sits well above it
INTEGRATED_LUFS = re.compile(r"Summary:.*?Integrated loudness:\s*I:\s*(-?inf|-?\d+(?:\.\d+)?) LUFS", re.DOTALL)


def dbfs(level_fraction):
    return 20 * math.log10(level_fraction) if level_fraction > 0 else float("-inf")


def duration_s(path):
    """Length of a stem in seconds, or None when it isn't WAV and ffprobe isn't installed."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def read_samples(path):
    """(mono 16-bit samples, rate_hz), or None when the format needs ffmpeg and it isn't installed."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError(f"{path.name}: expected mono 16-bit WAV like the placeholders")
            pcm = array.array("h")
            pcm.frombytes(w.readframes(w.getnframes()))
            return pcm, w.getframerate()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(DECODE_RATE_HZ), "-"],
        capture_output=True, check=True)
    pcm = array.array("h")
    pcm.frombytes(result.stdout)
    return pcm, DECODE_RATE_HZ


def loudness_lufs(path):
    """Integrated loudness (EBU R128) from ffmpeg's ebur128 filter, or None without ffmpeg.

    ebur128 rather than loudnorm: same integrated value, but loudnorm resamples to 192 kHz and was
    about 4x slower per stem.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    found = INTEGRATED_LUFS.search(result.stderr)
    if not found:
        raise ValueError(f"{Path(path).name}: no integrated loudness in ffmpeg's ebur128 summary")
    return float(found.group(1))


def count_clip_runs(pcm):
    ceiling = CLIP_FRACTION * FULL_SCALE
    runs = run = 0
    for s in pcm:
        if abs(s) >= ceiling:
            run += 1
            continue
        if run >= CLIP_RUN_SAMPLES:
            runs += 1
        run = 0
    return runs + (run >= CLIP_RUN_SAMPLES)


def measure(path):
    """Level, clipping and silence for one stem, or None when it can't be decoded here."""
    decoded = read_samples(path)
    if decoded is None:
        return None
    pcm, rate_hz = decoded
    window = max(1, int(WINDOW_S * rate_hz))
    sum_sq = 0
    silent = []
    for start in range(0, len(pcm), window):
        chunk = pcm[start:start + window]
        chunk_sq = sum(map(operator.mul, chunk, chunk))
        sum_sq += chunk_sq
        silent.append(dbfs(math.sqrt(chunk_sq / len(chunk)) / FULL_SCALE) < SILENCE_DBFS)

    peak = max(map(abs, pcm), default=0)
    lead = next((i for i, quiet in enumerate(silent) if not quiet), len(silent))
    trail = next((i for i, quiet in enumerate(reversed(silent)) if not quiet), len(silent))
    longest = run = 0
    for quiet in silent[lead:len(silent) - trail]:
        run = run + 1 if quiet else 0
        longest = max(longest, run)

    duration = len(pcm) / rate_hz
    return {
        "duration_s": duration,
        "rms_dbfs": dbfs(math.sqrt(sum_sq / len(pcm)) / FULL_SCALE) if pcm else float("-inf"),
        "peak_dbfs": dbfs(peak / FULL_SCALE),
        "clip_runs": count_clip_runs(pcm) if peak >= CLIP_FRACTION * FULL_SCALE else 0,
        "lead_silence_s": min(lead * WINDOW_S, duration),
        "trail_silence_s": min(trail * WINDOW_S, duration),
        "longest_inner_silence_s": longest * WINDOW_S,
    }
