# Project Zeno Ontario Fork - Comprehensive Workplan

## Executive Summary

This workplan outlines the complete customization of WRI's Project Zeno (Global Nature Watch Agent) for Ontario, Canada. The fork will create "Ontario Nature Watch" - a specialized LLM-powered agent for Ontario's environmental data, conservation areas, and natural resources.

**Timeline Estimate:** 8-12 weeks for full implementation
**Complexity:** Medium-High
**Primary Focus:** Data localization, agent customization, infrastructure adaptation

---

## 1. PROJECT SETUP & INFRASTRUCTURE

### 1.1 Repository Setup
**Priority:** HIGH | **Estimated Time:** 1 day

**Tasks:**
- [ ] Fork `wri/project-zeno` repository to new `project-zeno-ontario` repo
- [ ] Fork `wri/project-zeno-next` frontend repository 
- [ ] Fork `wri/project-zeno-deploy` deployment repository
- [ ] Update all repository references and documentation
- [ ] Set up new project structure with Ontario-specific naming

**Deliverables:**
```
ontario-nature-watch/
├── ontario-nature-watch-api/      (forked from project-zeno)
├── ontario-nature-watch-frontend/ (forked from project-zeno-next)
└── ontario-nature-watch-deploy/   (forked from project-zeno-deploy)
```

### 1.2 Environment Configuration
**Priority:** HIGH | **Estimated Time:** 2 days

**Tasks:**
- [ ] Create `.env.ontario.example` with Ontario-specific configurations
- [ ] Set up Ontario-specific API credentials:
  - Ontario GeoHub API access
  - Ontario Data Catalogue credentials
  - Great Lakes Information Network (GLIN) access
  - Conservation Ontario credentials
- [ ] Configure database with Ontario-specific schema extensions
- [ ] Set up Ontario-specific S3 buckets or storage for data

**Key Configuration Changes:**
```env
# Ontario-Specific Environment Variables
PROJECT_NAME="Ontario Nature Watch"
REGION_FOCUS="Ontario, Canada"
DEFAULT_MAP_CENTER="44.5,-79.5"  # Ontario centroid
DEFAULT_MAP_ZOOM="6"
ONTARIO_GEOHUB_API_KEY=<key>
ONTARIO_DATA_CATALOGUE_KEY=<key>
CONSERVATION_ONTARIO_API_KEY=<key>
```

---

## 2. DATA ACQUISITION & INGESTION

### 2.1 Ontario Geographic Boundaries
**Priority:** CRITICAL | **Estimated Time:** 3 days

**Data Sources:**
1. **GADM Ontario Data** (Already partially supported)
   - Filter existing GADM ingestion for Ontario only
   - Include all administrative levels (Province, County, District, Municipality)

2. **Ontario-Specific Boundaries**
   - Conservation Authority boundaries
   - Watershed boundaries
   - Forest Management Units (FMUs)
   - District boundaries

**Implementation:**
```python
# File: src/ingest/ingest_ontario_boundaries.py

ONTARIO_DATASETS = {
    "conservation_authorities": {
        "source": "https://geohub.lio.gov.on.ca/datasets/conservation-authority-regulated",
        "table": "ontario_conservation_authorities",
        "geometry_type": "MultiPolygon"
    },
    "watersheds": {
        "source": "https://geohub.lio.gov.on.ca/datasets/watershed-boundaries",
        "table": "ontario_watersheds", 
        "geometry_type": "MultiPolygon"
    },
    "municipalities": {
        "source": "https://geohub.lio.gov.on.ca/datasets/ontario-municipalities",
        "table": "ontario_municipalities",
        "geometry_type": "MultiPolygon"
    },
    "counties": {
        "source": "https://geohub.lio.gov.on.ca/datasets/county-boundaries",
        "table": "ontario_counties",
        "geometry_type": "MultiPolygon"
    }
}
```

### 2.2 Protected Areas & Conservation Lands
**Priority:** CRITICAL | **Estimated Time:** 4 days

**Data Sources:**

1. **Provincial Parks**
   - Source: Ontario GeoHub - Provincial Parks
   - ~340 provincial parks
   - Include park class (Wilderness, Natural Environment, Waterway, etc.)

2. **Conservation Reserves**
   - Source: Ontario GeoHub - Conservation Reserves
   - ~290 conservation reserves

3. **Protected Areas (Canadian)**
   - Source: Canadian Protected and Conserved Areas Database (CPCAD)
   - Filter for Ontario only
   - Include federal protected areas (National Parks, National Wildlife Areas)

4. **Nature Conservancy of Canada Lands**
   - Private conservation lands in Ontario

5. **WDPA Integration** (Already supported, filter for Ontario)

**Implementation:**
```python
# File: src/ingest/ingest_ontario_protected_areas.py

ONTARIO_PROTECTED_AREAS = {
    "provincial_parks": {
        "source": "https://geohub.lio.gov.on.ca/datasets/provincial-parks",
        "table": "ontario_provincial_parks",
        "attributes": ["park_name", "park_class", "size_ha", "regulation_date"]
    },
    "conservation_reserves": {
        "source": "https://geohub.lio.gov.on.ca/datasets/conservation-reserve-regulated",
        "table": "ontario_conservation_reserves",
        "attributes": ["reserve_name", "size_ha", "purpose"]
    },
    "cpcad_ontario": {
        "source": "https://www.canada.ca/en/services/environment/conservation/assessments/open-data/cpcad-download.html",
        "filter": "PROV_TERR = 'ON'",
        "table": "ontario_cpcad_areas"
    }
}
```

### 2.3 Forest Resources Inventory (FRI)
**Priority:** HIGH | **Estimated Time:** 5 days

**Challenge:** Large dataset (~500,000 km²), requires significant storage

**Data Sources:**
1. **Forest Resources Inventory - Planning Composite**
   - Source: Ontario GeoHub FRI Status
   - Forest types, age classes, stocking levels
   - Updated annually with growth projections

2. **Forest Management Units (FMUs)**
   - 47 FMUs across Ontario
   - Include management plans and harvest data

**Implementation Strategy:**
```python
# File: src/ingest/ingest_ontario_forest.py

# Option 1: Full ingestion (requires ~50GB storage)
# Option 2: Tiled/simplified version for query
# Option 3: API integration only (recommended for MVP)

FOREST_DATASETS = {
    "fri_simplified": {
        "source": "https://geohub.lio.gov.on.ca/datasets/forest-resources-inventory-status",
        "simplification": "dissolve_by_forest_type",
        "table": "ontario_forest_types"
    },
    "fmus": {
        "source": "https://geohub.lio.gov.on.ca/datasets/forest-management-units",
        "table": "ontario_forest_management_units"
    }
}
```

### 2.4 Water Resources
**Priority:** MEDIUM | **Estimated Time:** 3 days

**Data Sources:**
1. **Great Lakes Data**
   - Great Lakes Information Network (GLIN)
   - Water quality monitoring
   - Shoreline data

2. **Inland Water Bodies**
   - Ontario Hydro Network (OHN)
   - Lakes, rivers, wetlands

3. **Source Water Protection Areas**
   - Wellhead protection areas
   - Surface water intake protection zones

