# Full Cast interface (Core -> Surface, Proof)

Owned by Core. Any change here is called out in the PR description (ROLES rule 2).
Schema version: **1**. Every JSON file below carries `"version": 1`.

Core is the only role that calls ElevenLabs or Claude. Surface and Proof read the files described here
and never call those APIs.

## Files at a glance
| File | Written by | Read by | What it is |
| --- | --- | --- | --- |
| `script.json` | Core (`adapt`) | Surface (follow-along text), Proof (line coverage) | The adaptation: characters, scenes, lines with audio tags |
| `voices.json` | Core (`cast`) | Proof | Which ElevenLabs voice plays each character (locked) |
| `segments.json` | Core (`render`) | Surface (mix), Proof (checks) | Ordered list of stems to play, plus beds, chapters, flat clip |
| `stems/**` | Core (`render`) | Surface, Proof | The audio files named in `segments.json` |
| `usage.jsonl` | Core (every paid call) | Proof | One line per ElevenLabs call: what it cost |

All five live in one **output folder**. Paths inside the JSON files are relative to that folder and use
forward slashes. Samples of every file are in `core/fixtures/sample/`.

## script.json
```json
{
  "version": 1,
  "title": "The Monkey's Paw",
  "author": "W. W. Jacobs",
  "source": "texts/2026-10-31-monkeys-paw.txt",
  "characters": [
    {"id": "narrator", "name": "Narrator", "description": "voice description, 20-1000 characters"}
  ],
  "scenes": [
    {
      "number": 1,
      "title": "The parlour",
      "ambience": "wind outside, crackling fire",
      "music_mood": "uneasy, quiet",
      "lines": [
        {"id": "s01-l001", "speaker": "narrator", "text": "[quietly] The night was cold and wet."}
      ]
    }
  ]
}
```
- `characters`: at most 10 (Text to Dialogue voice limit). `id` is lowercase-with-dashes.
- `lines[].text` keeps ElevenLabs audio tags inline, e.g. `[whispers]`. For display or word matching,
  strip them: remove every `[...]` and collapse spaces (`core.interface.strip_tags`).
- Line ids are `s<scene, 2 digits>-l<line, 3 digits>` and unique across the whole script.
- Optional `lines[].sfx_after`: a sound-effect description to play right after that line, e.g.
  `"sfx_after": "three slow knocks on a wooden front door"`. Core's render step turns each one into an
  `sfx` segment in `segments.json`; Surface and Proof read SFX from `segments.json`, not from here.
  (Added 2026-10-31; existing files without it stay valid.)
- The real adaptation lives at `core/adaptation/script.json` (committed, reviewable); render copies it
  into the output folder.

## voices.json
```json
{
  "version": 1,
  "voices": {
    "narrator": {"voice_id": "abc123", "source": "library", "label": "deep, measured"}
  }
}
```
- One entry per character id. `source` is `library` (premade voice) or `voice_design`.
- Voice ids are not secrets, but the API key is: it never appears in any of these files.

## segments.json (the mix plan)
```json
{
  "version": 1,
  "segments": [
    {"id": "s01-d001", "scene": 1, "kind": "dialogue", "file": "stems/dialogue/s01-d001.mp3",
     "line_ids": ["s01-l001", "s01-l002"], "gap_after_ms": 400},
    {"id": "s01-x001", "scene": 1, "kind": "sfx", "file": "stems/sfx/s01-x001.mp3",
     "cue": "three loud knocks on the front door", "gap_after_ms": 300}
  ],
  "beds": [
    {"id": "s01-amb", "kind": "ambience", "file": "stems/beds/s01-amb.mp3",
     "from_segment": "s01-d001", "to_segment": "s01-x001", "gain_db": -20, "loop": true,
     "duck_under_dialogue": false},
    {"id": "theme", "kind": "music", "file": "stems/beds/theme.mp3",
     "from_segment": "s01-d001", "to_segment": "s01-d001", "gain_db": -14, "loop": false,
     "duck_under_dialogue": true}
  ],
  "chapters": [{"title": "Part I: The paw", "starts_at_segment": "s01-d001"}],
  "flat_clip": {"file": "stems/flat/flat.mp3", "voice": "narrator", "line_ids": ["s01-l001", "s01-l002"]}
}
```
- **`segments` is in play order and never overlaps.** Each segment starts when the previous one ends plus
  its `gap_after_ms`. There are no absolute times in this file: Surface measures each stem's length
  (e.g. `ffprobe`) and computes start times while mixing.
- `kind`: `dialogue` (one Text to Dialogue request, one or more script lines, at most 2,000 characters) or
  `sfx` (a sound effect played between lines).
- **Segment size (decided 2026-10-31):** Core splits dialogue at natural beats into segments of about
  3-6 lines and at most ~600 characters, so the player's per-segment highlight covers a few lines, not
  twenty. 2,000 characters stays the hard limit the validator enforces. Dialogue is priced per character,
  so smaller segments should not change the credit total; Core confirms this in Step 0.
