# apps/api/services/media/video_tools_available.py

"""Reports whether this deployment can work with video a person attaches."""

# Chat accepts video only when an agent can find moments in it or cut it.
VIDEO_ATTACHMENT_TOOL_NAMES = ("cut_video_clips", "find_video_moments")


def video_tools_available() -> bool:
    """Checks whether a registered tool can find moments in or cut workspace video."""
    # The tool registry imports the files services, which call this check.
    from services.agents.runtime.tools.permissions import is_tool_allowed
    from services.agents.runtime.tools.registry import get_runtime_tool_definition

    for name in VIDEO_ATTACHMENT_TOOL_NAMES:
        definition = get_runtime_tool_definition(name)
        if definition is not None and is_tool_allowed(definition, workspace=None):
            return True
    return False
