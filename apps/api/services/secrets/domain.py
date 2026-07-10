# apps/api/services/secrets/domain.py

"""Provider-neutral secret-reference value types."""

import re
from dataclasses import dataclass

from core.exceptions.integration import IntegrationValidationError

SECRET_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_/-]{1,255}$")


def validate_secret_name(name: str) -> str:
    """Validate a caller-namespaced secret name without accepting path traversal."""
    if not SECRET_NAME_PATTERN.fullmatch(name) or "//" in name or name.startswith("/"):
        raise IntegrationValidationError(
            "Invalid secret name",
            provider_key="secrets",
            operation="validate_secret_name",
        )
    return name


@dataclass(frozen=True)
class SecretReference:
    provider: str
    name: str
    version: str

    def __post_init__(self) -> None:
        validate_secret_name(self.name)
        if not self.provider.strip() or not self.version.strip():
            raise IntegrationValidationError(
                "Secret reference provider and version are required",
                provider_key=self.provider or "secrets",
                operation="validate_secret_reference",
            )

    def render(self) -> str:
        return f"{self.provider}:{self.name}#{self.version}"
