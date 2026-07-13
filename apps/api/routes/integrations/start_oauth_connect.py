# apps/api/routes/integrations/start_oauth_connect.py

"""Start an integration OAuth connect handshake."""

from ipaddress import IPv6Address

from fastapi import APIRouter, Depends, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from core.rate_limiting import enforce_rate_limit
from services.integrations.connections import start_oauth_connect as start_oauth_connect_service
from services.integrations.connections.schemas import OAuthConnectRequest, OAuthConnectResponse

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/connections/oauth/start")
async def start_oauth_connect(
    request: Request,
    payload: OAuthConnectRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> OAuthConnectResponse:
    del request
    await enforce_rate_limit(
        subject_ip=str(IPv6Address(actor.id.int)),
        endpoint="/integrations/connections/oauth/start",
        custom_limit=10,
        custom_window=60,
    )
    workspace, membership = workspace_context
    return await start_oauth_connect_service(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
