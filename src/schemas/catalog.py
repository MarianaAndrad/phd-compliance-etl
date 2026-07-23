
from datetime import date
from enum import Enum
from typing import Annotated, List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.control import Control


class DocumentType(str, Enum):
    Standard = "standard"
    Framework = "framework"
    Directive = "directive"


class Metadata(BaseModel):
    """Metadata describing the origin and nature of a controls catalog."""

    model_config = ConfigDict(title="Metadata", populate_by_name=True)

    type: DocumentType = Field(
        ...,
        title="Document Type",
        description="Nature of the document: a standard, a framework, or a regulatory directive.",
    )
    name: str = Field(
        ...,
        title="Name",
        description="Official name of the catalog (e.g. 'ISO/IEC 27001', 'NIST SP 800-53').",
    )
    version: str = Field(
        ...,
        title="Version",
        description="Version or revision of the document (e.g. '2022', 'Rev 5'). "
        "Kept as string since it may contain non-numeric text.",
    )
    language: str = Field(
        ...,
        title="Language",
        description="Language code of the document (e.g. 'en', 'pt').",
        min_length=2,
    )
    published: date = Field(
        ...,
        title="Published Date",
        description="Original publication date of the document.",
    )
    last_modified: Annotated[
        date,
        Field(
            alias="last-modified",
            title="Last Modified",
            description="Date of the last modification/revision of the document.",
        ),
    ]
    publisher: str = Field(
        ...,
        title="Publisher",
        description="Entity responsible for publishing the document (e.g. 'ISO', 'NIST', 'CIS').",
    )
    description: str = Field(
        default="",
        title="Description",
        description="Free-text, optional description of the catalog's purpose or scope.",
    )

    @field_validator("language")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        return v.lower()

class Catalog(BaseModel):
    """Represents a full controls catalog, preserving its original hierarchical structure."""

    model_config = ConfigDict(title="Catalog")
    uuid: str = Field(
        ...,
        title="UUID",
        description="Unique identifier for this catalog.",
    )
    metadata: Metadata = Field(
        ...,
        title="Metadata",
        description="Descriptive metadata for the catalog.",
    )
    groups: List[Control] = Field(
        default_factory=list,
        description="The requirements/ controls belonging to the catalog.",
    )
