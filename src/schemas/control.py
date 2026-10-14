from typing import Dict, List
from pydantic import BaseModel, ConfigDict, Field


class ControlModel(BaseModel):
    model_config = ConfigDict(title="Control", validate_assignment=True) # make pydantic validate fields when assigning after model creation (by default they are only validated on instantiation)

    catalog_uuid: str | None               = Field(default=None, title="Catalog UUID", description="UUID of the Catalog this control belongs to.")
    ref_code: str                          = Field(..., title="Reference Code", description="Official reference code of the control (e.g. 'A.5.1', 'AC-2').")
    title: str                             = Field(..., title="Title", description="Short title/name of the control.")
    slug: str                              = Field(..., title="Slug", description="Unique, human-readable, URL-friendly identifier for this control (e.g. '2.1-access-control').")
    parent_slug: str | None                = Field(default=None, title="Parent Slug", description="Slug of the parent control, if any. None for top-level controls.")
    category: str                          = Field(..., title="Category", description="Category of the control, normally the title of its root parent.")
    description: str                       = Field(default="", title="Description", description="General description of the control.")
    purpose: str                           = Field(default="", title="Purpose", description="Brief purpose/intent of the control.")
    guidance: str                          = Field(default="", title="Guidance", description="Implementation guidance. How to apply the control in practice.")
    other_information: str                 = Field(default="", title="Other Information", description="Field with some additional information, normally further reads.")
    means_of_verifiction: List[str]        = Field(default=[], title="Means of Verification", description="Ways to verify/audit compliance with this control.")
    attributes: List[Dict[str, List[str]]] = Field(default=[], title="Attributes", description="Tag-like attributes, each mapping a key to a list of values (e.g. [{'security-level': ['high']}]).")
    references: List[str]                  = Field(default=[], title="References", description="External documents referenced by this control (other standards, URLs, etc.).")
    citers: List[str] | None               = Field(default=[], title="Citers", description="Other documents that cite this control.")

    # NOTE: "groups" might be unnecessary in the context of DB storage? The "parent_slug" attribute should allow to retrieve child controls.
    # groups: List["ControlModel"] | List[str] = Field(default=[], description="Sub-controls or child controls of this control.")

#ControlModel.model_rebuild() # rebuild the model to resolve its forward reference ("ControlModel")
