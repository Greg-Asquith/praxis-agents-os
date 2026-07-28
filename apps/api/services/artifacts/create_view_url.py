# apps/api/services/artifacts/create_view_url.py

"""Mint and verify short-lived artifact view capabilities."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from core.exceptions.general import NotFoundError
from core.settings import settings
from models.artifacts import Artifact
from services.artifacts.schemas import ArtifactViewUrl
from utils.security import create_hmac_signature, derive_purpose_key, verify_hmac_signature

_SIGNATURE_VERSION = "v1"
_SIGNATURE_PURPOSE = "praxis:artifact-view-url:v1"


def _signature_key() -> str:
    root = settings.SECRET_KEY.get_secret_value().encode("utf-8")
    return derive_purpose_key(root, _SIGNATURE_PURPOSE).hex()


def _payload(*, artifact_id: UUID, version_id: UUID, expires: int) -> str:
    return f"artifact-view:v1:{artifact_id}:{version_id}:{expires}"


def create_artifact_view_url(*, artifact: Artifact, version_id: UUID) -> ArtifactViewUrl:
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.ARTIFACT_VIEW_URL_TTL_SECONDS)
    expires = int(expires_at.timestamp())
    digest = create_hmac_signature(
        _payload(artifact_id=artifact.id, version_id=version_id, expires=expires),
        _signature_key(),
    )
    base = settings.ARTIFACT_ORIGIN or settings.APP_BASE_URL
    return ArtifactViewUrl(
        url=(
            f"{base}/artifacts/view/{artifact.id}/{version_id}"
            f"?expires={expires}&sig={_SIGNATURE_VERSION}.{digest}"
        ),
        expires_at=datetime.fromtimestamp(expires, tz=UTC),
    )


def require_valid_artifact_view_signature(
    *,
    artifact_id: UUID,
    version_id: UUID,
    expires: int,
    signature: str,
) -> None:
    if expires < int(datetime.now(UTC).timestamp()):
        raise NotFoundError("Artifact not found")
    prefix, separator, digest = signature.partition(".")
    if separator != "." or prefix != _SIGNATURE_VERSION or not digest:
        raise NotFoundError("Artifact not found")
    if not verify_hmac_signature(
        _payload(artifact_id=artifact_id, version_id=version_id, expires=expires),
        digest,
        _signature_key(),
    ):
        raise NotFoundError("Artifact not found")
