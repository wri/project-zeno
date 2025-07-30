GADM_TABLE = "geometries_gadm"
KBA_TABLE = "geometries_kba"
LANDMARK_TABLE = "geometries_landmark"
WDPA_TABLE = "geometries_wdpa"


SUBREGION_TO_SUBTYPE_MAPPING = {
    "country": "country",
    "state": "state-province",
    "district": "district-county",
    "municipality": "municipality",
    "locality": "locality",
    "neighbourhood": "neighbourhood",
    "kba": "key-biodiversity-area",
    "wdpa": "protected-area",
    "landmark": "indigenous-and-community-land",
}


SOURCE_ID_MAPPING = {
    "kba": {"table": KBA_TABLE, "id_column": "sitrecid"},
    "landmark": {"table": LANDMARK_TABLE, "id_column": "landmark_id"},
    "wdpa": {"table": WDPA_TABLE, "id_column": "wdpa_pid"},
    "gadm": {"table": GADM_TABLE, "id_column": "gadm_id"},
}


# GADM LEVELS
GADM_LEVELS = {
    "country": {"col_name": "GID_0", "name": "iso"},
    "state-province": {"col_name": "GID_1", "name": "adm1"},
    "district-county": {"col_name": "GID_2", "name": "adm2"},
    "municipality": {"col_name": "GID_3", "name": "adm3"},
    "locality": {"col_name": "GID_4", "name": "adm4"},
    "neighbourhood": {"col_name": "GID_5", "name": "adm5"},
}

GADM_SUBTYPE_MAP = {val["col_name"]: key for key, val in GADM_LEVELS.items()}