- **Per-line timing (optional field `line_times_ms`, added 2026-10-31):** Core renders dialogue with
  `text_to_dialogue.convert_with_timestamps`, whose `voice_segments` give each input line a start and
  end time. Each dialogue segment then carries
  `"line_times_ms": [{"line_id": "s01-l001", "start_ms": 0, "end_ms": 4210}, ...]`, with times relative
  to the start of that segment's stem. The field may be missing (placeholder stems, or a line the API
  returned no timing for); then fall back to per-segment highlighting.
- Every script line appears in exactly one dialogue segment, in script order. Proof can rely on this.
- `beds` play *under* the segments, from the start of `from_segment` to the end of `to_segment`.
  `loop: true` means repeat the file to fill the span. `gain_db` is Core's suggested starting level;
  Surface owns the final levels. `duck_under_dialogue: true` asks Surface to lower that bed while dialogue plays.
- `flat_clip` is the before/after comparison: the same lines read by one voice as a plain audiobook.

## Stems (`stems/`)
```
stems/dialogue/<segment id>.<ext>
stems/sfx/<segment id>.<ext>
stems/beds/<bed id>.<ext>
stems/flat/flat.<ext>
```
- Real stems: MP3 as returned by ElevenLabs (exact format confirmed in Core Step 0, then recorded here).
- Placeholder stems: 44.1 kHz mono 16-bit WAV. Always take the path and extension from `segments.json`;
  never guess them.

## usage.jsonl (credit log for Proof)
One JSON object per line, appended for every ElevenLabs call, including cache hits:
```json
{"ts": "2026-10-31T14:02:11-04:00", "run_id": "2026-10-31T14-00-00", "feature": "dialogue",
 "endpoint": "text-to-dialogue", "model_id": "eleven_v4", "chars": 1834, "audio_ms": null,
 "credits_estimated": 1834, "credits_actual": null, "cache_hit": false,
 "item_id": "s01-d001", "output": "stems/dialogue/s01-d001.mp3"}
```
- `feature`: `dialogue`, `sfx`, `music`, `voice_design`, or `flat`. Ambience beds are sound-effect calls
  and are logged as `sfx` (their `item_id` is the bed id, e.g. `s01-amb`).
- `output` is relative to the folder holding `usage.jsonl`. A one-scene preview writes its stems under
  `preview-s01/`, so its rows read e.g. `preview-s01/stems/dialogue/s01-d001.mp3`.
- Core also keeps `pricing.json` next to `usage.jsonl` (layout below).

## pricing.json (prices Core estimates with)
```json
{
  "dialogue_credits_per_char": 1.0,
  "dialogue_basis": "assumed (1 credit per character x model multiplier)",
  "sfx_credits_per_call": 120,
  "ambience_credits_per_call": 240,
  "music_credits_per_call": 800
}
```
- `dialogue_credits_per_char` applies to `dialogue` and `flat` rows. Its `dialogue_basis` is either
  `"assumed (1 credit per character x model multiplier)"`, written by `step0` from the model's
  `character_cost_multiplier`, or `"measured"` once a dialogue call's balance change has been recorded.
- `sfx_credits_per_call`, `ambience_credits_per_call` and `music_credits_per_call` exist **only once
  measured** from the account balance before and after a real call, so they are always measured.
  A missing key means the price is still unknown. (Ambience calls are logged as `sfx` in usage.jsonl
  but priced under their own key, since a looping 20-second bed can cost differently from a short effect.)
- Measured values only go up: a later, lower reading never replaces a higher one, so estimates stay
  on the safe side.
- The numbers in the example are made up; read the real file.
- `credits_estimated` comes from Core's budget rules. `credits_actual` is filled only when Core can
  measure it (balance read before and after a call); otherwise it is `null`. Proof should report which
  of the two each number is based on.
- `credits_estimated` is `null` when Core has no cost rule for that feature yet (SFX and music until
  Core Step 0 confirms their pricing).
- Cache hits cost 0 credits and are logged with `cache_hit: true`.
- Placeholder logs add `"sample": true` to every row. Real logs never have it, so Proof can refuse samples.
- Claude API calls (the `adapt` step) are not ElevenLabs credits and are not logged here.

## Placeholder stems (before any credits are spent)
Any worktree can generate a full set of placeholder stems that match the sample files:
```
python -m core.placeholders --out output/placeholder
```
Run it from the repo root (Git Bash or PowerShell). It writes `script.json`, `voices.json`,
`segments.json`, a sample `usage.jsonl` and `stems/` into the given folder. Dialogue is a tone per
character, lasting about as long as the real line would; SFX are short noise bursts; beds are quiet
noise and a slow chord. `output/` is git-ignored, so nothing generated is committed.

## Where real output lives (decided by Jackson, 2026-10-31)
The three worktrees are separate folders and `output/` is git-ignored, so real stems are not shared
through git. Core writes the real output folder to a shared sibling of the worktrees:
```
C:\Users\raine\Projects\hack-or-treat\elevenlabs-shared\output\
```
- In code this is `core.config.output_dir()`: `../elevenlabs-shared/output` relative to the repo root,
  which resolves to the same folder from all three worktrees. Set `FULLCAST_OUTPUT_DIR` to override it.
- Only Core writes there. Surface and Proof read from it; anything they produce goes in their own
  folders (`web/`, `results/`).
- The parent `hack-or-treat` folder is not a git repo, so nothing in `elevenlabs-shared` gets committed.