**Implementation:**
```python
# File: src/ingest/ingest_ontario_water.py

WATER_DATASETS = {
    "great_lakes": {
        "source": "http://gis.glin.net/",
        "features": ["shoreline", "water_quality_stations"],
        "table": "ontario_great_lakes"
    },
    "ohn_waterbodies": {
        "source": "https://geohub.lio.gov.on.ca/datasets/ontario-hydro-network",
        "filter": "waterbody_type IN ('Lake', 'River')",
        "table": "ontario_waterbodies"
    },
    "wetlands": {
        "source": "https://geohub.lio.gov.on.ca/datasets/evaluated-wetlands",
        "table": "ontario_wetlands",
        "attributes": ["wetland_name", "wetland_type", "provincial_significance"]
    }
}
```

### 2.5 Species & Biodiversity
**Priority:** MEDIUM | **Estimated Time:** 3 days

**Data Sources:**
1. **Species at Risk in Ontario (SARO)**
   - Listed species under Endangered Species Act
   - Critical habitat designations

2. **Important Bird Areas (IBA) - Ontario**
   - Already may be in KBA dataset, but Ontario-specific

3. **Fish Habitat**
   - Sensitive fish habitat areas
   - Spawning grounds

**Implementation:**
```python
# File: src/ingest/ingest_ontario_biodiversity.py

BIODIVERSITY_DATASETS = {
    "species_at_risk": {
        "source": "https://geohub.lio.gov.on.ca/datasets/species-at-risk-occurrences",
        "table": "ontario_species_at_risk",
        "sensitivity": "HIGH"  # May require data access agreements
    },
    "fish_habitat": {
        "source": "https://geohub.lio.gov.on.ca/datasets/sensitive-fish-habitat",
        "table": "ontario_fish_habitat"
    }
}
```

### 2.6 Land Use & Agriculture
**Priority:** LOW | **Estimated Time:** 2 days

**Data Sources:**
1. **Ontario Land Cover**
   - 2015 land cover classification (15-meter resolution)

2. **Agricultural Resource Inventory**
   - Prime agricultural areas
   - Canada Land Inventory soil capability

**Implementation:**
```python
# File: src/ingest/ingest_ontario_landuse.py

LANDUSE_DATASETS = {
    "land_cover": {
        "source": "https://geohub.lio.gov.on.ca/datasets/ontario-land-cover-2015",
        "table": "ontario_land_cover",
        "raster": True  # May need rasterio processing
    },
    "prime_agricultural": {
        "source": "https://geohub.lio.gov.on.ca/datasets/prime-agricultural-areas",
        "table": "ontario_agriculture"
    }
}
```

### 2.7 Climate & Environmental Monitoring
**Priority:** MEDIUM | **Estimated Time:** 3 days

**Data Sources:**
1. **Climate Stations**
   - Environment Canada weather stations in Ontario
   - Historical climate data

2. **Air Quality Monitoring**
   - Ontario Air Quality Health Index stations

**API Integration Preferred** (real-time data)

---

## 3. DATABASE SCHEMA MODIFICATIONS

### 3.1 New Tables for Ontario Data
**Priority:** HIGH | **Estimated Time:** 3 days

**New Schema Elements:**
```sql
-- File: db/migrations/001_ontario_schema.sql

-- Conservation Authorities
CREATE TABLE ontario_conservation_authorities (
    id SERIAL PRIMARY KEY,
    authority_name VARCHAR(255),
    acronym VARCHAR(10),
    geometry GEOMETRY(MultiPolygon, 4326),
    jurisdiction_area_ha NUMERIC,
    watershed_count INTEGER,
    website VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_ont_ca_geom ON ontario_conservation_authorities USING GIST(geometry);

-- Provincial Parks
CREATE TABLE ontario_provincial_parks (
    id SERIAL PRIMARY KEY,
    park_name VARCHAR(255),
    park_class VARCHAR(50), -- Wilderness, Natural Environment, etc.
    geometry GEOMETRY(MultiPolygon, 4326),
    size_ha NUMERIC,
    regulation_date DATE,
    operating_season VARCHAR(50),
    facilities JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_ont_parks_geom ON ontario_provincial_parks USING GIST(geometry);

-- Forest Management Units
CREATE TABLE ontario_forest_management_units (
    id SERIAL PRIMARY KEY,
    fmu_name VARCHAR(255),
    fmu_code VARCHAR(10),
    geometry GEOMETRY(MultiPolygon, 4326),
    area_ha NUMERIC,
    management_company VARCHAR(255),
    plan_start_year INTEGER,
    plan_end_year INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Watersheds
CREATE TABLE ontario_watersheds (
    id SERIAL PRIMARY KEY,
    watershed_name VARCHAR(255),
    watershed_code VARCHAR(50),
    geometry GEOMETRY(MultiPolygon, 4326),
    area_ha NUMERIC,
    primary_drainage VARCHAR(100),
    conservation_authority_id INTEGER REFERENCES ontario_conservation_authorities(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Water Bodies
CREATE TABLE ontario_waterbodies (
    id SERIAL PRIMARY KEY,
    waterbody_name VARCHAR(255),
    waterbody_type VARCHAR(50), -- Lake, River, Stream
    geometry GEOMETRY(MultiPolygon, 4326),
    surface_area_ha NUMERIC,
    perimeter_km NUMERIC,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_ont_water_geom ON ontario_waterbodies USING GIST(geometry);

-- Species at Risk
CREATE TABLE ontario_species_at_risk (
    id SERIAL PRIMARY KEY,
    species_name VARCHAR(255),
    scientific_name VARCHAR(255),
    saro_status VARCHAR(50), -- Endangered, Threatened, Special Concern
    last_observation_date DATE,
    geometry GEOMETRY(Point, 4326),
    habitat_description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_ont_species_geom ON ontario_species_at_risk USING GIST(geometry);
```

### 3.2 Update Search Functions
**Priority:** HIGH | **Estimated Time:** 2 days

**Modify:** `db/functions/search_areas.sql`

Add Ontario-specific search capabilities:
```sql
-- Function to search Ontario-specific area types
CREATE OR REPLACE FUNCTION search_ontario_areas(
    search_query TEXT,
    area_types TEXT[] DEFAULT NULL,
    limit_count INTEGER DEFAULT 10
) RETURNS TABLE (
    id INTEGER,
    name VARCHAR,
    type VARCHAR,
    subtype VARCHAR,
    geometry GEOMETRY,
    relevance NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    -- Provincial Parks
    SELECT 
        p.id,
        p.park_name::VARCHAR as name,
        'protected_area'::VARCHAR as type,
        p.park_class::VARCHAR as subtype,
        p.geometry,
        similarity(p.park_name, search_query) as relevance
    FROM ontario_provincial_parks p
    WHERE (area_types IS NULL OR 'provincial_park' = ANY(area_types))
        AND p.park_name ILIKE '%' || search_query || '%'
    
    UNION ALL
    
    -- Conservation Authorities
    SELECT 
        c.id,
        c.authority_name::VARCHAR as name,
        'conservation_authority'::VARCHAR as type,
        'watershed_management'::VARCHAR as subtype,
        c.geometry,
        similarity(c.authority_name, search_query) as relevance
    FROM ontario_conservation_authorities c
    WHERE (area_types IS NULL OR 'conservation_authority' = ANY(area_types))
        AND c.authority_name ILIKE '%' || search_query || '%'
    
    -- Add more unions for other Ontario area types...
    
    ORDER BY relevance DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;
```

