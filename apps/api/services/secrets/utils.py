# apps/api/services/secrets/utils.py

"""Private helpers shared by secrets providers."""

import hashlib
import re

from services.secrets.domain import validate_secret_name


def secret_environment_name(name: str) -> str:
    validate_secret_name(name)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return f"SECRET_{normalized}"


def gcp_secret_id(name: str) -> str:
    """Map a reference name to a collision-resistant GCP-safe identifier."""
    return cloud_secret_id(name)


def cloud_secret_id(name: str) -> str:
    """Map namespaced paths to a bounded, collision-resistant vault identifier."""
    validate_secret_name(name)
    return f"praxis-{hashlib.sha256(name.encode('utf-8')).hexdigest()}"
