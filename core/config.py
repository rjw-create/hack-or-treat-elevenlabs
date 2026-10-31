"""Paths and settings shared by every Core step."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The three role worktrees are sibling folders, so a sibling folder is the one place all of them can
# read real stems from without committing audio. FULLCAST_OUTPUT_DIR overrides it.
DEFAULT_OUTPUT_DIR = REPO_ROOT.parent / "elevenlabs-shared" / "output"


CACHE_DIR = REPO_ROOT / "cache"  # git-ignored; every paid response is kept here
ADAPTATION_DIR = REPO_ROOT / "core" / "adaptation"  # committed script.json and voices.json

# Step 0 checks this id exists in the account's model list before anything is spent.
DIALOGUE_MODEL_ID = "eleven_v4"
OUTPUT_FORMAT = "mp3_44100_128"

BUDGET_CREDITS = 10_000
RESERVE_CREDITS = 1_500
SPEND_CAP_CREDITS = BUDGET_CREDITS - RESERVE_CREDITS


def output_dir():
    return Path(os.environ.get("FULLCAST_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR)


def api_key():
    """Load ELEVENLABS_API_KEY from this repo's .env at run time. The value is never printed."""
    from dotenv import load_dotenv  # imported here so tests and dry runs work without the package

    load_dotenv(REPO_ROOT / ".env")
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set in .env (only Jackson edits that file)")
    return key
