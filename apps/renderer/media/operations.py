# apps/renderer/media/operations.py

"""The media operations the renderer offers; each module builds its own command lines."""

from driver.server import Operation

from media.cut import cut_input_count, run_cut, validate_cut
from media.extract_audio import run_extract_audio, validate_extract_audio
from media.ffmpeg import check_arguments, probe_file
from media.frames import run_frames, validate_frames
from media.scene_cuts import run_scene_cuts, validate_scene_cuts

OPERATIONS: dict[str, Operation] = {
    "probe": Operation(
        validate=lambda arguments: check_arguments(arguments, required={}),
        output_count=lambda arguments: 0,
        # Container metadata can sit anywhere in the file, so probe the whole input.
        run=lambda context, arguments: probe_file(context, context.fetch_input().name),
    ),
    "scene_cuts": Operation(
        validate=validate_scene_cuts, output_count=lambda arguments: 0, run=run_scene_cuts
    ),
    "cut": Operation(
        validate=validate_cut,
        output_count=lambda arguments: 1,
        run=run_cut,
        input_count=cut_input_count,
    ),
    "extract_audio": Operation(
        validate=validate_extract_audio,
        output_count=lambda arguments: arguments.get("chunks", 1),
        run=run_extract_audio,
    ),
    "frames": Operation(
        validate=validate_frames,
        output_count=lambda arguments: len(arguments["times_ms"]),
        run=run_frames,
    ),
}
