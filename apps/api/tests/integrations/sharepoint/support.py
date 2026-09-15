# apps/api/tests/integrations/sharepoint/support.py

"""SharePoint transport and active-context fixtures."""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx2

from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token


def fixture(name):
    return json.loads((Path(__file__).with_name("fixtures") / name).read_text())


@asynccontextmanager
async def graph(handler):
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        yield MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="sharepoint", client=transport
        )


def entry(drive_id="drive"):
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="sharepoint",
        resource_type="sharepoint_drive",
        external_id=drive_id,
        display_name="Documents",
        connection_id=uuid4(),
        connection_label="SharePoint",
        connection_status="active",
        write_allowed=False,
    )


def context(*entries):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            db=object(),
            user=object(),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Document agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="sharepoint_list_folder",
        tool_call_id="call-1",
    )
