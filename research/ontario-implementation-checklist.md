# Ontario Nature Watch - Implementation Checklist

## Quick Start Guide for Claude Code

This is a condensed, actionable checklist for implementing the Ontario fork of Project Zeno. Refer to `ontario-zeno-workplan.md` for detailed explanations.

---

## PHASE 1: SETUP (Week 1)

### Repository Setup
- [ ] Fork `wri/project-zeno` to `ontario-nature-watch-api`
- [ ] Fork `wri/project-zeno-next` to `ontario-nature-watch-frontend`  
- [ ] Fork `wri/project-zeno-deploy` to `ontario-nature-watch-deploy`
- [ ] Update all `README.md` files with Ontario branding
- [ ] Update `pyproject.toml` project name to "ontario-nature-watch"

### Environment Files
- [ ] Copy `.env.example` to `.env.ontario.example`
- [ ] Add Ontario-specific variables:
  ```bash
  PROJECT_NAME="Ontario Nature Watch"
  REGION_FOCUS="Ontario, Canada"
  DEFAULT_MAP_CENTER="44.5,-79.5"
  ONTARIO_GEOHUB_API_KEY=<get_key>
  CONSERVATION_ONTARIO_API_KEY=<get_key>
  ```

### Database Schema
- [ ] Create migration: `db/migrations/001_ontario_schema.sql`
- [ ] Create tables:
  - `ontario_provincial_parks`
  - `ontario_conservation_authorities`
  - `ontario_conservation_reserves`
  - `ontario_forest_management_units`
  - `ontario_watersheds`
  - `ontario_waterbodies`
  - `ontario_municipalities`
- [ ] Add spatial indexes (GIST) on all geometry columns
- [ ] Create search function: `search_ontario_areas()`

---

## PHASE 2: DATA INGESTION (Weeks 2-3)

### Priority 1: Core Geographic Data
- [ ] Create `src/ingest/ingest_ontario_boundaries.py`
  - [ ] GADM Ontario (filter existing script)
  - [ ] Municipalities from Ontario GeoHub
  - [ ] Counties from Ontario GeoHub
- [ ] Run ingestion, verify with: `SELECT COUNT(*) FROM ontario_municipalities;`

### Priority 2: Protected Areas
- [ ] Create `src/ingest/ingest_ontario_protected_areas.py`
  - [ ] Provincial Parks: https://geohub.lio.gov.on.ca/datasets/provincial-parks
  - [ ] Conservation Reserves: https://geohub.lio.gov.on.ca/datasets/conservation-reserve-regulated
  - [ ] CPCAD Ontario subset
- [ ] Expected counts: ~340 parks, ~290 reserves
- [ ] Validate: `pytest tests/test_ontario_data_quality.py::test_provincial_parks_count`

### Priority 3: Conservation Authorities & Watersheds
- [ ] Create `src/ingest/ingest_ontario_watersheds.py`
  - [ ] Conservation Authority boundaries (should be exactly 36)
  - [ ] Watershed boundaries
- [ ] Validate: `pytest tests/test_ontario_data_quality.py::test_conservation_authorities_count`

### Priority 4: Water Resources
- [ ] Create `src/ingest/ingest_ontario_water.py`
  - [ ] Ontario Hydro Network (lakes, rivers)
  - [ ] Great Lakes shoreline data
  - [ ] Wetlands (evaluated wetlands)

### Priority 5: Forest Data (Optional - can defer)
- [ ] Create `src/ingest/ingest_ontario_forest.py`
  - [ ] Forest Management Units (47 FMUs)
  - [ ] Simplified FRI data (not full dataset due to size)

---

## PHASE 3: AGENT CUSTOMIZATION (Weeks 4-6)

### System Prompts
- [ ] Create `src/agent/prompts/ontario_system_prompt.py`
- [ ] Add Ontario context (geography, conservation system, authorities)
- [ ] Add Ontario terminology (Conservation Authorities, Provincial Parks classes)
- [ ] Include safety guidelines (species data, cultural sites)

### Ontario-Specific Tools
- [ ] Create `src/agent/tools/ontario_area_lookup.py`
  - Tool: `ontario_area_lookup`
  - Searches: provincial parks, CAs, municipalities, watersheds
- [ ] Create `src/agent/tools/conservation_authority_tool.py`
  - Tool: `conservation_authority_info`
  - Returns: jurisdiction, watersheds, programs
- [ ] Create `src/agent/tools/ontario_forest_tool.py` (if forest data ingested)
  - Tool: `ontario_forest_lookup`
  - Returns: FMU info, forest types
- [ ] Create `src/agent/tools/great_lakes_tool.py`
  - Tool: `great_lakes_data`
  - Returns: water quality, levels, shoreline info

