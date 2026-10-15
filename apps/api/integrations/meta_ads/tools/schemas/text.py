# apps/api/integrations/meta_ads/tools/schemas/text.py

"""Shared text validators for Meta Ads tool inputs."""


def tidy_text(value: str) -> str:
    """Collapses runs of whitespace and refuses blank text."""
    if not value.strip():
        raise ValueError("Write some text.")
    return " ".join(value.split())
