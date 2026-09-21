# apps/api/integrations/sharepoint/tools/mutations.py

"""Validates the approved inputs for SharePoint folder and text writes."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from ..operations.write_utils import ItemName, TextContent, VersionToken, text_content_type
from ..references import SharePointDriveItemReference


class CreateFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: ItemName
    parent: SharePointDriveItemReference | None = None


class WriteFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: ItemName
    content: TextContent
    folder: SharePointDriveItemReference | None = None

    @model_validator(mode="after")
    def validate_text_name(self) -> Self:
        text_content_type(self.name, operation="write_file")
        return self


class UpdateFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    file: SharePointDriveItemReference
    expected_version: VersionToken
    content: TextContent
