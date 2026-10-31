# elevenlabs-project

Hack or Treat hackathon entry (2026-10-31) for one category only: **Best Project Built With ElevenLabs**.
Candidate ideas are in `2026-10-31-ideas.md`. Chosen idea: **Full Cast** (see Status).

## Focus
- Voice or sound is the product. Go beyond plain text to speech (sound effects, speech to text, agents, voice changer).
- This is the only project that spends the free ElevenLabs tokens. Cache generated audio instead of regenerating it.
- `ELEVENLABS_API_KEY` lives in `.env` (listed in `.gitignore`). Never commit it, print it, or send it to the browser.
- Voice cloning only with the speaker's explicit consent.

## Status
- Idea: **Full Cast**. The Monkey's Paw (W. W. Jacobs, 1902, public domain) as a ~5-minute abridged
  audio drama: 6 voices, SFX, music, plus a flat audiobook clip for before/after. Scope is set by a
  10,000-credit budget.
- Roles: parallel sessions (Core, Surface + Story, Proof) per `2026-10-31-ROLES.md`. This folder is Core.
  The contract between roles is `docs/2026-10-31-interface.md`.
- Stack: Python 3.11. So far standard library only (`core/`). Approved for Core Step 0, not yet
  installed: `.venv` with `elevenlabs`, `anthropic`, `python-dotenv`, `pytest`. ffmpeg is used by Surface
  for the mix (install needs Jackson's OK). `ANTHROPIC_API_KEY` also lives in `.env`.
- Real audio output goes to `../elevenlabs-shared/output` (`core.config.output_dir()`, override with
  `FULLCAST_OUTPUT_DIR`). Never commit audio.
- Verify: `bash scripts/check.sh` (Git Bash). Spends no credits.
