# Submission draft: Full Cast

Draft text for the Hack or Treat submission form, category **Best Project Built With ElevenLabs**.
Paste each section into the matching field. Fill or cut every `[TBD: ...]` before submitting.

## Name
Full Cast

## One-line description
A public-domain ghost story turned into a five-minute audio drama with a full voice cast, sound
effects and ambience, and a player that lets you switch between a plain audiobook and the full cast.

## What it does
Full Cast adapts "The Monkey's Paw" (W. W. Jacobs, 1902) into a short radio-style drama in three
scenes and 49 lines. Each of the six characters has their own ElevenLabs voice, scenes are voiced with Text to Dialogue so the speakers react
to each other, and sound effects and ambience are generated from short text cues. A mixer places every
clip in order, loops ambience under each scene and lowers a low theme drone while people speak. The player
shows the script following along, has a chapter list, and has a before/after toggle that jumps between
a one-voice reading and the full cast at the same moment.

## How we built it
- **Adaptation:** written with Claude Code during the session and checked by hand. Lines carry
  ElevenLabs audio tags for delivery, such as `[whispers]`.
- **Voices:** six premade ElevenLabs library voices, matched to written character descriptions. No cloned voices.
- **Dialogue:** ElevenLabs Text to Dialogue, several lines per request.
- **Sound:** ElevenLabs sound effects from text cues, for the effects, the ambience under each scene and
  a low theme drone. There is no composed music.
- **Mix:** Python and FFmpeg. The mixer reads a plan (`segments.json`), measures each clip and builds
  one FFmpeg filter graph. The drone ducks under dialogue, following the dialogue timeline.
- **Player:** one static HTML page, no framework.
- **Checks:** scripts confirm every line is spoken once and in order, check every clip for silence,
  clipping and loudness, and report credit use. None of them spend credits. A listener A/B form
  (one voice against the full cast) is ready but has not been run, so we report no listener ratings.
- **Team setup:** three Claude Code sessions worked in parallel (pipeline, mix and story, measurement),
  each in its own git worktree, joined by a written interface.

## Budget and scope
We had 10,000 ElevenLabs credits. That set the scope: the drama is an abridged version of about five
minutes, not the full story. Every generated clip is cached so nothing is generated twice. The final
render used `[TBD: credits, from python -m evals.credits]` credits for `[TBD: length]` of finished audio.

## Challenges
- Keeping a long multi-voice render inside a fixed credit budget: the script length was cut to fit
  before anything was generated.
- Timing without timestamps: clips have no fixed start times, so the mixer measures each one and builds
  the timeline itself. The script highlighting comes from that same timeline, using the per-line times
  ElevenLabs returns with the dialogue, so the line being spoken is highlighted.
- A local-server problem: Python's built-in server can't serve partial files, so the browser couldn't
  seek in the audio. We wrote a small server that can.

## What's next
- Word-level highlighting, if the dialogue timing data is fine-grained enough. Today it is line by line.
- More public-domain stories through the same pipeline.

## Links
- Code: `[TBD: repository URL, if it is made public]`
- Demo video: `[TBD]`

## Credits
"The Monkey's Paw" by W. W. Jacobs (1863-1943), first published 1902, public domain. Abridged for this
adaptation. Voices, sound effects, ambience and the theme drone generated with ElevenLabs.
