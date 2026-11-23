# apps/api/services/agents/runtime/tools/web/nodes.py

"""Provenance nodes for strings the remote server chose, shared by the HTTP web tools."""

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from services.agents.runtime.untrusted import UntrustedContent, UntrustedNode
from services.web.domain import RedirectHop

_SOURCE_KIND = "web_fetch"


class WebRedirect(BaseModel):
    url: UntrustedNode
    status: int
    location: UntrustedNode


def untrusted(source_ref: str, content: str) -> UntrustedContent:
    """Wraps server-chosen text, citing the requested URL as its source."""
    return UntrustedContent(source_kind=_SOURCE_KIND, source_ref=source_ref, content=content)


def redirect_nodes(source_ref: str, hops: Iterable[RedirectHop]) -> list[dict[str, Any]]:
    """Returns redirect hops with their URLs as nodes; a redirect target is server-chosen."""
    return [
        {
            "url": untrusted(source_ref, hop.url),
            "status": hop.status,
            "location": untrusted(source_ref, hop.location),
        }
        for hop in hops
    ]
