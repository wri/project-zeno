SOURCE_ID_MAPPING = {
    "kba": {"table": "geometries_kba", "id_column": "sitrecid"},
    "landmark": {"table": "geometries_landmark", "id_column": "gfw_fid"},
    "wdpa": {"table": "geometries_wdpa", "id_column": "wdpa_pid"},
    "gadm": {"table": "geometries_gadm", "id_column": None},  # GADM uses GID_X levels
}


GADM_SUBTYPE_MAP = {
    "GID_0": "country",
    "GID_1": "state-province",
    "GID_2": "district-county",
    "GID_3": "municipality",
    "GID_4": "locality",
    "GID_5": "neighbourhood",
}


def get_gadm_level(gadm_id: str) -> str:
    """
    Return the GADM level based on the GADM ID.

    GADM IDs are structured as follows:
    - Level 0: "GID_0"
    - Level 1: "GID_1"
    - Level 2: "GID_2"
    - Level 3: "GID_3"
    - Level 4: "GID_4"
    - Level 5: "GID_5"

    The number of dots in the GADM ID indicates the level:
    Level 0: No dots (e.g., AFG)
    Level 1: 1 dot (e.g., AFG.1_1)
    Level 2: 2 dots (e.g., AFG.1.2_1)
    Level 3: 3 dots (e.g., AFG.1.2.3_1)
    Level 4: 4 dots (e.g., AFG.1.2.3.4_1)
    Level 5: 5 dots (e.g., AFG.1.2.3.4.5_1) etc.

    These example IDs might not be real ids.
    """

    level = gadm_id.count(".")
    if level < 0 or level > 5:
        raise ValueError(f"Invalid GADM ID: {gadm_id}")
    gadm_level = f"GID_{level}"
    subtype = GADM_SUBTYPE_MAP.get(gadm_level)
    return gadm_level, subtype
