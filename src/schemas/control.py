from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

class Control(BaseModel):
    model_config = ConfigDict(title="Control")

    # catalog_uuid: str = Field(
    #     ...,
    #     title="Catalog UUID",
    #     description="UUID of the Catalog this control belongs to.",
    # )

    ref_code: str = Field(
        ...,
        title="Reference Code",
        description="Official reference code of the control (e.g. 'A.5.1', 'AC-2').",
    )

    title: str = Field(
        ...,
        alias="title",
        title="Title",
        description="Short title/name of the control.",
    )

    slug: str = Field(
        ...,
        title="Slug",
        description="Unique, human-readable, URL-friendly identifier for this control (e.g. 'access-control', 'data-encryption')."
    )

    parent_slug: Optional[str] = Field(
        default=None,
        title="Parent Slug",
        description="Slug of the parent control, if any. None for top-level controls.",
    )

    description: str = Field(
        ...,
        title="Description",
        description="General description of the control.",
    )

    purpose: str = Field(
        default="",
        title="Purpose",
        description="Purpose/intent of the control — why it exists.",
    )

    guidance: str = Field(
        default="",
        title="Guidance",
        description="Implementation guidance — how to apply the control in practice.",
    )

    other_information: str = Field(
        default="",
        title="Other Information",
        description="Catch-all field for additional information not covered elsewhere.",
    )

    means_of_verification: List[str] = Field(
        default_factory=list,
        title="Means of Verification",
        description="Ways to verify/audit compliance with this control.",
    )

    attributes: List[Dict[str, List[str]]] = Field(
        default_factory=list,
        title="Attributes",
        description="Tag-like attributes, each mapping a key to a list of values "
        "(e.g. [{'security-level': ['high']}]).",
    )


    # TODO REVIEW THIS
    # references: List[str] = Field(
    #     default_factory=list,
    #     title="References",
    #     description="External/cross references (other standards, URLs, etc.).",
    # )
    #
    # citer: str = Field(
    #     default="",
    #     title="Citer",
    #     description="TODO: clarify meaning — who/what cites or references this control.",
    # )

    groups: List["Control"] = Field(default_factory=list, description="Sub-controls or child controls of this control.")

Control.model_rebuild()