### Update Main Agent
- [ ] Modify `src/agent/agent.py`:
  - Import Ontario tools
  - Add Ontario tools to tool list
  - Use `ONTARIO_SYSTEM_PROMPT` for Ontario deployment

### Dataset RAG
- [ ] Create `data/ontario_datasets_catalog.csv`
  - List all Ontario datasets with descriptions
  - Include: name, description, source, topics, coverage
- [ ] Update `src/ingest/embed_datasets.py`
  - Load Ontario catalog
  - Generate embeddings
  - Store in `data/ontario-datasets-index/`
- [ ] Run: `python src/ingest/embed_datasets.py`

### Analytics
- [ ] Create `src/api/ontario_analytics.py`
  - `get_protected_area_coverage(geometry)` - calculate coverage %
  - `get_forest_stats(geometry)` - forest type breakdown (if FRI available)
  - `get_watershed_info(geometry)` - watershed characteristics

---

## PHASE 4: TESTING (Weeks 7-8)

### Data Quality Tests
- [ ] Create `tests/test_ontario_data_quality.py`
  - Test park count (~340)
  - Test CA count (exactly 36)
  - Test geometry validity (all valid geometries)
  - Test projection (all EPSG:4326)
  - Test attribute completeness

### Agent Tests
- [ ] Create `tests/test_ontario_agent.py`
  - Test: Find Algonquin Park (should return correct park)
  - Test: Find Grand River CA (should return correct CA)
  - Test: Ontario forest types (should mention boreal, carolinian)
  - Test: Spatial queries (parks within 50km of Toronto)

### Performance Tests
- [ ] Create `tests/test_ontario_performance.py`
  - Spatial search <1 second
  - Geometry intersection <2 seconds
  - Agent response <10 seconds

### Run All Tests
- [ ] `pytest tests/test_ontario_data_quality.py -v`
- [ ] `pytest tests/test_ontario_agent.py -v`
- [ ] `pytest tests/test_ontario_performance.py -v`

---

## PHASE 5: FRONTEND (Weeks 9-10)

### Configuration
- [ ] Create `frontend/config/ontario-config.js`
  - App name, tagline
  - Default map center (44.5, -79.5)
  - Default zoom (6)
  - Color scheme (Ontario Green, Great Lakes Blue)
  - Example prompts (Ontario-specific)

### Branding
- [ ] Update `frontend/public/logo.png` with Ontario logo
- [ ] Update `frontend/public/favicon.ico`
- [ ] Update landing page imagery (Ontario landscapes)
- [ ] Update `frontend/components/Header.jsx` with Ontario branding

### Map Layers
- [ ] Create `frontend/components/Map/OntarioLayers.js`
  - Provincial Parks layer (green fill)
  - Conservation Authorities layer (blue outline)
  - Watersheds layer (light blue fill)
  - Municipalities layer (gray outline)
- [ ] Update `frontend/components/Map/Map.jsx` to load Ontario layers

### UI Components
- [ ] Create `frontend/components/OntarioContextPanel.jsx`
  - Geography section
  - Conservation system stats
  - Key features list
- [ ] Update example prompts in chat interface
- [ ] Add region filter (Southern, Central, Eastern, Northern, Far North)

---

## PHASE 6: DEPLOYMENT (Weeks 11-12)

### Infrastructure Setup
- [ ] Update `docker-compose.yaml` with Ontario-specific settings
- [ ] Create `helm/ontario-nature-watch/values-ontario.yaml`
  - App name, environment variables
  - Resource limits (CPU, memory)
  - Database persistence (100Gi)

### CI/CD
- [ ] Create `.github/workflows/ontario-data-refresh.yml`
  - Weekly data refresh (Sunday 2 AM)
  - Run ingestion scripts
  - Validate data quality
  - Alert on failure

### Monitoring
- [ ] Create `monitoring/ontario-alerts.yml`
  - Alert: Data staleness (>14 days)
  - Alert: Query performance degradation
  - Alert: Protected area coverage anomaly

### Documentation
- [ ] Create `docs/ONTARIO_CUSTOMIZATION.md`
- [ ] Create `docs/ONTARIO_USER_GUIDE.md`
- [ ] Create `docs/LICENSE_ATTRIBUTION.md`
- [ ] Update main `README.md` with Ontario focus

---

## DATA SOURCES TO ACCESS

### Ontario GeoHub
- **URL:** https://geohub.lio.gov.on.ca
- **Key Datasets:**
  - Provincial Parks: `/datasets/provincial-parks`
  - Conservation Reserves: `/datasets/conservation-reserve-regulated`
  - Conservation Authorities: `/datasets/conservation-authority-regulated`
  - Municipalities: `/datasets/ontario-municipalities`
  - FMUs: `/datasets/forest-management-units`
  - Watersheds: `/datasets/watershed-boundaries`
  - OHN (water): `/datasets/ontario-hydro-network`

