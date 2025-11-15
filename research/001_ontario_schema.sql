-- Ontario Nature Watch Database Schema
-- Migration: 001_ontario_schema.sql
-- Description: Create Ontario-specific tables for protected areas, conservation authorities, watersheds, etc.

-- Enable PostGIS if not already enabled
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm; -- For fuzzy text search

-- ============================================================================
-- ONTARIO PROVINCIAL PARKS
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_provincial_parks (
    id SERIAL PRIMARY KEY,
    park_id VARCHAR(50) UNIQUE,
    park_name VARCHAR(255) NOT NULL,
    park_class VARCHAR(50), -- Wilderness, Natural Environment, Waterway, etc.
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    size_ha NUMERIC,
    regulation_date DATE,
    operating_season VARCHAR(100),
    facilities JSONB, -- JSON array of facilities: camping, trails, etc.
    website VARCHAR(255),
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for parks
CREATE INDEX idx_ont_parks_geom ON ontario_provincial_parks USING GIST(geometry);
CREATE INDEX idx_ont_parks_name ON ontario_provincial_parks USING GIN(park_name gin_trgm_ops);
CREATE INDEX idx_ont_parks_class ON ontario_provincial_parks(park_class);

-- ============================================================================
-- ONTARIO CONSERVATION RESERVES
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_conservation_reserves (
    id SERIAL PRIMARY KEY,
    reserve_id VARCHAR(50) UNIQUE,
    reserve_name VARCHAR(255) NOT NULL,
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    size_ha NUMERIC,
    regulation_date DATE,
    purpose TEXT,
    management_plan VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ont_reserves_geom ON ontario_conservation_reserves USING GIST(geometry);
CREATE INDEX idx_ont_reserves_name ON ontario_conservation_reserves USING GIN(reserve_name gin_trgm_ops);

-- ============================================================================
-- ONTARIO CONSERVATION AUTHORITIES
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_conservation_authorities (
    id SERIAL PRIMARY KEY,
    authority_id VARCHAR(50) UNIQUE,
    authority_name VARCHAR(255) NOT NULL,
    acronym VARCHAR(10),
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    jurisdiction_area_ha NUMERIC,
    watershed_count INTEGER,
    municipalities_served TEXT[], -- Array of municipality names
    programs JSONB, -- JSON object of programs/services
    contact_email VARCHAR(255),
    website VARCHAR(255),
    established_year INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ont_ca_geom ON ontario_conservation_authorities USING GIST(geometry);
CREATE INDEX idx_ont_ca_name ON ontario_conservation_authorities USING GIN(authority_name gin_trgm_ops);
CREATE INDEX idx_ont_ca_acronym ON ontario_conservation_authorities(acronym);

-- ============================================================================
-- ONTARIO WATERSHEDS
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_watersheds (
    id SERIAL PRIMARY KEY,
    watershed_id VARCHAR(50) UNIQUE,
    watershed_name VARCHAR(255) NOT NULL,
    watershed_code VARCHAR(50),
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    area_ha NUMERIC,
    primary_drainage VARCHAR(100), -- Lake Ontario, Lake Huron, etc.
    conservation_authority_id INTEGER REFERENCES ontario_conservation_authorities(id),
    tertiary_watershed VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ont_watersheds_geom ON ontario_watersheds USING GIST(geometry);
CREATE INDEX idx_ont_watersheds_name ON ontario_watersheds USING GIN(watershed_name gin_trgm_ops);
CREATE INDEX idx_ont_watersheds_ca ON ontario_watersheds(conservation_authority_id);

-- ============================================================================
-- ONTARIO MUNICIPALITIES
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_municipalities (
    id SERIAL PRIMARY KEY,
    municipality_id VARCHAR(50) UNIQUE,
    municipality_name VARCHAR(255) NOT NULL,
    municipality_type VARCHAR(50), -- City, Town, Township, Village, etc.
    county VARCHAR(100),
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    area_ha NUMERIC,
    population INTEGER,
    upper_tier VARCHAR(255), -- For two-tier municipalities
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ont_municipalities_geom ON ontario_municipalities USING GIST(geometry);
CREATE INDEX idx_ont_municipalities_name ON ontario_municipalities USING GIN(municipality_name gin_trgm_ops);
CREATE INDEX idx_ont_municipalities_county ON ontario_municipalities(county);

-- ============================================================================
-- ONTARIO FOREST MANAGEMENT UNITS
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_forest_management_units (
    id SERIAL PRIMARY KEY,
    fmu_id VARCHAR(50) UNIQUE,
    fmu_name VARCHAR(255) NOT NULL,
    fmu_code VARCHAR(10),
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    area_ha NUMERIC,
    management_company VARCHAR(255),
    plan_start_year INTEGER,
    plan_end_year INTEGER,
    plan_document_url VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ont_fmus_geom ON ontario_forest_management_units USING GIST(geometry);
CREATE INDEX idx_ont_fmus_name ON ontario_forest_management_units USING GIN(fmu_name gin_trgm_ops);
CREATE INDEX idx_ont_fmus_code ON ontario_forest_management_units(fmu_code);

-- ============================================================================
-- ONTARIO WATER BODIES
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_waterbodies (
    id SERIAL PRIMARY KEY,
    waterbody_id VARCHAR(50) UNIQUE,
    waterbody_name VARCHAR(255),
    waterbody_type VARCHAR(50), -- Lake, River, Stream, Pond
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    surface_area_ha NUMERIC,
    perimeter_km NUMERIC,
    great_lake BOOLEAN DEFAULT FALSE, -- Is this one of the Great Lakes?
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ont_water_geom ON ontario_waterbodies USING GIST(geometry);
CREATE INDEX idx_ont_water_name ON ontario_waterbodies USING GIN(waterbody_name gin_trgm_ops);
CREATE INDEX idx_ont_water_type ON ontario_waterbodies(waterbody_type);
CREATE INDEX idx_ont_water_great_lake ON ontario_waterbodies(great_lake) WHERE great_lake = TRUE;

-- ============================================================================
-- ONTARIO WETLANDS
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_wetlands (
    id SERIAL PRIMARY KEY,
    wetland_id VARCHAR(50) UNIQUE,
    wetland_name VARCHAR(255),
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    area_ha NUMERIC,
    wetland_type VARCHAR(50), -- Marsh, Swamp, Bog, Fen
    provincial_significance BOOLEAN DEFAULT FALSE,
    evaluated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ont_wetlands_geom ON ontario_wetlands USING GIST(geometry);
CREATE INDEX idx_ont_wetlands_name ON ontario_wetlands USING GIN(wetland_name gin_trgm_ops);
CREATE INDEX idx_ont_wetlands_significant ON ontario_wetlands(provincial_significance) WHERE provincial_significance = TRUE;

-- ============================================================================
-- ONTARIO SPECIES AT RISK (Sensitive - restricted access)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ontario_species_at_risk (
    id SERIAL PRIMARY KEY,
    occurrence_id VARCHAR(50) UNIQUE,
    species_name VARCHAR(255) NOT NULL,
    scientific_name VARCHAR(255),
    saro_status VARCHAR(50), -- Endangered, Threatened, Special Concern, Extirpated
    last_observation_date DATE,
    geometry GEOMETRY(Point, 4326), -- GENERALIZED for public access
    generalized_location VARCHAR(255), -- e.g., "Southern Ontario", "Muskoka Region"
    habitat_type VARCHAR(100),
    habitat_description TEXT,
    data_sensitivity VARCHAR(20) DEFAULT 'HIGH', -- HIGH, MEDIUM, LOW
    access_restricted BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ont_species_geom ON ontario_species_at_risk USING GIST(geometry);
CREATE INDEX idx_ont_species_name ON ontario_species_at_risk USING GIN(species_name gin_trgm_ops);
CREATE INDEX idx_ont_species_status ON ontario_species_at_risk(saro_status);

-- ============================================================================
-- UNIFIED SEARCH FUNCTION
-- ============================================================================
-- Function to search across all Ontario area types
CREATE OR REPLACE FUNCTION search_ontario_areas(
    search_query TEXT,
    area_types TEXT[] DEFAULT NULL,
    region VARCHAR DEFAULT NULL,
    limit_count INTEGER DEFAULT 10
) RETURNS TABLE (
    id INTEGER,
    name VARCHAR,
    type VARCHAR,
    subtype VARCHAR,
    geometry GEOMETRY,
    size_ha NUMERIC,
    relevance NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    -- Provincial Parks
    SELECT 
        p.id,
        p.park_name::VARCHAR as name,
        'provincial_park'::VARCHAR as type,
        p.park_class::VARCHAR as subtype,
        p.geometry,
        p.size_ha,
        similarity(p.park_name, search_query) as relevance
    FROM ontario_provincial_parks p
    WHERE (area_types IS NULL OR 'provincial_park' = ANY(area_types))
        AND (p.park_name ILIKE '%' || search_query || '%' 
             OR similarity(p.park_name, search_query) > 0.3)
    
    UNION ALL
    
    -- Conservation Reserves
    SELECT 
        r.id,
        r.reserve_name::VARCHAR as name,
        'conservation_reserve'::VARCHAR as type,
        'protected_area'::VARCHAR as subtype,
        r.geometry,
        r.size_ha,
        similarity(r.reserve_name, search_query) as relevance
    FROM ontario_conservation_reserves r
    WHERE (area_types IS NULL OR 'conservation_reserve' = ANY(area_types))
        AND (r.reserve_name ILIKE '%' || search_query || '%'
             OR similarity(r.reserve_name, search_query) > 0.3)
    
    UNION ALL
    
    -- Conservation Authorities
    SELECT 
        c.id,
        c.authority_name::VARCHAR as name,
        'conservation_authority'::VARCHAR as type,
        'watershed_management'::VARCHAR as subtype,
        c.geometry,
        c.jurisdiction_area_ha as size_ha,
        similarity(c.authority_name, search_query) as relevance
    FROM ontario_conservation_authorities c
    WHERE (area_types IS NULL OR 'conservation_authority' = ANY(area_types))
        AND (c.authority_name ILIKE '%' || search_query || '%'
             OR c.acronym ILIKE '%' || search_query || '%'
             OR similarity(c.authority_name, search_query) > 0.3)
    
    UNION ALL
    
    -- Municipalities
    SELECT 
        m.id,
        m.municipality_name::VARCHAR as name,
        'municipality'::VARCHAR as type,
        m.municipality_type::VARCHAR as subtype,
        m.geometry,
        m.area_ha as size_ha,
        similarity(m.municipality_name, search_query) as relevance
    FROM ontario_municipalities m
    WHERE (area_types IS NULL OR 'municipality' = ANY(area_types))
        AND (m.municipality_name ILIKE '%' || search_query || '%'
             OR similarity(m.municipality_name, search_query) > 0.3)
    
    ORDER BY relevance DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SPATIAL STATISTICS FUNCTION
-- ============================================================================
-- Calculate protected area coverage for a given geometry
CREATE OR REPLACE FUNCTION calculate_protected_area_coverage(
    input_geometry GEOMETRY
) RETURNS TABLE (
    total_area_ha NUMERIC,
    protected_area_ha NUMERIC,
    coverage_percentage NUMERIC,
    park_count INTEGER,
    reserve_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    WITH area_calc AS (
        SELECT ST_Area(input_geometry::geography) / 10000 as total_ha
    ),
    parks_intersect AS (
        SELECT 
            COUNT(*) as park_count,
            SUM(ST_Area(ST_Intersection(p.geometry, input_geometry)::geography) / 10000) as park_area_ha
        FROM ontario_provincial_parks p
        WHERE ST_Intersects(p.geometry, input_geometry)
    ),
    reserves_intersect AS (
        SELECT 
            COUNT(*) as reserve_count,
            SUM(ST_Area(ST_Intersection(r.geometry, input_geometry)::geography) / 10000) as reserve_area_ha
        FROM ontario_conservation_reserves r
        WHERE ST_Intersects(r.geometry, input_geometry)
    )
    SELECT 
        a.total_ha,
        COALESCE(p.park_area_ha, 0) + COALESCE(r.reserve_area_ha, 0) as protected_ha,
        ((COALESCE(p.park_area_ha, 0) + COALESCE(r.reserve_area_ha, 0)) / a.total_ha * 100) as coverage_pct,
        p.park_count::INTEGER,
        r.reserve_count::INTEGER
    FROM area_calc a
    CROSS JOIN parks_intersect p
    CROSS JOIN reserves_intersect r;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- UPDATE TRIGGERS (for updated_at timestamps)
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_parks_updated_at BEFORE UPDATE ON ontario_provincial_parks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_reserves_updated_at BEFORE UPDATE ON ontario_conservation_reserves
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_ca_updated_at BEFORE UPDATE ON ontario_conservation_authorities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_watersheds_updated_at BEFORE UPDATE ON ontario_watersheds
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_municipalities_updated_at BEFORE UPDATE ON ontario_municipalities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_fmus_updated_at BEFORE UPDATE ON ontario_forest_management_units
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- COMMENTS (for documentation)
-- ============================================================================
COMMENT ON TABLE ontario_provincial_parks IS 'Ontario Provincial Parks with boundaries, classification, and facilities';
COMMENT ON TABLE ontario_conservation_authorities IS 'Ontario Conservation Authorities managing watersheds and natural resources';
COMMENT ON TABLE ontario_watersheds IS 'Watershed boundaries in Ontario';
COMMENT ON TABLE ontario_municipalities IS 'Municipal boundaries in Ontario';
COMMENT ON TABLE ontario_forest_management_units IS 'Forest Management Units for sustainable forestry';
COMMENT ON TABLE ontario_species_at_risk IS 'Species at Risk occurrences (GENERALIZED locations for public access)';

COMMENT ON FUNCTION search_ontario_areas IS 'Unified search across all Ontario area types with fuzzy matching';
COMMENT ON FUNCTION calculate_protected_area_coverage IS 'Calculate protected area coverage for a given geometry';

-- End of migration
