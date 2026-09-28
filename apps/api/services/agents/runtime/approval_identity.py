"""Derives approval identities from saved suspensions without changing native IDs."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from uuid import UUID, uuid5

from core.exceptions.general import ConflictError

APPROVAL_BATCH_KEY = "approval_batch_id"
APPROVAL_REVISION_KEY = "approval_revision"
_APPROVAL_NAMESPACE = UUID("66a8e790-f54c-49d4-a8ab-c593d46592fd")
MAX_PROPOSAL_BYTES = 4 * 1024 * 1024
MAX_PROJECTION_LEAVES = 1024


def validate_approval_identity_metadata(raw: Mapping[str, object]) -> UUID:
    """Returns the saved batch and rejects a missing batch or malformed revision."""
    if APPROVAL_REVISION_KEY in raw:
        revision = raw[APPROVAL_REVISION_KEY]
        if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None:
            raise invalid_approval_state("Invalid saved approval revision")
    value = raw.get(APPROVAL_BATCH_KEY)
    if not isinstance(value, str):
        raise invalid_approval_state("Invalid saved approval batch")
    try:
        return UUID(value)
    except ValueError as exc:
        raise invalid_approval_state("Invalid saved approval batch") from exc


def approval_id(
    *,
    owner_run_id: UUID,
    batch_id: UUID,
    tool_call_id: str,
    parent_tool_call_id: str | None = None,
) -> str:
    """Identifies one owning run and native leaf path within one suspension."""
    path = [str(batch_id), str(owner_run_id), parent_tool_call_id, tool_call_id]
    return str(uuid5(_APPROVAL_NAMESPACE, json.dumps(path, separators=(",", ":"))))


def proposal_digest(value: object) -> str:
    """Hashes bounded canonical server data without exposing its content."""
    digest = hashlib.sha256()
    size = 0
    try:
        chunks = json.JSONEncoder(
            sort_keys=True, separators=(",", ":"), allow_nan=False
        ).iterencode(value)
        for chunk in chunks:
            encoded = chunk.encode("utf-8")
            size += len(encoded)
            if size > MAX_PROPOSAL_BYTES:
                raise invalid_approval_state("Saved approval proposal exceeds its size limit")
            digest.update(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise invalid_approval_state("Saved approval proposal is not valid JSON") from exc
    return digest.hexdigest()


def approval_revision(
    *, root_run_id: UUID, root_batch_id: UUID, leaves: Sequence[Mapping[str, object]]
) -> str:
    """Fingerprints immutable proposals; human edits are intentionally not inputs."""
    if len(leaves) > MAX_PROJECTION_LEAVES:
        raise invalid_approval_state("Saved approval projection has too many leaves")
    return proposal_digest(
        {
            "root_run_id": str(root_run_id),
            "root_batch_id": str(root_batch_id),
            "leaves": sorted(leaves, key=lambda leaf: str(leaf["approval_id"])),
        }
    )


def invalid_approval_state(message: str) -> ConflictError:
    return ConflictError(
        message, conflicting_resource="agent_run", details={"error_code": "invalid_approval_state"}
    )
