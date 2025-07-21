-- Table modifications (SKIP - tables already have correct structure)
-- Uncomment these lines only if running on fresh tables that need schema updates:

/*
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
*/

------------------------------------------------------------
-- 1. Load spatial extension (install only once per database)
------------------------------------------------------------
INSTALL spatial;
LOAD   spatial;

------------------------------------------------------------
-- 2. Drop target table for repeatable runs
------------------------------------------------------------
-- Drop existing tables for clean rebuild
DROP TABLE IF EXISTS gadm_plus;
DROP TABLE IF EXISTS geometries;

------------------------------------------------------------
-- 3. Create separate geometry table for efficient storage
------------------------------------------------------------
CREATE OR REPLACE TABLE geometries AS
WITH all_geometries AS (
    -- GADM geometries
    SELECT
        'gadm' AS source,
        gadm_id AS src_id,
        geometry
    FROM gadm
    WHERE geometry IS NOT NULL
    
    UNION ALL
    
    -- KBA geometries
    SELECT
        'kba' AS source,
        kba_id AS src_id,
        geometry
    FROM kba
    WHERE geometry IS NOT NULL
    
    UNION ALL
    
    -- Landmark geometries
    SELECT
        'landmark' AS source,
        landmark_id AS src_id,
        geometry
    FROM landmark
    WHERE geometry IS NOT NULL
    
    UNION ALL
    
    -- WDPA geometries
    SELECT
        'wdpa' AS source,
        wdpa_id AS src_id,
        geometry
    FROM wdpa
    WHERE geometry IS NOT NULL
)
SELECT
    row_number() OVER () AS id,
    source,
    src_id,
    geometry
FROM all_geometries;

------------------------------------------------------------
-- 4. Drop geometry columns from individual tables (now stored centrally)
------------------------------------------------------------
-- Drop geometry columns to save space since geometry is now in dedicated table
ALTER TABLE gadm DROP COLUMN IF EXISTS geometry;
ALTER TABLE kba DROP COLUMN IF EXISTS geometry;
ALTER TABLE landmark DROP COLUMN IF EXISTS geometry;
ALTER TABLE wdpa DROP COLUMN IF EXISTS geometry;

------------------------------------------------------------
-- 5. Create main metadata table (without geometry)
------------------------------------------------------------
CREATE OR REPLACE TABLE gadm_plus AS
WITH unioned AS (

    ---------------------  GADM  ---------------------
    SELECT
        'gadm'              AS source,
        gadm_id             AS src_id,
        name,
        subtype,
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
-- 6. Create indexes for efficient lookups
------------------------------------------------------------
-- Index on geometry table for fast geometry lookups
CREATE INDEX IF NOT EXISTS geometries_lookup_idx
    ON geometries (source, src_id);

-- Spatial index on geometry table
CREATE INDEX IF NOT EXISTS geometries_geom_rtree
    ON geometries
    USING RTREE (geometry);

-- Index on main table for searches
CREATE INDEX IF NOT EXISTS gadm_plus_source_idx
    ON gadm_plus (source, src_id);









