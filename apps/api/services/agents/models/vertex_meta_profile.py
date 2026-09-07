# apps/api/services/agents/models/vertex_meta_profile.py

"""JSON schema compatibility for Vertex's Llama Chat Completions API."""

import json
from typing import Any

from pydantic_ai.profiles import JsonSchemaTransformer


class VertexMetaJsonSchemaTransformer(JsonSchemaTransformer):
    def transform(self, schema: dict[str, Any]) -> dict[str, Any]:
        # Vertex Llama returns HTTP 500 for schema-valued additionalProperties.
        # Keep the value constraints visible to the model; Pydantic still enforces them.
        values = schema.get("additionalProperties")
        if isinstance(values, dict):
            constraint = json.dumps(values, separators=(",", ":"))
            description = schema.get("description", "")
            schema["description"] = (
                f"{description}\nEach additional property value must match: {constraint}"
            ).strip()
            schema["additionalProperties"] = True
        self.is_strict_compatible = False
        return schema
