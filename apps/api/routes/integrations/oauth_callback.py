# apps/api/routes/integrations/oauth_callback.py

"""Complete integration OAuth after the provider returns to the frontend."""

from fastapi import APIRouter, Depends, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from core.exceptions.integration import IntegrationAuthError, IntegrationError
from core.rate_limiting import get_client_ip, require_rate_limit
from services.integrations.connections import complete_oauth_callback
from services.integrations.connections.schemas import OAuthCallbackRequest, OAuthCallbackResponse
from services.security import SecurityEventType, safe_record_security_event_committed

router = APIRouter(
    dependencies=[
        Depends(require_editor),
        Depends(require_rate_limit(custom_limit=20, custom_window=60)),
    ]
)


@router.post("/oauth/callback")
async def oauth_callback(
    request: Request,
    payload: OAuthCallbackRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> OAuthCallbackResponse:
    workspace, _membership = workspace_context
    client_ip = get_client_ip(request)
    try:
        return await complete_oauth_callback(
            db,
            actor=actor,
            workspace=workspace,
            code=payload.code,
            state=payload.state,
            provider_error=payload.error,
            ip_address=client_ip,
            endpoint=request.url.path,
        )
    except IntegrationError as exc:
        # Callback failures intentionally update connection/audit state. Persist
        # those changes before the typed exception becomes a problem response.
        await db.commit()
        if not (isinstance(exc, IntegrationAuthError) and exc.operation == "oauth_state"):
            await safe_record_security_event_committed(
                event_type=SecurityEventType.AUTH_OAUTH_FAILED,
                ip_address=client_ip,
                endpoint=request.url.path,
                details={"provider_key": exc.provider_key, "operation": exc.operation},
            )
        raise
