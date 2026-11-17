# Video eval fixtures

The `video_*` cases in `evals/datasets/agent_behavior.yaml` use these, built
with the production code for a 45-minute pricing talk:

- `attached_video_pricing_talk.txt`: `video_attachment_note` for the talk,
  the text chat sends when a person attaches a video.
- `find_video_moments_pricing_talk.json`: a `find_video_moments` result with
  five moments, each built by the tool's `_moment_output`, so titles, hooks,
  reasons, and excerpts are untrusted nodes.
- `ask_video_transition_glitch.json`: an `ask_video` result for a reel cut
  from the talk, whose answer (an untrusted node) describes a split-frame
  tear at a wipe between two white screens. It mirrors the owner test of
  2026-10-13, where a clean wipe was described this way.

- `attached_audio_track.txt`: `media_attachment_note` for an attached MP3,
  the note chat sends with an audio File.
- `cut_video_clips_discounts_reel.json`: a `cut_video_clips` result for one
  9:16 reel cut from the talk with pause removal.

Rebuild them when the attachment note or a tool's result changes, so the
evals show models what production returns.
