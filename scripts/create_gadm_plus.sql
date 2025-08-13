-- kba -> rename id to kba_id, add name using (natname, intname, iso3), add subtype
ALTER TABLE kba RENAME COLUMN id TO kba_id;

ALTER TABLE kba ADD COLUMN name VARCHAR;
UPDATE kba SET name = concat_ws(', ', natname, intname, iso3);

ALTER TABLE kba ADD COLUMN subtype VARCHAR;
UPDATE kba SET subtype = 'key-biodiversity-area';

-- landmark -> rename id to landmark_id, rename name to landmark_name, add name using (landmark_name, category, iso_code), add subtype
ALTER TABLE landmark RENAME COLUMN id TO landmark_id;
ALTER TABLE landmark RENAME COLUMN name TO landmark_name;

ALTER TABLE landmark ADD COLUMN name VARCHAR;
UPDATE landmark SET name = concat_ws(', ', landmark_name, category, iso_code);

ALTER TABLE landmark ADD COLUMN subtype VARCHAR;
UPDATE landmark SET subtype = 'indigenous-and-community-land';


-- wdpa -> rename id to wdpa_id, name to wdpa_name, add name using (wdpa_name, desig, iso3), add subtype
ALTER TABLE wdpa RENAME COLUMN id TO wdpa_id;
ALTER TABLE wdpa RENAME COLUMN name TO wdpa_name;

ALTER TABLE wdpa ADD COLUMN name VARCHAR;
UPDATE wdpa SET name = concat_ws(', ', wdpa_name, desig, iso3);

ALTER TABLE wdpa ADD COLUMN subtype VARCHAR;
UPDATE wdpa SET subtype = 'protected-area';

------------------------------------------------------------
-- 1. Load spatial extension (install only once per database)
------------------------------------------------------------
INSTALL spatial;
LOAD   spatial;

------------------------------------------------------------
-- 2. Drop target table for repeatable runs
------------------------------------------------------------
DROP TABLE IF EXISTS gadm_plus;

------------------------------------------------------------
-- 3. Stack the four layers, selecting *only* the desired columns
------------------------------------------------------------
CREATE OR REPLACE TABLE gadm_plus AS
WITH unioned AS (

    ---------------------  GADM  ---------------------
    SELECT
        'gadm'              AS source,
        gadm_id             AS src_id,
        name,
        subtype,
        geometry,
        /* provenance flags */
        TRUE                AS is_gadm,
        FALSE               AS is_kba,
        FALSE               AS is_landmark,
        FALSE               AS is_wdpa
    FROM gadm

    UNION ALL

    ---------------------  KBA   ---------------------
    SELECT
        'kba'               AS source,
        kba_id              AS src_id,
        name,
        subtype,
        geometry,
        FALSE               AS is_gadm,
        TRUE                AS is_kba,
        FALSE               AS is_landmark,
        FALSE               AS is_wdpa
    FROM kba

    UNION ALL

    ---------------------  Landmark  -----------------
    SELECT
        'landmark'          AS source,
        landmark_id         AS src_id,
        name,
        subtype,
        geometry,
        FALSE               AS is_gadm,
        FALSE               AS is_kba,
        TRUE                AS is_landmark,
        FALSE               AS is_wdpa
    FROM landmark

    UNION ALL

    ---------------------  WDPA  ---------------------
    SELECT
        'wdpa'              AS source,
        wdpa_id             AS src_id,
        name,
        subtype,
        geometry,
        FALSE               AS is_gadm,
        FALSE               AS is_kba,
        FALSE               AS is_landmark,
        TRUE                AS is_wdpa
    FROM wdpa
)
SELECT
    row_number() OVER () AS id,
    *
FROM unioned;

------------------------------------------------------------
-- 5. Optional: spatial index for faster spatial predicates
------------------------------------------------------------
CREATE INDEX IF NOT EXISTS gadm_plus_geom_rtree
    ON gadm_plus
    USING RTREE (geometry);
