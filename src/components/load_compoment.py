import json

from typing import Dict, List, Any

from pymongo import AsyncMongoClient

from core.config import settings

from schemas.catalog import CatalogModel, MetadataModel
from schemas.control import ControlModel

COMPLIANCE_DB_NAME = "complianceETL"

async def persist_catalog(mongodb_client: AsyncMongoClient, database_name: str, catalog: CatalogModel) -> str:

    '''catalog = await mongodb_client[database_name].get_collection(settings.DB_MONGO_CATALOGS_COLL).find_one(
        { "metadata.name": catalog.metadata.name }
    )
    #print(catalog)

    if catalog is None:
        metadata = MetadataModel(
            type="standard",
            name=framework_name,
            publisher="ISO/IEC"
        )
        catalog = CatalogModel(
            uuid=str(uuid4()),
            metadata=metadata
        )

        result = await mongodb_client[database_name].get_collection(settings.DB_MONGO_CATALOGS_COLL).insert_one(catalog.model_dump())
    else:
        catalog = CatalogModel(**catalog) # create pydantic model instance from raw python dict'''

    await mongodb_client[database_name].get_collection(settings.DB_MONGO_CATALOG_COLLECTION).update_one(
        {"metadata.name": catalog.metadata.name},
        {"$set": catalog.model_dump()},
        upsert=True,
    )

    return catalog.uuid


async def persist_controls(mongodb_client: AsyncMongoClient, database_name: str, catalog_uuid: str, controls_list: List[ControlModel]) -> None:
    """Upserts each control, keyed by (catalog_uuid, slug) so re-running the
    extraction on the same document does not create duplicates."""

    for control in controls_list:
        if not control.catalog_uuid:
            control.catalog_uuid = catalog_uuid
        payload = control.model_dump()
        await mongodb_client[database_name].get_collection(settings.DB_MONGO_CONTROL_COLLECTION).update_one(
            {"slug": payload["slug"]}, #{"catalog_uuid": catalog_uuid, "slug": payload["slug"]},
            {"$set": payload},
            upsert=True,
        )
    

async def persist_data(mongodb_client: AsyncMongoClient, framework_name: str, cdm_instances: Dict):
    global COMPLIANCE_DB_NAME

    catalog_uuid = await persist_catalog(mongodb_client, COMPLIANCE_DB_NAME, cdm_instances["catalog"])
    await persist_controls(mongodb_client, COMPLIANCE_DB_NAME, catalog_uuid, cdm_instances["controls_list"])


def load_cdm_instances(cdm_path: str) -> dict[str, CatalogModel | list[Any]]:
    json_data, controls_list, catalog = [], [], None
    
    with open(cdm_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    catalog = CatalogModel(**json_data["catalog"])
    for control in json_data["controls_list"]:
        controls_list.append(ControlModel(**control))

    return { "catalog": catalog, "controls_list": controls_list }