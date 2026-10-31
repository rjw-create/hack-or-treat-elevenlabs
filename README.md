# Full Cast

Full Cast turns a public-domain short story into a short audio drama: a different voice for every
character, sound effects between lines, ambience and music under the scenes, and a script that follows
along as it plays. The player has a before/after toggle, so you can hear the same passage as a plain
one-voice audiobook and then as the full cast.

The story is **The Monkey's Paw** by W. W. Jacobs (first published 1902), abridged to about five minutes.

Entry for Hack or Treat (2026-10-31), category **Best Project Built With ElevenLabs**.

> Numbers marked `[TBD: ...]` are filled in from the real render and Proof's credit report. They are
> left blank on purpose until they are measured.

## What it does
1. **Adapt.** The story is cut down to a ~5-minute script: three scenes ("The paw", "The visitor",
   "The knocking"), 49 lines and six speaking parts. Lines carry ElevenLabs audio tags such as
   `[whispers]` for delivery. The adaptation was written with Claude Code during the hackathon session
   and then checked by hand, not generated through an API call at run time. It is in
   [`core/adaptation/script.json`](core/adaptation/script.json); the source text is in
   [`core/texts/`](core/texts/).
2. **Cast.** Each character gets one ElevenLabs voice: a library voice or one made with Voice Design
   from a short written description. No voice is cloned from a real person.
3. **Render.** Dialogue is generated with ElevenLabs Text to Dialogue, several lines per request, so
   speakers react to each other. Sound effects and ambience are generated from short text cues
   (music source: `[TBD: confirm from Core's render]`). Every generated clip is cached, so nothing is
   paid for twice.
4. **Mix.** `web/mix.py` measures every clip, places them in order with their pauses, loops the
   ambience under each scene, lowers the music while people talk, and writes one MP3.
5. **Play.** `web/index.html` plays the drama with the script highlighted as it goes: the line being
   spoken when ElevenLabs returns per-line timing with the dialogue, otherwise the few lines of the
   current clip (`[TBD: confirm which on the real render]`). It also has a chapter list
   and the before/after toggle.

How the parts talk to each other is written down in [`docs/2026-10-31-interface.md`](docs/2026-10-31-interface.md).

## Run it (no credits needed)
Needs Python 3.11 and FFmpeg (`winget install Gyan.FFmpeg` on Windows, then open a new terminal).
These commands work in PowerShell and Git Bash, from the repo root.

Make placeholder audio (tones stand in for voices, noise for sound effects):
```
python -m core.placeholders --out output/placeholder
```
Mix it:
```
python -m web.mix --src output/placeholder --out output/mix/placeholder
```
Serve the player and open http://127.0.0.1:8000/web/ :
```
python -m web.serve
```
Use `web.serve`, not `python -m http.server`: the built-in server cannot answer the partial-file
(Range) requests a browser needs to seek in audio, so chapters and the toggle would not work.

### With the real render
Core writes the real clips to `../elevenlabs-shared/output` (outside the repo, never committed). Mix
them and open http://127.0.0.1:8000/web/?mix=real :
```
python -m web.mix --src ../elevenlabs-shared/output --out output/mix/real
```
Rendering the real clips spends ElevenLabs credits and needs `ELEVENLABS_API_KEY` in `.env`. Only the
Core role runs that step. `[TBD: Core's render command once it is merged]`

## Budget and scope, honestly
- The whole project runs on a **10,000-credit** ElevenLabs budget, with at least 1,500 kept in reserve
  for re-renders. Dialogue costs credits per character of text, so the budget sets the length.
- That is why the drama is **abridged to about five minutes**. It is not the full story: scenes are
  shortened and some description is cut. The original is short and worth reading.
- Credits used for the final render: `[TBD: from python -m evals.credits]`. That report says for every
  number whether it was measured from the account balance or estimated from Core's cost rules.
- Finished length: `[TBD: from timeline.json]`.

## Checking the result
All of these read local files only and spend no credits.

| Command | What it checks |
| --- | --- |
| `bash scripts/check.sh` | Everything below on sample data, plus the interface and mixer tests |
| `python -m evals.coverage` | Every script line is spoken exactly once, in order, and every clip exists |
| `python -m evals.audio_checks` | Every clip: length, silence, clipping, loudness, pauses |
| `python -m evals.credits` | Credits by feature, against the budget, and credits per finished minute |

## How the repo is organised
| Folder | What it holds | Role |
| --- | --- | --- |
| `core/` | Interface checks, placeholders, and the ElevenLabs pipeline | Core |
| `web/` | Mixer, dev server and player page | Surface + Story |
| `evals/` | Coverage, audio and credit reports | Proof |
| `docs/` | The interface between the roles, and the [demo script](docs/2026-10-31-demo-script.md) | Core, Story |

The submission text draft is [`2026-10-31-submission.md`](2026-10-31-submission.md).

The three roles worked in parallel in separate git worktrees. Only Core calls ElevenLabs, so credit use
stays in one place. See [`2026-10-31-ROLES.md`](2026-10-31-ROLES.md).

## Credits
- **Story:** "The Monkey's Paw" by W. W. Jacobs (1863-1943), first published in 1902. Public domain.
  This adaptation abridges it.
- **Voices, sound effects and music:** generated with ElevenLabs.
- **Adaptation and code:** written with Claude Code.