---

## 4. AGENT CUSTOMIZATION

### 4.1 System Prompts & Context
**Priority:** CRITICAL | **Estimated Time:** 3 days

**File:** `src/agent/prompts/ontario_system_prompt.py`

```python
ONTARIO_SYSTEM_PROMPT = """
You are Ontario Nature Watch, an AI assistant specializing in Ontario's natural environment, 
conservation areas, and environmental data. You have deep knowledge of:

GEOGRAPHY & JURISDICTIONS:
- Ontario's 47 Forest Management Units (FMUs)
- 36 Conservation Authorities managing watersheds across the province
- 340+ Provincial Parks across 7 park classes
- 290+ Conservation Reserves
- Ontario's regions: Southern Ontario, Central Ontario, Eastern Ontario, Northern Ontario, Far North
- The Great Lakes (Superior, Huron, Erie, Ontario) and their watersheds

ADMINISTRATIVE LEVELS:
- Province: Ontario
- Counties and Districts: 49 census divisions
- Municipalities: 444 lower-tier municipalities
- First Nations: 133 First Nations communities

KEY ENVIRONMENTAL FEATURES:
- Boreal Forest: Northern Ontario's dominant ecosystem
- Great Lakes: 20% of world's fresh surface water
- Carolinian Forest: Southern Ontario's rare ecosystem (Canadian endpoint)
- Hudson Bay Lowlands: One of largest wetland complexes in North America
- Niagara Escarpment: UNESCO World Biosphere Reserve

CONSERVATION CONTEXT:
- Ontario's Far North Act protects 225,000 km² of boreal forest
- Endangered Species Act (2007) protects species and habitats
- Provincial Parks Act manages park system
- Conservation Authorities Act enables watershed-based conservation
- Greenbelt Act protects 2 million acres of farmland and natural areas

KNOWLEDGE SOURCES:
- Ontario GeoHub: Authoritative provincial geospatial data
- Conservation Ontario: Watershed management data
- Ontario Ministry of Natural Resources and Forestry (MNRF)
- Great Lakes Information Network (GLIN)
- Canadian Protected and Conserved Areas Database (CPCAD)

When answering questions:
1. Use Ontario-specific terminology (e.g., "Conservation Authority" not "watershed district")
2. Reference relevant Ontario legislation and policies
3. Consider geographic context (Southern vs Northern Ontario distinctions)
4. Acknowledge First Nations territories and Treaty lands when relevant
5. Reference both English and French place names where applicable (Ontario is bilingual)
6. Use metric units (hectares, kilometres, square kilometres)

You can help users:
- Find conservation areas and protected lands
- Understand forest management and natural resources
- Explore watershed boundaries and water resources
- Learn about species at risk and biodiversity
- Analyze land use patterns and environmental changes
- Access Ontario government environmental data and policies
"""

ONTARIO_SAFETY_GUIDELINES = """
SENSITIVE DATA HANDLING:
- Species at Risk location data may be restricted to prevent harm to vulnerable species
- Some First Nations cultural sites are protected and locations should not be disclosed
- Private land ownership data should be handled carefully
- Follow Ontario's Freedom of Information and Protection of Privacy Act (FIPPA)

CULTURAL SENSITIVITY:
- Acknowledge that Ontario sits on the traditional territories of many Indigenous nations
- Use appropriate terminology for First Nations, Métis, and Inuit peoples
- Respect cultural protocols regarding sacred sites and traditional knowledge
"""
```

### 4.2 Ontario-Specific Tools
**Priority:** HIGH | **Estimated Time:** 5 days

**New Tool Files:**

#### Tool 1: Ontario Area Lookup
**File:** `src/agent/tools/ontario_area_lookup.py`

```python
from langchain.tools import BaseTool
from typing import Optional, Dict, Any
import logging

class OntarioAreaLookupTool(BaseTool):
    name = "ontario_area_lookup"
    description = """
    Search for areas of interest in Ontario including:
    - Provincial Parks (by name or park class)
    - Conservation Authorities (by name or watershed)
    - Municipalities (by name or county)
    - Conservation Reserves
    - Forest Management Units
    - Watersheds
    
    Input should be a search query string or JSON with filters:
    {
        "query": "Algonquin",
        "type": ["provincial_park", "conservation_authority"],
        "region": "Central Ontario"
    }
    """
    
    async def _arun(self, query: str) -> Dict[str, Any]:
        """Execute Ontario-specific area search"""
        # Parse query
        if isinstance(query, str):
            search_params = {"query": query, "types": None}
        else:
            search_params = json.loads(query)
        
        # Execute search against Ontario-specific tables
        results = await self.db.search_ontario_areas(
            search_query=search_params["query"],
            area_types=search_params.get("types"),
            region=search_params.get("region")
        )
        
        return {
            "results": results,
            "count": len(results),
            "search_params": search_params
        }
```

#### Tool 2: Ontario Forest Data
**File:** `src/agent/tools/ontario_forest_tool.py`

```python
class OntarioForestTool(BaseTool):
    name = "ontario_forest_lookup"
    description = """
    Query Ontario's Forest Resources Inventory (FRI) data:
    - Forest types and age classes
    - Forest Management Unit information
    - Harvesting statistics
    - Growth projections
    
    Input: FMU name, forest type, or geographic area
    """
    
    async def _arun(self, query: str) -> Dict[str, Any]:
        # Query FRI database or API
        # Return forest composition, management info
        pass
```

#### Tool 3: Conservation Authority Info
**File:** `src/agent/tools/conservation_authority_tool.py`

```python
class ConservationAuthorityTool(BaseTool):
    name = "conservation_authority_info"
    description = """
    Get information about Ontario Conservation Authorities:
    - Jurisdiction boundaries
    - Watershed management programs
    - Conservation areas
    - Flood management
    
    Input: Conservation Authority name or location
    """
    
    async def _arun(self, query: str) -> Dict[str, Any]:
        # Look up conservation authority
        # Return programs, areas, watershed info
        pass
```

#### Tool 4: Great Lakes Data
**File:** `src/agent/tools/great_lakes_tool.py`

```python
class GreatLakesTool(BaseTool):
    name = "great_lakes_data"
    description = """
    Access Great Lakes environmental data:
    - Water quality monitoring
    - Lake levels
    - Shoreline information
    - Protected areas along Great Lakes
    
    Input: Lake name (Superior, Huron, Erie, Ontario) or specific parameter
    """
    
    async def _arun(self, query: str) -> Dict[str, Any]:
        # Query GLIN API or database
        # Return water quality, levels, trends
        pass
```

### 4.3 Dataset RAG Customization
**Priority:** HIGH | **Estimated Time:** 3 days

**File:** `data/ontario_datasets_catalog.csv`

Create Ontario-specific dataset catalog for RAG:

