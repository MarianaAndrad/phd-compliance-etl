
from datetime import date
from enum import Enum
from typing import Annotated, List
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

#from schemas.control import ControlModel


class DocumentType(str, Enum):
    Standard = "standard"
    Framework = "framework"
    Directive = "directive"

class MetadataModel(BaseModel):
    """Metadata describing the origin and nature of a controls catalog."""
    model_config = ConfigDict(title="Metadata")

    type: DocumentType         = Field(..., title="Document Type", description="Nature of the document: a standard, a framework, or a regulatory directive.")
    name: str                  = Field(..., title="Name", description="Official name of the catalog (e.g. 'ISO/IEC 27001', 'NIST SP 800-53').")
    version: str | None        = Field(default=None, title="Version", description="Version or revision of the document (e.g. '2022', 'Rev 5'). Kept as string since it may contain non-numeric text.")
    language: str              = Field(default="en", title="Language", description="Language code of the document (e.g. 'en', 'pt').", min_length=2)
    published: date | None     = Field(default=None, title="Published Date", description="Original publication date of the document.")
    last_modified: date | None = Field(default=None, alias="last-modified", title="Last Modified", description="Date of the last modification/revision of the document.")
    publisher: str             = Field(..., title="Publisher", description="Entity responsible for publishing the document (e.g. 'ISO', 'NIST', 'CIS').")
    description: str           = Field(default="", title="Description", description="Free-text, optional description of the catalog's purpose or scope.")

    @field_validator("language")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        return v.lower()

class CatalogModel(BaseModel):
    """Represents a catalog of controls."""
    model_config = ConfigDict(title="Catalog")
    
    uuid: str               = Field(default_factory=lambda: str(uuid4()), title="UUID", description="Unique identifier for this catalog.")
    metadata: MetadataModel = Field(..., title="Metadata", description="Descriptive metadata for the catalog.")

    # NOTE: "groups" might be unnecessary in the context of DB storage? The control's "catalog_uuid" attribute should allow to retrieve catalog controls.
    #groups: List[ControlModel] = Field(default=[], description="The requirements/ controls belonging to the catalog.")
