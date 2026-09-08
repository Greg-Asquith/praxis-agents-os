# apps/api/integrations/outlook_mail/operations/search_people.py

"""Frames bounded results from the shared Graph people search."""

from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.microsoft_graph import MicrosoftGraphClient
from services.integrations.microsoft_graph.people import search_people as graph_search_people


async def search_people(client: MicrosoftGraphClient, *, query: str, limit: int = 10) -> list[dict]:
    if not 1 <= len(query.strip()) <= 100 or not 1 <= limit <= 25:
        raise ValueError("People search requires 1-100 query characters and a limit of 1-25")
    people = await graph_search_people(client, query=query, limit=limit)
    return [
        {
            key: UntrustedNode(
                source_kind="outlook_person", source_ref=address, content=value[:bound]
            )
            for key, value, bound in (
                ("name", name, 500),
                ("address", address, 320),
                ("job_title", job_title, 500),
                ("department", department, 500),
            )
        }
        for name, address, job_title, department in people[:limit]
    ]