```csv
dataset_id,dataset_name,description,source,topics,geographic_coverage,temporal_coverage,access_method
ont_parks_001,Ontario Provincial Parks,"Complete inventory of Ontario's 340+ provincial parks with boundaries, facilities, and classification",Ontario GeoHub,"protected areas,parks,recreation,conservation",Ontario,"1893-present",API
ont_ca_001,Conservation Authority Boundaries,"Boundaries and information for Ontario's 36 Conservation Authorities",Conservation Ontario,"watersheds,conservation,flood management",Ontario,"1946-present",API
ont_fri_001,Forest Resources Inventory,"Comprehensive forest inventory covering 500,000+ km² of Ontario forests",MNRF,"forestry,natural resources,land cover",Ontario,"2000-present",API
ont_water_001,Ontario Hydro Network,"Comprehensive water network including lakes, rivers, and wetlands",Ontario GeoHub,"water resources,hydrology,watersheds",Ontario,"Ongoing",WFS
ont_species_001,Species at Risk Occurrences,"Documented occurrences of species at risk in Ontario (access restricted)",MNRF,"biodiversity,species,conservation","Ontario (restricted)","1900-present",Restricted
ont_wetlands_001,Evaluated Wetlands,"Provincially Significant Wetlands and other evaluated wetlands",MNRF,"wetlands,conservation,biodiversity",Ontario,"1983-present",API
ont_landcover_001,Ontario Land Cover 2015,"15-meter resolution land cover classification for Southern Ontario",MNRF,"land use,land cover,environment",Southern Ontario,"2015",Download
ont_greatlakes_001,Great Lakes Water Quality,"Water quality monitoring data for Ontario's Great Lakes",GLIN,"water quality,Great Lakes,monitoring",Great Lakes,"1960-present",API
ont_niagara_001,Niagara Escarpment,"Niagara Escarpment Plan Area boundaries and regulations",Niagara Escarpment Commission,"protected areas,land use planning,conservation","Niagara Escarpment","1973-present",API
ont_greenbelt_001,Greenbelt Lands,"Protected greenbelt areas in Southern Ontario",MMAH,"land use planning,agriculture,conservation",Southern Ontario,"2005-present",API
```

**Update:** `src/ingest/embed_datasets.py`

```python
# Load Ontario-specific dataset catalog
def load_ontario_datasets():
    ontario_catalog = pd.read_csv('data/ontario_datasets_catalog.csv')
    
    # Create embeddings for Ontario datasets
    embeddings = create_embeddings(
        ontario_catalog['description'] + ' ' + 
        ontario_catalog['topics'] + ' ' + 
        ontario_catalog['dataset_name']
    )
    
    # Store in separate or combined index
    store_embeddings('ontario-datasets-index', embeddings, ontario_catalog)
```

### 4.4 Analytics Integration
**Priority:** MEDIUM | **Estimated Time:** 4 days

**New Analytics Endpoints:**

Most WRI analytics rely on their proprietary APIs. For Ontario, you'll need alternatives:

```python
# File: src/api/ontario_analytics.py

class OntarioAnalyticsService:
    """
    Ontario-specific analytics using local data + external APIs
    """
    
    async def get_forest_stats(self, geometry: dict) -> dict:
        """
        Calculate forest statistics for a given area
        Uses: FRI data, FMU data
        """
        pass
    
    async def get_protected_area_coverage(self, geometry: dict) -> dict:
        """
        Calculate protected area coverage
        Uses: Provincial parks, conservation reserves, CPCAD
        """
        pass
    
    async def get_watershed_info(self, geometry: dict) -> dict:
        """
        Get watershed characteristics
        Uses: Watershed boundaries, water quality data
        """
        pass
    
    async def get_species_richness(self, geometry: dict) -> dict:
        """
        Estimate species richness (limited by available data)
        Uses: Species at risk, biodiversity surveys
        """
        pass
```

---

## 5. FRONTEND CUSTOMIZATION

### 5.1 Branding & UI Updates
**Priority:** MEDIUM | **Estimated Time:** 3 days

**Repository:** `ontario-nature-watch-frontend`

**Changes Required:**

```javascript
// File: config/ontario-config.js

export const ONTARIO_CONFIG = {
  appName: "Ontario Nature Watch",
  tagline: "Explore Ontario's Natural Heritage",
  
  defaultMapView: {
    center: [44.5, -79.5], // Ontario centroid
    zoom: 6,
    bounds: [
      [-95.2, 41.7], // Southwest corner
      [-74.3, 56.9]  // Northeast corner
    ]
  },
  
  baseMapLayers: {
    default: "OpenStreetMap",
    satellite: "Esri WorldImagery",
    topographic: "Ontario Base Map"
  },
  
  colorScheme: {
    primary: "#006400",      // Ontario Green
    secondary: "#4A90E2",    // Great Lakes Blue
    accent: "#D4AF37"        // Golden (Trillium)
  },
  
  // Example prompts tailored to Ontario
  examplePrompts: [
    "Show me provincial parks in the Muskoka region",
    "What Conservation Authority manages the Grand River watershed?",
    "Find protected areas larger than 10,000 hectares in Northern Ontario",
    "What is the forest composition of Algonquin Provincial Park?",
    "Show me wetlands along Lake Huron",
    "Find species at risk in the Niagara Escarpment"
  ],
  
  regions: [
    "Southern Ontario",
    "Central Ontario",
    "Eastern Ontario",
    "Northern Ontario",
    "Far North"
  ]
};
```

