# Video eval fixtures

The `video_*` cases in `evals/datasets/agent_behavior.yaml` use these, built
with the production code for a 45-minute pricing talk:

- `attached_video_pricing_talk.txt`: `video_attachment_note` for the talk,
  the text chat sends when a person attaches a video.
- `find_video_moments_pricing_talk.json`: a `find_video_moments` result with
  five moments, each built by the tool's `_moment_output`, so titles, hooks,
  reasons, and excerpts are untrusted nodes.

Rebuild them when the attachment note or the moments result changes, so the
evals show models what production returns.
