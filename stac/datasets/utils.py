import io
import json
import os

from pypgstac.db import PgstacDB
from pypgstac.load import Loader, Methods
from pystac import Collection, Item


def get_loader():
    required_env_vars = [
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
    ]

    missing_vars = [var for var in required_env_vars if var not in os.environ]

    if missing_vars:
        raise EnvironmentError(
            f"Missing required environment variables for pgstac connection: {', '.join(missing_vars)}"
        )

    print(
        "All required environment variables for pgstac database connection are set."
    )

    db = PgstacDB()
    loader = Loader(db=db)

    return loader


def load_stac_data_to_db(collection: Collection, items: list[Item]):
    loader = get_loader()

    print("Loading collection to database")
    loader.load_collections(
        io.BytesIO(json.dumps(collection.to_dict()).encode("utf-8")),
        insert_mode=Methods.upsert,
    )

    for item in items:
        item.clear_links()

    print(f"Loading {len(items)} items to database")
    loader.load_items(
        (item.to_dict() for item in items),
        insert_mode=Methods.upsert,
    )