**Logo & Assets:**
- Create Ontario-specific logo (suggest incorporating Trillium, Ontario's provincial flower)
- Update favicon
- Add Ontario imagery for landing page

### 5.2 Ontario-Specific Map Layers
**Priority:** HIGH | **Estimated Time:** 3 days

```javascript
// File: components/Map/OntarioLayers.js

export const ONTARIO_MAP_LAYERS = [
  {
    id: "provincial-parks",
    name: "Provincial Parks",
    source: {
      type: "vector",
      url: "https://services.arcgis.com/.../provincial_parks/FeatureServer"
    },
    style: {
      fill: "#2d5f2e",
      stroke: "#1a3a1b",
      opacity: 0.6
    },
    popup: (feature) => ({
      title: feature.properties.park_name,
      content: `
        <strong>Class:</strong> ${feature.properties.park_class}<br>
        <strong>Size:</strong> ${feature.properties.size_ha} ha
      `
    })
  },
  {
    id: "conservation-authorities",
    name: "Conservation Authorities",
    source: {
      type: "vector",
      url: "https://services.arcgis.com/.../conservation_authorities/FeatureServer"
    },
    style: {
      fill: "transparent",
      stroke: "#4A90E2",
      strokeWidth: 2
    }
  },
  {
    id: "watersheds",
    name: "Watersheds",
    source: {
      type: "vector",
      url: "https://services.arcgis.com/.../watersheds/FeatureServer"
    },
    style: {
      fill: "#e3f2fd",
      stroke: "#2196F3",
      opacity: 0.3
    }
  },
  // ... more layers
];
```

### 5.3 Ontario Context Panel
**Priority:** LOW | **Estimated Time:** 2 days

Add an information panel explaining Ontario's environmental context:

```jsx
// File: components/OntarioContextPanel.jsx

export const OntarioContextPanel = () => {
  return (
    <InfoPanel>
      <h3>About Ontario's Natural Heritage</h3>
      
      <Section title="Geography">
        <p>Ontario is Canada's second-largest province, spanning 1,076,395 km². 
        It contains 20% of the world's freshwater in the Great Lakes and hosts 
        diverse ecosystems from Carolinian forests in the south to boreal forests 
        and Hudson Bay Lowlands in the north.</p>
      </Section>
      
      <Section title="Conservation System">
        <StatGrid>
          <Stat label="Provincial Parks" value="340+" />
          <Stat label="Conservation Reserves" value="290+" />
          <Stat label="Conservation Authorities" value="36" />
          <Stat label="Protected Area" value="10.7%" />
        </StatGrid>
      </Section>
      
      <Section title="Key Features">
        <ul>
          <li>Great Lakes: Superior, Huron, Erie, Ontario</li>
          <li>Niagara Escarpment (UNESCO Biosphere Reserve)</li>
          <li>Boreal forest (70% of provincial land)</li>
          <li>225,000+ lakes and rivers</li>
        </ul>
      </Section>
    </InfoPanel>
  );
};
```

---

## 6. TESTING & VALIDATION

### 6.1 Data Quality Testing
**Priority:** HIGH | **Estimated Time:** 3 days

```python
# File: tests/test_ontario_data_quality.py

import pytest
from src.database import get_db_connection

class TestOntarioDataQuality:
    
    def test_provincial_parks_count(self):
        """Verify we have ~340 provincial parks"""
        result = db.execute("SELECT COUNT(*) FROM ontario_provincial_parks")
        assert 330 <= result[0] <= 350, "Provincial parks count out of expected range"
    
    def test_conservation_authorities_count(self):
        """Verify we have 36 conservation authorities"""
        result = db.execute("SELECT COUNT(*) FROM ontario_conservation_authorities")
        assert result[0] == 36, f"Expected 36 CAs, found {result[0]}"
    
    def test_geometry_validity(self):
        """Check all geometries are valid"""
        invalid_parks = db.execute("""
            SELECT park_name FROM ontario_provincial_parks 
            WHERE NOT ST_IsValid(geometry)
        """)
        assert len(invalid_parks) == 0, f"Invalid geometries found: {invalid_parks}"
    
    def test_projection_consistency(self):
        """Ensure all data is in EPSG:4326"""
        tables = ['ontario_provincial_parks', 'ontario_conservation_authorities', 
                  'ontario_watersheds']
        for table in tables:
            result = db.execute(f"SELECT ST_SRID(geometry) FROM {table} LIMIT 1")
            assert result[0] == 4326, f"{table} has wrong projection"
```

### 6.2 Agent Behavior Testing
**Priority:** HIGH | **Estimated Time:** 3 days

```python
# File: tests/test_ontario_agent.py

class TestOntarioAgent:
    
    @pytest.mark.asyncio
    async def test_park_lookup(self):
        """Test finding Algonquin Park"""
        response = await agent.run("Show me Algonquin Provincial Park")
        
        assert "Algonquin" in response
        assert "provincial park" in response.lower()
        assert "7,653" in response or "7653" in response  # Size in km²
    
    @pytest.mark.asyncio
    async def test_conservation_authority_lookup(self):
        """Test finding Conservation Authority"""
        response = await agent.run("Tell me about the Grand River Conservation Authority")
        
        assert "Grand River" in response
        assert "Conservation Authority" in response
        assert "watershed" in response.lower()
    
    @pytest.mark.asyncio
    async def test_ontario_context(self):
        """Test Ontario-specific knowledge"""
        response = await agent.run("What are the main forest types in Ontario?")
        
        assert any(term in response.lower() for term in 
                  ["boreal", "great lakes", "carolinian", "mixed"])
    
    @pytest.mark.asyncio
    async def test_spatial_query(self):
        """Test spatial queries"""
        response = await agent.run(
            "Find all provincial parks within 50km of Toronto"
        )
        
        # Should return Rouge National Urban Park, potentially others
        assert "park" in response.lower()
        assert isinstance(response.get('results'), list)
```

### 6.3 Performance Testing
**Priority:** MEDIUM | **Estimated Time:** 2 days

```python
# File: tests/test_ontario_performance.py

class TestPerformance:
    
    def test_area_search_speed(self):
        """Spatial search should complete in <1 second"""
        import time
        start = time.time()
        
        results = db.search_ontario_areas("Toronto", limit=10)
        
        elapsed = time.time() - start
        assert elapsed < 1.0, f"Search took {elapsed}s, expected <1s"
    
    def test_geometry_intersection_speed(self):
        """Geometry operations should be fast"""
        import time
        start = time.time()
        
        # Find all parks intersecting with a conservation authority
        results = db.execute("""
            SELECT p.park_name 
            FROM ontario_provincial_parks p, ontario_conservation_authorities c
            WHERE ST_Intersects(p.geometry, c.geometry)
            AND c.authority_name = 'Credit Valley Conservation'
        """)
        
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Intersection query took {elapsed}s"
```

---

## 7. DEPLOYMENT & INFRASTRUCTURE

### 7.1 Environment-Specific Deployment
**Priority:** HIGH | **Estimated Time:** 4 days

**Repository:** `ontario-nature-watch-deploy`

**Kubernetes/Helm Configuration:**

```yaml
# File: helm/ontario-nature-watch/values-ontario.yaml

app:
  name: ontario-nature-watch
  region: ontario
  
api:
  image:
    repository: ghcr.io/your-org/ontario-nature-watch-api
    tag: latest
  
  env:
    - name: PROJECT_NAME
      value: "Ontario Nature Watch"
    - name: REGION_FOCUS
      value: "Ontario, Canada"
    - name: DEFAULT_MAP_CENTER
      value: "44.5,-79.5"
    - name: ONTARIO_GEOHUB_API_KEY
      valueFrom:
        secretKeyRef:
          name: ontario-api-keys
          key: geohub-api-key
  
  resources:
    requests:
      memory: "2Gi"
      cpu: "1000m"
    limits:
      memory: "4Gi"
      cpu: "2000m"

database:
  image:
    repository: postgis/postgis
    tag: "15-3.4"
  
  persistence:
    size: 100Gi  # Increase for Ontario datasets
  
  # Ontario-specific database initialization
  initScripts:
    - 001_ontario_schema.sql
    - 002_ontario_functions.sql
    - 003_ontario_indexes.sql

frontend:
  image:
    repository: ghcr.io/your-org/ontario-nature-watch-frontend
    tag: latest
  
  env:
    - name: NEXT_PUBLIC_API_URL
      value: "https://api.ontario-nature-watch.org"
    - name: NEXT_PUBLIC_APP_NAME
      value: "Ontario Nature Watch"
```

### 7.2 Data Update Pipeline
**Priority:** MEDIUM | **Estimated Time:** 3 days

**Automated Data Refresh:**

```yaml
# File: .github/workflows/ontario-data-refresh.yml

name: Ontario Data Refresh

on:
  schedule:
    - cron: '0 2 * * 0'  # Weekly on Sunday at 2 AM
  workflow_dispatch:

jobs:
  refresh-ontario-data:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Refresh Provincial Parks
        run: |
          python src/ingest/refresh_ontario_parks.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          ONTARIO_GEOHUB_API_KEY: ${{ secrets.ONTARIO_GEOHUB_API_KEY }}
      
      - name: Refresh Conservation Areas
        run: |
          python src/ingest/refresh_conservation_areas.py
      
      - name: Validate Data Quality
        run: |
          pytest tests/test_ontario_data_quality.py
      
      - name: Notify on Failure
        if: failure()
        uses: actions/github-script@v6
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: 'Ontario Data Refresh Failed',
              body: 'The automated Ontario data refresh failed. Please investigate.'
            })
```

### 7.3 Monitoring & Alerting
**Priority:** MEDIUM | **Estimated Time:** 2 days

```yaml
# File: monitoring/ontario-alerts.yml

groups:
  - name: ontario-nature-watch
    interval: 30s
    rules:
      - alert: OntarioDataStaleness
        expr: time() - ontario_data_last_updated_timestamp > 86400 * 14
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Ontario dataset has not been updated in 14 days"
          description: "Dataset {{ $labels.dataset }} last updated {{ $value }} seconds ago"
      
      - alert: SpatialQueryPerformance
        expr: histogram_quantile(0.95, spatial_query_duration_seconds) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Spatial queries are slow"
          description: "95th percentile query time is {{ $value }} seconds"
      
      - alert: LowProtectedAreaCoverage
        expr: ontario_protected_area_percentage < 10
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "Protected area coverage calculation seems wrong"
          description: "Calculated coverage is {{ $value }}%, expected >10%"
```

---

## 8. DOCUMENTATION

### 8.1 Ontario-Specific Documentation
**Priority:** MEDIUM | **Estimated Time:** 4 days

**Create New Documentation:**

```markdown
# File: docs/ONTARIO_CUSTOMIZATION.md

# Ontario Nature Watch - Customization Documentation

## Overview
Ontario Nature Watch is a fork of WRI's Project Zeno, customized for Ontario's 
environmental data and conservation needs.

## Data Sources

### Primary Data Sources
1. **Ontario GeoHub** (https://geohub.lio.gov.on.ca)
   - Authoritative provincial geospatial data
   - 500+ datasets covering natural resources, boundaries, infrastructure
   - API access for real-time data

2. **Conservation Ontario** (https://conservationontario.ca)
   - Conservation Authority boundaries and programs
   - Watershed management data
   - Flood forecasting and water quality

3. **Canadian Protected Areas Database (CPCAD)**
   - Federal and provincial protected areas
   - Ontario subset with detailed attributes

4. **Great Lakes Information Network (GLIN)**
   - Great Lakes water quality and levels
   - Binational data sharing

### Data Update Frequency
- Provincial Parks: Quarterly
- Conservation Authority boundaries: Annually
- Forest Resources Inventory: Annually (with growth projections)
- Water quality: Real-time where available
- Species at Risk: As reported (sensitive)

## Ontario-Specific Features

### Geographic Regions
The system recognizes Ontario's distinct regions:
- **Southern Ontario**: Windsor to Ottawa, south of French/Mattawa rivers
- **Central Ontario**: Muskoka, Haliburton, Peterborough regions
- **Eastern Ontario**: Ottawa Valley to Kingston
- **Northern Ontario**: Sudbury, Timmins, Thunder Bay regions
- **Far North**: Hudson Bay Lowlands, Ring of Fire

### Conservation Framework
Understanding Ontario's conservation system:
- **Provincial Parks**: 7 classes (Wilderness, Natural Environment, Waterway, Recreational, Natural Heritage, Cultural Heritage, Recreation Trail)
- **Conservation Reserves**: Areas set aside for natural heritage protection
- **Conservation Authorities**: Watershed-based conservation agencies (36 across Ontario)
- **National Parks**: Federal protected areas (e.g., Bruce Peninsula, Pukaskwa)
- **Greenbelt**: Protected agricultural and natural areas in Greater Golden Horseshoe

### Key Datasets

#### ontario_provincial_parks
- 340+ parks across Ontario
- Total area: 9 million hectares
- Fields: park_name, park_class, size_ha, facilities, operating_season

#### ontario_conservation_authorities
- 36 conservation authorities
- Cover 95% of populated areas in Ontario
- Fields: authority_name, jurisdiction_area, watersheds, programs

#### ontario_forest_management_units
- 47 FMUs covering 45 million hectares
- Sustainable forest management
- Fields: fmu_code, area_ha, management_company, plan_year

... (additional dataset documentation)

## Usage Examples

### Finding Protected Areas
```python
# Find provincial parks in a specific region
agent.run("Show me all wilderness-class provincial parks in Northern Ontario")

# Find conservation areas by watershed
agent.run("What conservation areas are managed by the Grand River Conservation Authority?")
```

### Forest Analysis
```python
# Query forest composition
agent.run("What are the dominant forest types in Algonquin Provincial Park?")

# Find Forest Management Units
agent.run("Show me FMUs in the Sault Ste. Marie district")
```

### Water Resources
```python
# Great Lakes queries
agent.run("What is the current water level of Lake Ontario?")

# Watershed information
agent.run("Show me all wetlands in the Credit River watershed")
```

## API Endpoints

### Ontario-Specific Endpoints

#### GET /api/ontario/parks
Returns list of Ontario provincial parks with optional filters.

Query Parameters:
- `park_class`: Filter by park class
- `region`: Geographic region
- `min_size`: Minimum size in hectares
- `facilities`: Required facilities (camping, trails, etc.)

#### GET /api/ontario/conservation-authorities
Returns Conservation Authorities with jurisdiction info.

#### GET /api/ontario/forest/fmus
Returns Forest Management Units.

... (additional API documentation)

## Configuration

### Environment Variables
```bash
# Ontario-specific configuration
PROJECT_NAME="Ontario Nature Watch"
REGION_FOCUS="Ontario, Canada"
DEFAULT_MAP_CENTER="44.5,-79.5"
DEFAULT_MAP_ZOOM="6"

# Data source API keys
ONTARIO_GEOHUB_API_KEY=your_key_here
CONSERVATION_ONTARIO_API_KEY=your_key_here
GLIN_API_KEY=your_key_here

# Optional: Restrict to Ontario only
GEOGRAPHIC_BOUNDS="-95.2,41.7,-74.3,56.9"
```

## Known Limitations

1. **Forest Resources Inventory**: Full FRI dataset is very large (~50GB). The system uses a simplified version. For detailed forest analysis, users should access FRI directly from MNRF.

2. **Species at Risk Data**: Location data for endangered species is restricted to prevent harm. General distribution information is available, but precise locations require special access.

3. **Real-time Water Quality**: While some stations provide real-time data via GLIN, many water quality parameters are updated monthly or quarterly.

4. **Far North Coverage**: Remote areas of Far North Ontario have limited ground-truth data. Satellite-derived information may have lower accuracy.

## Contributing Ontario Data

If you have additional Ontario datasets to contribute:
1. Ensure data is publicly accessible or you have distribution rights
2. Provide metadata (source, temporal coverage, update frequency)
3. Include data dictionary with field descriptions
4. Submit via pull request with ingestion script

Contact: ontario-nature-watch@example.org
```

### 8.2 User Guide
**Priority:** LOW | **Estimated Time:** 3 days

```markdown
# File: docs/ONTARIO_USER_GUIDE.md

# Ontario Nature Watch User Guide

## Getting Started

Ontario Nature Watch helps you explore Ontario's natural heritage through an 
AI-powered conversational interface.

### What You Can Do

1. **Discover Protected Areas**
   - Find provincial parks, conservation reserves, and national parks
   - Learn about park facilities, trails, and accessibility
   - Get directions and planning information

2. **Explore Watersheds**
   - Understand watershed boundaries
   - Find Conservation Authorities and their programs
   - Access water quality information

3. **Understand Forests**
   - Learn about forest types and composition
   - Explore Forest Management Units
   - Access sustainable forestry information

4. **Species & Biodiversity**
   - Learn about species at risk
   - Find Important Bird Areas
   - Explore wetlands and critical habitat

### Example Questions

**Finding Places:**
- "Show me wilderness provincial parks within 200km of Toronto"
- "What conservation areas are in Waterloo Region?"
- "Find wetlands along the Lake Huron shoreline"

**Learning About Areas:**
- "Tell me about Algonquin Provincial Park"
- "What is the Grand River Conservation Authority responsible for?"
- "What are the main environmental features of the Niagara Escarpment?"

**Environmental Data:**
- "What is the forest composition of Temagami region?"
- "Show me protected area coverage in Grey County"
- "What species at risk are found in the Carolinian zone?"

**Planning & Analysis:**
- "Find campable provincial parks in Eastern Ontario"
- "What watersheds drain into Lake Ontario?"
- "Compare protected area coverage across Ontario regions"

## Understanding Results

### Map View
Results are displayed on an interactive map:
- **Green areas**: Provincial parks and conservation reserves
- **Blue outlines**: Conservation Authority boundaries / watersheds
- **Orange**: Forest Management Units
- **Purple**: Species at risk habitat (generalized)

### Data Tables
Detailed information is provided in tables with:
- Area name and classification
- Size (in hectares or km²)
- Managing organization
- Links to more information

### Charts & Visualizations
Statistical analyses are shown as:
- Bar charts (comparing areas or categories)
- Pie charts (composition breakdowns)
- Time series (trends over time where available)

## Tips for Best Results

1. **Be Specific**: "Provincial parks in Muskoka" is better than "parks"

2. **Use Ontario Terminology**:
   - Say "Conservation Authority" not "watershed district"
   - Say "Provincial Park" not just "park" (to distinguish from municipal parks)

3. **Combine Criteria**: "Wilderness provincial parks over 50,000 hectares in Northern Ontario"

4. **Ask for Context**: "Why is the Oak Ridges Moraine important?" gets you background information

5. **Request Comparisons**: "Compare forest coverage in Southern vs Northern Ontario"

## Data Sources & Currency

All data comes from authoritative Ontario government sources:
- Ontario GeoHub (Ministry of Natural Resources and Forestry)
- Conservation Ontario
- Parks Ontario
- Environment and Climate Change Canada

**Data Currency:**
- Administrative boundaries: Updated annually
- Protected areas: Updated quarterly
- Environmental monitoring: Varies (some real-time, some monthly)
- Forest inventory: Annual updates with projections

## Privacy & Sensitive Data

Some information is protected:
- **Species at Risk locations**: Only general distribution shown
- **Cultural heritage sites**: May be generalized
- **Private land**: Ownership not disclosed

## Need Help?

- **Technical Issues**: support@ontario-nature-watch.org
- **Data Questions**: data@ontario-nature-watch.org
- **Feedback**: feedback@ontario-nature-watch.org

## Glossary

**Conservation Authority**: Watershed-based conservation agencies established under Ontario's Conservation Authorities Act

**FMU**: Forest Management Unit - areas designated for sustainable forest management

**Provincial Park Classes**:
- Wilderness: Remote, undeveloped areas
- Natural Environment: Natural landscapes with some facilities
- Waterway: River and lake corridors for recreation
- Recreation: Areas focused on outdoor recreation
- ... (etc.)

**PSW**: Provincially Significant Wetland - wetlands recognized for ecological importance

**SARO**: Species at Risk in Ontario - species protected under Endangered Species Act
```

---

## 9. LEGAL & COMPLIANCE

### 9.1 Data Licensing
**Priority:** HIGH | **Estimated Time:** 2 days

**Review and Document:**

1. **Ontario Open Government License**
   - Most Ontario GeoHub data is under Open Government License - Ontario
   - Permits: copy, modify, publish, adapt, distribute
   - Requires: attribution to "Ontario"
   - Review: https://www.ontario.ca/page/open-government-licence-ontario

2. **Conservation Ontario Data**
   - Verify licensing terms with Conservation Ontario
   - May require separate attribution

3. **Federal Data (CPCAD, etc.)**
   - Usually under Open Government License - Canada
   - Verify attribution requirements

**Create:** `docs/LICENSE_ATTRIBUTION.md`

```markdown
# Data Licensing and Attribution

## Ontario Government Data
Data from Ontario GeoHub is used under the Open Government License - Ontario.

**Attribution:** Contains information licensed under the Open Government Licence – Ontario.

**Source Datasets:**
- Provincial Parks Boundaries
- Conservation Reserve Boundaries
- Conservation Authority Boundaries
- Forest Management Units
- Ontario Hydro Network
- [List all Ontario datasets]

**License:** https://www.ontario.ca/page/open-government-licence-ontario

## Federal Government Data
Canadian Protected and Conserved Areas Database (CPCAD) and other federal data 
used under Open Government License - Canada.

**Attribution:** Contains information licensed under the Open Government Licence – Canada.

**Source Datasets:**
- Canadian Protected and Conserved Areas Database
- [List all federal datasets]

**License:** https://open.canada.ca/en/open-government-licence-canada

## Third-Party Data
[List any third-party data sources with their specific licenses]
```

### 9.2 Privacy Compliance
**Priority:** MEDIUM | **Estimated Time:** 2 days

**Ensure Compliance with:**
1. **FIPPA** (Freedom of Information and Protection of Privacy Act - Ontario)
   - No personal information stored
   - User queries logged but anonymized
   - Implement data retention policies

2. **PIPEDA** (Personal Information Protection and Electronic Documents Act - Federal)
   - If collecting user accounts/preferences

**Create:** `docs/PRIVACY_POLICY.md`

---

## 10. MAINTENANCE & LONG-TERM SUSTAINABILITY

### 10.1 Data Update Schedule
**Priority:** MEDIUM | **Estimated Time:** 1 day

Create a maintenance calendar:

```markdown
# Ontario Nature Watch Data Maintenance Schedule

## Quarterly Updates
- Provincial Parks (check for new parks or boundary changes)
- Conservation Reserves
- Protected area statistics

## Annual Updates
- Forest Resources Inventory (typically released annually)
- Conservation Authority boundaries
- Administrative boundaries (post-municipal reorganizations)

## Monthly Updates (if available)
- Water quality data
- Species at Risk occurrences (if access granted)

## Real-time / On-demand
- Weather and climate data
- Water levels (Great Lakes)
- Some air quality metrics

## Verification Checklist
After each data update:
- [ ] Run data quality tests
- [ ] Verify geometry validity
- [ ] Check for projection consistency
- [ ] Update dataset metadata (last_updated timestamp)
- [ ] Regenerate dataset embeddings if descriptions changed
- [ ] Test agent queries against updated data
```

### 10.2 Community Contribution Guidelines
**Priority:** LOW | **Estimated Time:** 2 days

**Create:** `CONTRIBUTING_ONTARIO.md`

```markdown
# Contributing to Ontario Nature Watch

## Ways to Contribute

### 1. Report Issues
Found a bug or data error? Open an issue:
- Describe the problem clearly
- Include example query if agent-related
- Provide expected vs actual results

### 2. Suggest Ontario Datasets
Know of a useful Ontario dataset we're missing?
- Verify it's publicly accessible
- Provide: source URL, description, format, update frequency
- Explain use cases

### 3. Improve Documentation
Help make the project more accessible:
- Fix typos or unclear instructions
- Add examples
- Translate to French

### 4. Code Contributions
Follow these steps:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit pull request

### 5. Share Feedback
Use the project? Let us know:
- Success stories
- Frustrations
- Feature requests
```

---

## IMPLEMENTATION ROADMAP

### Phase 1: Foundation (Weeks 1-3)
**Goal:** Set up infrastructure and ingest critical datasets

- [ ] Week 1: Repository setup, environment configuration, database schema
- [ ] Week 2: Ingest GADM, provincial parks, conservation reserves
- [ ] Week 3: Ingest conservation authorities, watersheds, basic forest data

**Deliverable:** Working system with Ontario boundaries and protected areas

### Phase 2: Agent Customization (Weeks 4-6)
**Goal:** Customize agent for Ontario context

- [ ] Week 4: Ontario system prompts, basic Ontario tools
- [ ] Week 5: Dataset RAG with Ontario catalog, test agent responses
- [ ] Week 6: Advanced tools (forest, Great Lakes, analytics)

**Deliverable:** Functional Ontario Nature Watch agent

### Phase 3: Frontend & UX (Weeks 7-8)
**Goal:** Create Ontario-branded user experience

- [ ] Week 7: Frontend branding, map customization, Ontario layers
- [ ] Week 8: Example prompts, context panels, UI polish

**Deliverable:** Production-ready frontend

### Phase 4: Testing & Documentation (Weeks 9-10)
**Goal:** Ensure quality and usability

- [ ] Week 9: Comprehensive testing (data, agent, performance)
- [ ] Week 10: Documentation, deployment guides, license compliance

**Deliverable:** Fully documented, tested system

### Phase 5: Deployment & Refinement (Weeks 11-12)
**Goal:** Deploy to production and iterate

- [ ] Week 11: Production deployment, monitoring setup
- [ ] Week 12: User feedback collection, bug fixes, refinement

**Deliverable:** Live Ontario Nature Watch system

---

## RESOURCE REQUIREMENTS

### Technical Resources
- **Storage:** ~100-150 GB (database + cached data)
  - PostgreSQL with PostGIS: 80-120 GB
  - File storage: 20-30 GB
- **Compute:**
  - API: 2-4 vCPUs, 4-8 GB RAM
  - Database: 2-4 vCPUs, 8-16 GB RAM
  - Frontend: 1-2 vCPUs, 2-4 GB RAM
- **Network:**
  - Bandwidth for map tiles and data serving
  - API rate limits (Ontario GeoHub, etc.)

### Human Resources
- **Backend Developer:** 3-4 weeks full-time
  - Data ingestion scripts
  - Agent customization
  - API modifications
- **Frontend Developer:** 2-3 weeks full-time
  - UI customization
  - Map layer integration
  - Branding
- **Data Analyst/GIS Specialist:** 2-3 weeks part-time
  - Dataset identification
  - Data quality validation
  - Geographic expertise
- **DevOps/Infrastructure:** 1-2 weeks part-time
  - Deployment setup
  - CI/CD pipelines
  - Monitoring

### Third-Party Services
- **API Keys Required:**
  - OpenAI or Anthropic (for LLM)
  - Ontario GeoHub (if rate limits apply)
  - Map tile providers (if not using OSM)
- **Optional Services:**
  - Langfuse (observability) - can self-host
  - S3-compatible storage for backups

---

## RISK ASSESSMENT & MITIGATION

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Large dataset ingestion failures | Medium | High | Implement chunked processing, retry logic, validation checks |
| Agent provides incorrect Ontario information | Medium | High | Extensive testing, fact-checking layer, clear limitations in UI |
| Performance issues with spatial queries | Medium | Medium | Proper indexing (GiST), query optimization, caching layer |
| API rate limits from data providers | Low | Medium | Implement caching, respect rate limits, have fallback options |
| Ontario data source changes/deprecated | Low | Medium | Monitor sources, maintain update pipeline, document alternatives |

### Legal/Compliance Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Misuse of restricted species data | Low | High | Implement access controls, generalize sensitive locations |
| Attribution/licensing violations | Low | Medium | Clear documentation, automated attribution in outputs |
| Privacy concerns with user queries | Low | Medium | Anonymize logs, clear privacy policy, minimal data retention |

### Operational Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Data staleness (outdated information) | Medium | Medium | Automated update pipelines, staleness alerts, last-updated stamps |
| Lack of ongoing maintenance resources | Medium | High | Document all processes, automate where possible, seek funding/partnership |
| User confusion vs. original Project Zeno | Low | Low | Clear branding, distinct domain, Ontario-specific focus in all communications |

---

## SUCCESS METRICS

### Technical Metrics
- **Data Coverage:** >90% of Ontario protected areas ingested
- **Query Performance:** 95th percentile <2 seconds for spatial searches
- **Agent Accuracy:** >90% factually correct responses on validation set
- **Uptime:** >99% availability

### User Engagement Metrics
- **Query Success Rate:** >80% of queries return relevant results
- **User Satisfaction:** >4.0/5.0 average rating
- **Return Users:** >30% users return within 30 days

### Impact Metrics
- **Coverage:** Users from all Ontario regions
- **Use Cases:** Environmental planning, education, conservation, research
- **Data Requests:** Increase in Ontario open data downloads (if trackable)

---

## APPENDICES

### Appendix A: Ontario Dataset Inventory
[Complete list of 50+ Ontario datasets with metadata]

### Appendix B: Conservation Authority Directory
[List of all 36 CAs with contact info, jurisdiction]

### Appendix C: Provincial Park Classification Guide
[Detailed explanation of Ontario's park system]

### Appendix D: Technical Architecture Diagrams
[System architecture specific to Ontario deployment]

### Appendix E: API Reference
[Complete API documentation for Ontario endpoints]

### Appendix F: Sample Queries & Expected Outputs
[Test suite of Ontario-specific queries]

---

## CONCLUSION

This workplan provides a comprehensive roadmap for customizing WRI's Project Zeno for Ontario. The key differentiators for the Ontario fork are:

1. **Deep Ontario Data Integration:** 500+ datasets from Ontario GeoHub, Conservation Ontario, and federal sources
2. **Ontario-Specific Agent Knowledge:** Understanding of Conservation Authorities, provincial park system, forest management, Great Lakes
3. **Localized User Experience:** Ontario branding, regional context, relevant examples
4. **Sustainable Maintenance:** Automated data pipelines, comprehensive documentation

**Estimated Total Effort:** 8-12 weeks with dedicated team
**Estimated Cost:** $80,000-$120,000 CAD (including development, infrastructure, initial deployment)

The result will be a production-ready "Ontario Nature Watch" system that serves as a powerful tool for exploring Ontario's natural heritage, supporting conservation planning, education, and environmental decision-making.

---

**Document Version:** 1.0
**Last Updated:** 2024-11-14
**Author:** Technical Planning Team
**Contact:** ontario-nature-watch@example.org
