# apps/api/tests/services/media/test_renderer_contract.py

"""The API's operation limits and names match the renderer's, which lives in its own image."""

import ast
from pathlib import Path
from typing import get_args

from services.media import domain

RENDERER_MEDIA = Path(__file__).resolve().parents[4] / "renderer" / "media"
# API name: renderer name, where they differ.
RENAMED = {
    "DEFAULT_FRAME_EDGE_PX": "DEFAULT_MAX_EDGE_PX",
    "MAX_CUT_SEGMENTS": "MAX_SEGMENTS",
    "MAX_CUT_SHOT_CUTS": "MAX_SHOT_CUTS",
    "MAX_CUT_KEEP_RANGES": "MAX_KEEP_RANGES",
}
SHARED = (
    "MAX_SCENE_CUTS",
    "MIN_SCENE_THRESHOLD",
    "MAX_SCENE_THRESHOLD",
    "MAX_FRAMES",
    "MIN_FRAME_EDGE_PX",
    "MAX_FRAME_EDGE_PX",
    "DEFAULT_FRAME_EDGE_PX",
    "MAX_AUDIO_CHUNKS",
    "MAX_CUT_SEGMENTS",
    "MAX_CUT_SHOT_CUTS",
    "MAX_CUT_KEEP_RANGES",
    "MIN_OUTPUT_EDGE_PX",
    "MAX_OUTPUT_EDGE_PX",
    "MIN_OUTPUT_FPS",
    "MAX_OUTPUT_FPS",
    "MIN_TRANSITION_MS",
    "MAX_TRANSITION_MS",
    "MAX_FADE_MS",
)


def _renderer_constants() -> dict[str, object]:
    """Reads literal module constants from the renderer's source without importing it."""
    constants: dict[str, object] = {}
    for path in RENDERER_MEDIA.glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)):
                continue
            value = node.value
            wrap = isinstance(value, ast.Call) and getattr(value.func, "id", None) == "frozenset"
            try:
                literal = ast.literal_eval(value.args[0] if wrap else value)
            except (ValueError, IndexError):
                continue
            constants[node.targets[0].id] = frozenset(literal) if wrap else literal
    return constants


def test_api_limits_and_names_match_the_renderers() -> None:
    renderer = _renderer_constants()

    assert {name: getattr(domain, name) for name in SHARED} == {
        name: renderer[RENAMED.get(name, name)] for name in SHARED
    }
    assert set(get_args(domain.TransitionStyle)) == renderer["XFADE_STYLES"] | {
        renderer["NO_TRANSITION"]
    }
    assert set(get_args(domain.AudioCurve)) == renderer["ACROSSFADE_CURVES"]
