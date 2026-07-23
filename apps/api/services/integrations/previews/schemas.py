# apps/api/services/integrations/previews/schemas.py

"""Response contracts for integration content previews."""

from typing import Any, Literal

from pydantic import BaseModel


class IntegrationPreviewRead(BaseModel):
    kind: str
    content_type: Literal["html", "text"]
    content: str
    meta: dict[str, Any]
