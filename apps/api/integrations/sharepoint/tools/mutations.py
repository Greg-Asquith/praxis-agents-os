# apps/api/integrations/sharepoint/tools/mutations.py

"""Validates the approved inputs for SharePoint folder and text writes."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from services.integrations.files import FileReference

from ..operations.write_utils import ItemName, TextContent, VersionToken, text_content_type
from ..references import SharePointDriveItemReference


class CreateFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: ItemName
    parent: SharePointDriveItemReference | None = None


class FileContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: TextContent | None = None
    source: FileReference | None = None

    @model_validator(mode="after")
    def validate_content_source(self) -> Self:
        if (self.content is None) == (self.source is None):
            raise ValueError("Provide either content or a source File.")
        return self


class WriteFileInput(FileContentInput):
    name: ItemName
    folder: SharePointDriveItemReference | None = None

    @model_validator(mode="after")
    def validate_text_name(self) -> Self:
        if self.content is not None:
            text_content_type(self.name, operation="write_file")
        return self


class UpdateFileInput(FileContentInput):
    file: SharePointDriveItemReference
    expected_version: VersionToken
