# Ontario Nature Watch - Sample Code

This directory contains sample code to help you get started with customizing Project Zeno for Ontario.

## Files Overview

### 1. `001_ontario_schema.sql`
**Purpose:** Database schema for Ontario-specific data

**What it does:**
- Creates tables for Ontario Provincial Parks, Conservation Authorities, Watersheds, etc.
- Sets up spatial indexes for efficient geographic queries
- Provides unified search functions
- Includes validation and helper functions

**How to use:**
```bash
# Apply to your database
psql $DATABASE_URL -f 001_ontario_schema.sql

# Or using alembic (recommended)
# Copy to: db/migrations/versions/001_ontario_schema.sql
alembic upgrade head
```

**Key tables created:**
- `ontario_provincial_parks` (~340 parks)
- `ontario_conservation_authorities` (36 CAs)
- `ontario_conservation_reserves` (~290 reserves)
- `ontario_watersheds` (300+ watersheds)
- `ontario_municipalities` (444 municipalities)
- `ontario_forest_management_units` (47 FMUs)
- `ontario_waterbodies` (lakes, rivers)
- `ontario_wetlands` (evaluated wetlands)
- `ontario_species_at_risk` (sensitive - generalized locations)

**Important functions:**
- `search_ontario_areas(query, types, region, limit)` - Unified search across all area types
- `calculate_protected_area_coverage(geometry)` - Calculate protected area % for any area

---

### 2. `ingest_ontario_parks.py`
**Purpose:** Download and ingest Ontario Provincial Parks data

**What it does:**
- Downloads parks data from Ontario GeoHub
- Transforms geometry to EPSG:4326
- Ingests into `ontario_provincial_parks` table
- Validates data quality (counts, geometries, projections)

**How to use:**
```bash
# Set environment variable
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/ontario-nature-watch"

# Run ingestion
python ingest_ontario_parks.py

# Expected output:
# - Downloaded 340+ parks
# - All geometries valid
# - Total area ~9 million hectares
```

**Customization needed:**
- Update `PARKS_GEOJSON_URL` with actual Ontario GeoHub endpoint
- Adjust field mappings based on actual data schema (check the GeoHub docs)
- Modify `transform_parks_data()` to match actual field names

**Similar scripts needed:**
- `ingest_ontario_conservation_authorities.py`
- `ingest_ontario_watersheds.py`
- `ingest_ontario_wetlands.py`
- etc.

---

### 3. `ontario_area_lookup_tool.py`
**Purpose:** LangChain tools for Ontario area searches

**What it provides:**
- `OntarioAreaLookupTool` - Search all Ontario area types
- `ConservationAuthorityTool` - Detailed CA information

**How to use:**

1. **In your agent code:**
```python
from ontario_area_lookup_tool import ONTARIO_TOOLS

# Add to your agent's tools
agent = create_agent(
    tools=[
        *ONTARIO_TOOLS,  # Ontario-specific tools
        *other_tools     # Other tools
    ]
)
```

2. **Test the tools:**
```bash
# Run the test suite included in the file
python ontario_area_lookup_tool.py
```

**Example queries handled:**
- "Find Algonquin Provincial Park"
- "What does the Grand River Conservation Authority manage?"
- "Show me municipalities in Waterloo Region"
- "Find wilderness parks in Northern Ontario"

**Extending:**
- Add `OntarioForestTool` for forest queries
- Add `GreatLakesTool` for water quality data
- Add `OntarioAnalyticsTool` for statistical analysis

---

### 4. `.env.ontario.example`
**Purpose:** Complete environment configuration template

**What it contains:**
- All configuration options for Ontario deployment
- Database settings
- LLM provider settings
- Ontario data source URLs
- Feature flags
- Monitoring and logging config

**How to use:**
```bash
# Copy to your project root
cp .env.ontario.example /path/to/project/.env

# Edit with your actual values
nano .env

# Key values to set:
# - DATABASE_URL
# - ANTHROPIC_API_KEY (or OPENAI_API_KEY)
# - LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
```

**Important sections:**
- **Project Configuration:** Name, region, branding
- **Database:** Connection strings and pool settings
- **LLM Configuration:** Model selection and API keys
- **Ontario Data Sources:** GeoHub, Conservation Ontario, GLIN
- **Feature Flags:** Enable/disable specific features
- **Ontario-Specific Settings:** Expected counts, regions, etc.

---

## Quick Start Guide

### 1. Set Up Database
```bash
# Create database
createdb ontario-nature-watch

# Apply schema
psql ontario-nature-watch -f 001_ontario_schema.sql

# Verify tables created
psql ontario-nature-watch -c "\dt ontario_*"
```

### 2. Configure Environment
```bash
# Copy environment file
cp .env.ontario.example .env

# Edit configuration
nano .env

# Set at minimum:
# - DATABASE_URL
# - ANTHROPIC_API_KEY or OPENAI_API_KEY
```

### 3. Ingest Data
```bash
# Install dependencies
pip install geopandas asyncpg

# Run park ingestion
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ontario-nature-watch"
python ingest_ontario_parks.py

# Verify ingestion
psql ontario-nature-watch -c "SELECT COUNT(*) FROM ontario_provincial_parks;"
# Should return ~340
```

