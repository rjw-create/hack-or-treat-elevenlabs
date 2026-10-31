"""Paths and settings shared by every Core step."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The three role worktrees are sibling folders, so a sibling folder is the one place all of them can
# read real stems from without committing audio. FULLCAST_OUTPUT_DIR overrides it.
DEFAULT_OUTPUT_DIR = REPO_ROOT.parent / "elevenlabs-shared" / "output"


def output_dir():
    return Path(os.environ.get("FULLCAST_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR)
