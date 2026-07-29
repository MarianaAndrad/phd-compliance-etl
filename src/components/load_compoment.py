from typing import List

from motor.motor_asyncio import AsyncIOMotorDatabase

from schemas.catalog import Metadata
from schemas.control import Control


async def persist_metadata(db: AsyncIOMotorDatabase, catalog_uuid: str, metadata: Metadata) -> None:
    """Upserts the catalog-level metadata document."""

    await db.catalogs.update_one(
        {"uuid": catalog_uuid},
        {"$set": {"uuid": catalog_uuid, "metadata": metadata.model_dump(by_alias=True)}},
        upsert=True,
    )


async def persist_controls(db: AsyncIOMotorDatabase, catalog_uuid: str, controls: List[Control]) -> None:
    """Upserts each control, keyed by (catalog_uuid, slug) so re-running the
    extraction on the same document does not create duplicates."""

    for control in controls:
        await db.controls.update_one(
            {"catalog_uuid": catalog_uuid, "slug": control.slug},
            {"$set": control.model_dump()},
            upsert=True,
        )


async def persist_catalog(db: AsyncIOMotorDatabase, catalog_uuid: str, metadata: Metadata, controls: List[Control]) -> None:
    """Persists the full extraction result: metadata + flat controls."""

    await persist_metadata(db, catalog_uuid, metadata)
    await persist_controls(db, catalog_uuid, controls)