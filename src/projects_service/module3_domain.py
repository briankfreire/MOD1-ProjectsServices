"""Public artifact metadata and bounded provider shapes, without storage paths."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

ExternalId = Annotated[int, Field(strict=True, ge=1, le=9007199254740991)]
ArtifactType = Literal["PDF", "MARKDOWN", "PNG", "JPEG"]
PUBLIC_LIMIT = 100


class ExternalProject(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)
    id: ExternalId
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)


class ArtifactItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)
    id: ExternalId
    project_id: ExternalId
    name: str = Field(min_length=1, max_length=300)
    artifact_type: ArtifactType
    version: ExternalId
    created_at: datetime = Field(strict=False)


class ArtifactVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)
    id: ExternalId
    artifact_id: ExternalId
    version_number: ExternalId
    created_at: datetime = Field(strict=False)


class ProjectList(RootModel[list[ExternalProject]]):
    root: list[ExternalProject] = Field(max_length=1000)


class ArtifactList(RootModel[list[ArtifactItem]]):
    root: list[ArtifactItem] = Field(max_length=1000)


class VersionList(RootModel[list[ArtifactVersion]]):
    root: list[ArtifactVersion] = Field(max_length=1000)


class ArtifactCatalog(BaseModel):
    enabled: bool = True
    items: list[ExternalProject] = Field(default_factory=list, max_length=PUBLIC_LIMIT)
    total: int = 0
    truncated: bool = False


class ArtifactPage(BaseModel):
    enabled: bool = True
    module3_project_id: ExternalId | None = None
    items: list[ArtifactItem] = Field(default_factory=list, max_length=PUBLIC_LIMIT)
    total: int = 0
    truncated: bool = False


class VersionPage(BaseModel):
    module3_project_id: ExternalId
    artifact_id: ExternalId
    items: list[ArtifactVersion] = Field(max_length=PUBLIC_LIMIT)
    total: int
    truncated: bool = False


@dataclass(frozen=True)
class ArtifactDownload:
    content: bytes
    filename: str
