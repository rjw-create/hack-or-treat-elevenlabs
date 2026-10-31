# Full Cast demo script (2:30)

Recorded as a screen capture of the player page plus voiceover. The before/after toggle is the hook,
so it comes first and comes back at the end.

Before recording:
- Mix the real render: `python -m web.mix --src ../elevenlabs-shared/output --out output/mix/real`
- Serve it: `python -m web.serve`, open http://127.0.0.1:8000/web/?mix=real
- Browser at a normal desktop width, zoom 125% so the script is readable in the video.
- System audio captured; voiceover recorded separately and kept quieter than the drama.
- Replace every `[TBD: ...]` below with the measured number, or cut the sentence.

| Time | On screen | Voiceover |
| --- | --- | --- |
| 0:00-0:15 | Player loaded, **Before: one voice** selected. Press play on the opening. | "This is the opening of The Monkey's Paw, read the way most audiobooks are: one voice, no sound." |
| 0:15-0:35 | Click **After: full cast** while it plays. The audio jumps to about the same point (the position is scaled, not matched word for word) with six voices, the fire and the wind. | "Same lines. Now every character has their own voice, and the room has a sound." |
| 0:35-0:50 | Let it play. Point at the highlighted line moving down the script. | "The script follows along, one line at a time, using the line timings ElevenLabs returns with the dialogue." |
| 0:50-1:20 | Click the chapter for scene 3, **The knocking** (chapter titles come from Core's `segments.json`; scene titles are "The paw", "The visitor", "The knocking"). Let the knocking play. | "Full Cast took a 1902 short story and made a five-minute radio drama from it: three scenes, six voices. ElevenLabs Text to Dialogue voices the scenes, several lines per request, so the speakers react to each other. Sound effects and ambience come from short text cues." |
| 1:20-1:45 | Cut to `docs/2026-10-31-interface.md` scrolled to `segments.json`, then back to the player. | "The pieces are planned as data: which clips play in what order, with what pause, and what sits underneath. The mixer measures each clip, lays them end to end, and lowers the drone when someone speaks." |
| 1:45-2:05 | Terminal: output of `python -m evals.credits`, budget line visible. | "We had ten thousand credits. That is why this is an abridged five-minute version, not the whole story. The final render used `[TBD: credits]`, and every clip is cached so nothing is paid for twice." |
| 2:05-2:20 | Back to the player, Part I. Toggle **Before**, then **After**, on one line of dialogue. | "One voice. Full cast." |
| 2:20-2:30 | Title and byline on screen. | "Full Cast. The Monkey's Paw by W. W. Jacobs, public domain. Voices and sound by ElevenLabs." |

## Notes
- If the video must be under 2:00, cut the 1:20-1:45 interface shot and shorten the credit line.
- Keep claims to what the video shows. No listener-rating numbers unless Proof's results are in
  `results/` and quoted with their sample size.
- The adaptation was written with Claude Code in the session, not by an API call at run time. If asked,
  say so.