### Conservation Ontario
- **URL:** https://co-opendata-camaps.hub.arcgis.com
- **Data:** Conservation Authority programs, watershed data

### Federal Sources
- **CPCAD:** https://www.canada.ca/en/environment-climate-change/services/national-wildlife-areas/protected-conserved-areas-database.html
- **Filter:** `PROV_TERR = 'ON'`

### Great Lakes Information Network
- **URL:** http://gis.glin.net/
- **Data:** Water quality, water levels

---

## VERIFICATION STEPS

After each phase, verify:

### After Setup
```bash
# Check database tables exist
psql $DATABASE_URL -c "\dt ontario_*"

# Should list all Ontario tables
```

### After Data Ingestion
```bash
# Check row counts
psql $DATABASE_URL -c "SELECT 
  'parks' as type, COUNT(*) FROM ontario_provincial_parks
  UNION ALL
  SELECT 'CAs', COUNT(*) FROM ontario_conservation_authorities
  UNION ALL
  SELECT 'watersheds', COUNT(*) FROM ontario_watersheds;"

# Expected: ~340 parks, 36 CAs, ~300+ watersheds
```

### After Agent Customization
```bash
# Test agent with sample query
python client.py "Show me Algonquin Provincial Park"

# Should return information about Algonquin
```

### After Frontend
```bash
# Start frontend
cd frontend && npm run dev

# Visit http://localhost:3000
# Check: Ontario branding, map centered on Ontario, example prompts
```

---

## COMMON ISSUES & SOLUTIONS

### Issue: Geometry invalid errors
**Solution:** Run `ST_MakeValid(geometry)` during ingestion

### Issue: Slow spatial queries
**Solution:** Ensure GIST indexes created: `CREATE INDEX idx_name ON table USING GIST(geometry);`

### Issue: Agent returns non-Ontario results
**Solution:** Add geographic filter in tools: `WHERE ST_Intersects(geometry, ontario_boundary)`

### Issue: Data ingestion fails (network/API errors)
**Solution:** Add retry logic, check API keys, verify URLs

### Issue: Provincial park count off
**Solution:** Check source data date, verify filters (some might be draft status)

---

## ESTIMATED TIMELINE

| Phase | Duration | Parallel Work? |
|-------|----------|----------------|
| Setup | 1 week | No |
| Data Ingestion | 2 weeks | Partially (can split datasets) |
| Agent Customization | 3 weeks | Some (prompts vs tools) |
| Testing | 1 week | No (needs complete system) |
| Frontend | 2 weeks | Yes (parallel with testing) |
| Deployment | 1 week | Partially |
| **Total** | **10 weeks** | **~8 weeks with parallelization** |

---

## CRITICAL SUCCESS FACTORS

1. ✅ **Data Quality:** All geometries valid, projections consistent
2. ✅ **Agent Accuracy:** >90% correct responses on Ontario queries
3. ✅ **Performance:** Spatial queries <2s, agent responses <10s
4. ✅ **Completeness:** All 36 CAs, ~340 parks, major watersheds ingested
5. ✅ **Documentation:** Clear setup, usage, and maintenance docs

---

## RESOURCES NEEDED

### API Keys
- [ ] Ontario GeoHub API key (if rate-limited): https://geohub.lio.gov.on.ca
- [ ] OpenAI/Anthropic API key for LLM
- [ ] (Optional) Mapbox or similar for base maps

### Software
- [ ] PostgreSQL 15+ with PostGIS 3.4+
- [ ] Python 3.11+
- [ ] Node.js 18+ (for frontend)
- [ ] Docker & Docker Compose

### Storage
- [ ] Database: ~100-120 GB
- [ ] File storage: ~20-30 GB
- [ ] Total: ~150 GB

### Team
- [ ] Backend developer: 4 weeks FTE
- [ ] Frontend developer: 2 weeks FTE
- [ ] GIS analyst: 1 week FTE (part-time for validation)
- [ ] DevOps: 1 week FTE (part-time for deployment)

---

## NEXT STEPS

1. **Review this checklist** and the detailed workplan
2. **Gather API keys** and access credentials
3. **Set up development environment** (fork repos, configure environment)
4. **Start with Phase 1** (setup and schema)
5. **Proceed sequentially** through phases
6. **Test continuously** (don't wait until end)
7. **Document as you go** (easier than retrospective documentation)

---

**Document Version:** 1.0  
**Companion Document:** `ontario-zeno-workplan.md`  
**Last Updated:** 2024-11-14