### 4. Test Tools
```bash
# Test Ontario area lookup
python ontario_area_lookup_tool.py

# Should output search results for test queries
```

### 5. Integrate with Project Zeno
```bash
# In your agent setup file (e.g., src/agent/agent.py)
from ontario_area_lookup_tool import ONTARIO_TOOLS

# Add Ontario tools to agent
tools = [
    *ONTARIO_TOOLS,
    # ... other tools
]

# Update system prompt
from src.agent.prompts.ontario_system_prompt import ONTARIO_SYSTEM_PROMPT
agent = create_agent(
    tools=tools,
    system_prompt=ONTARIO_SYSTEM_PROMPT
)
```

---

## Data Sources

### Ontario GeoHub
- **URL:** https://geohub.lio.gov.on.ca
- **License:** Open Government Licence - Ontario
- **Datasets:**
  - Provincial Parks: `/datasets/provincial-parks`
  - Conservation Reserves: `/datasets/conservation-reserve-regulated`
  - Conservation Authorities: `/datasets/conservation-authority-regulated`
  - Municipalities: `/datasets/ontario-municipalities`
  - Watersheds: `/datasets/watershed-boundaries`
  - Forest Management Units: `/datasets/forest-management-units`
  - Ontario Hydro Network: `/datasets/ontario-hydro-network`
  - Wetlands: `/datasets/evaluated-wetlands`

### Conservation Ontario
- **URL:** https://co-opendata-camaps.hub.arcgis.com
- **Data:** Additional CA-specific datasets

### Federal Data
- **CPCAD:** https://www.canada.ca/en/environment-climate-change/services/national-wildlife-areas/protected-conserved-areas-database.html
- **Filter for Ontario:** `PROV_TERR = 'ON'`

---

## Validation Checklist

After running the sample code, verify:

### Database
- [ ] All tables created: `\dt ontario_*`
- [ ] Spatial indexes created: `\di idx_ont_*`
- [ ] Functions exist: `\df search_ontario_areas`
- [ ] Triggers created for updated_at

### Data
- [ ] Provincial parks: ~340 records
- [ ] Conservation Authorities: exactly 36
- [ ] All geometries valid: No invalid geometries
- [ ] Projection correct: All EPSG:4326

### Tools
- [ ] Area lookup returns results
- [ ] CA tool returns detailed info
- [ ] JSON parsing works for complex queries
- [ ] Errors handled gracefully

---

## Common Issues

### Issue: "relation ontario_provincial_parks does not exist"
**Solution:** Run the schema migration first: `psql -f 001_ontario_schema.sql`

### Issue: "No module named 'asyncpg'"
**Solution:** Install dependencies: `pip install asyncpg geopandas`

### Issue: "Unable to download parks data"
**Solution:** 
- Check Ontario GeoHub URL (may have changed)
- Download data manually and place in `data/ontario/parks/`
- Update URL in ingestion script

### Issue: "Invalid geometries found"
**Solution:** Add geometry repair in ingestion:
```python
geometry_wkt = row.geometry.buffer(0).wkt  # Repair geometry
```

### Issue: "Park count is 250, expected 340"
**Solution:** 
- Check if data source is filtered (e.g., only operating parks)
- Verify you're not filtering out draft or planned parks
- Check the GeoHub dataset description for coverage

---

## Next Steps

1. **Create more ingestion scripts** following the parks example:
   - Conservation Authorities
   - Watersheds
   - Wetlands
   - Forest Management Units

2. **Expand tool capabilities:**
   - Forest composition analysis
   - Water quality queries
   - Species distribution (if access granted)

3. **Add dataset catalog:**
   - Create `data/ontario_datasets_catalog.csv`
   - Generate embeddings for RAG
   - Enable intelligent dataset selection

4. **Customize agent prompts:**
   - Create `src/agent/prompts/ontario_system_prompt.py`
   - Add Ontario context and terminology
   - Include safety guidelines for sensitive data

5. **Set up frontend:**
   - Ontario branding
   - Map centered on Ontario
   - Ontario-specific example prompts

---

## Resources

### Documentation
- Main workplan: `../ontario-zeno-workplan.md`
- Implementation checklist: `../ontario-implementation-checklist.md`

### Ontario Resources
- Ontario GeoHub: https://geohub.lio.gov.on.ca
- Conservation Ontario: https://conservationontario.ca
- Ontario Parks: https://www.ontarioparks.com
- MNRF: https://www.ontario.ca/page/ministry-natural-resources-and-forestry

### Project Zeno
- GitHub: https://github.com/wri/project-zeno
- Documentation: Check the /docs directory

---

## Support

For questions or issues:
1. Check the main workplan for detailed explanations
2. Review Project Zeno's original documentation
3. Test queries against Ontario GeoHub directly
4. Validate database schema and indexes

---

**Last Updated:** 2024-11-14
**Version:** 1.0
**Compatibility:** Project Zeno main branch
