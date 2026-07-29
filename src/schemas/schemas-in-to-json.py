import json
import logging

from src.schemas.catalog import Metadata, Catalog
from src.schemas.control import Control

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

schemas = {}

for model in (Metadata, Control, Catalog):
    schema = model.model_json_schema()
    schemas[model.__name__] = schema

    logger.debug("%s\n%s %s %s", model.__name__, "=" * 20, model.__name__, "=" * 20)
    logger.debug(json.dumps(schema, indent=2))

with open("extraction_schema.json", "w") as f:
    json.dump(schemas, f, indent=2)

logger.info("Schemas written to schemas.json")
