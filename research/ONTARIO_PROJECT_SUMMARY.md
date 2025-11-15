# Ontario Nature Watch - Project Summary & Handoff

## Executive Summary

This package contains everything needed to fork WRI's Project Zeno and customize it for Ontario, Canada, creating "Ontario Nature Watch" - a specialized AI agent for exploring Ontario's environmental data, conservation areas, and natural resources.

**Project Goal:** Create a production-ready, Ontario-focused version of the Global Nature Watch agent that understands Ontario's conservation system, protected areas, watersheds, and environmental data.

**Estimated Timeline:** 8-12 weeks
**Estimated Budget:** $80,000-$120,000 CAD
**Team Required:** 2-4 developers (backend, frontend, GIS, DevOps)

---

## Package Contents

### 📋 Planning Documents

1. **`ontario-zeno-workplan.md`** (75+ pages)
   - Complete technical specification
   - Detailed implementation plan
   - Data source inventory
   - Architecture modifications
   - Testing strategy
   - Deployment guide
   
   **Use this for:** Understanding the full scope and detailed requirements

2. **`ontario-implementation-checklist.md`** (25+ pages)
   - Phase-by-phase checklist
   - Quick reference guide
   - Verification steps
   - Common issues & solutions
   
   **Use this for:** Day-to-day implementation tracking

### 💻 Sample Code

3. **`sample_code/001_ontario_schema.sql`**
   - Complete database schema
   - Spatial indexes
   - Search functions
   - Helper functions
   
   **Use this to:** Set up your database structure

4. **`sample_code/ingest_ontario_parks.py`**
   - Example data ingestion script
   - Shows Ontario GeoHub integration
   - Validation logic
   - Error handling
   
   **Use this as:** Template for other ingestion scripts

5. **`sample_code/ontario_area_lookup_tool.py`**
   - LangChain tools for Ontario searches
   - Database integration
   - Example: Ontario Area Lookup
   - Example: Conservation Authority Info
   
   **Use this to:** Extend the agent with Ontario-specific capabilities

6. **`sample_code/.env.ontario.example`**
   - Complete environment configuration
   - All settings documented
   - Ontario-specific variables
   - Feature flags
   
   **Use this to:** Configure your deployment

7. **`sample_code/README.md`**
   - Quick start guide for sample code
   - Integration instructions
   - Troubleshooting tips
   
   **Use this as:** Getting started guide

---

## Key Differentiators from Original Project Zeno

### Geographic Focus
- **Original:** Global coverage, primarily WRI data sources
- **Ontario:** Ontario-only, provincial data sources (Ontario GeoHub, Conservation Ontario)

### Data Sources
- **Original:** GADM, WDPA, KBA, Landmark, WRI Analytics API
- **Ontario:** 
  - 340+ Provincial Parks
  - 36 Conservation Authorities
  - 290+ Conservation Reserves
  - 47 Forest Management Units
  - 300+ Watersheds
  - Great Lakes data
  - Ontario-specific biodiversity data

### Agent Knowledge
- **Original:** Global conservation context, general protected areas
- **Ontario:**
  - Conservation Authorities (unique to Ontario)
  - Provincial Park classification system
  - Ontario regions (Southern, Central, Eastern, Northern, Far North)
  - Great Lakes ecosystem
  - Ontario environmental legislation

### User Experience
- **Original:** Global search, world map
- **Ontario:** 
  - Ontario-centered map
  - Ontario-specific examples ("Find wilderness parks in Algonquin region")
  - Conservation Authority integration
  - Regional filtering (Northern vs Southern Ontario)

---

## What Makes This Different from Standard Geospatial Apps

### 1. Conversational Interface
Users ask questions in natural language:
- "Show me wilderness parks within 200km of Toronto"
- "What Conservation Authority manages the Grand River?"
- "Find wetlands along Lake Huron"

### 2. Intelligent Dataset Selection
The agent automatically selects relevant datasets using RAG:
- User: "I want to know about forest management"
- Agent: Selects Forest Resources Inventory, FMU data
- Returns: Forest composition, management plans, harvesting stats

### 3. Multi-Source Integration
Combines data from multiple sources seamlessly:
- Ontario GeoHub (provincial data)
- Conservation Ontario (watershed management)
- Federal CPCAD (national protected areas)
- Great Lakes Information Network (water quality)

### 4. Context-Aware Responses
Understands Ontario-specific context:
- "Conservation Authority" vs generic watershed management
- Provincial park classes (Wilderness vs Natural Environment)
- Regional distinctions (boreal forest in North, Carolinian in South)

---

## Critical Success Factors

### Data Quality ✓
- All 36 Conservation Authorities ingested (exactly)
- ~340 Provincial Parks (within range)
- Valid geometries (0 invalid)
- Consistent projection (EPSG:4326)

### Agent Accuracy ✓
- >90% correct responses on Ontario queries
- Proper terminology (Conservation Authority, not watershed district)
- Geographic context (knows Northern vs Southern Ontario)

### Performance ✓
- Spatial queries <2 seconds
- Agent responses <10 seconds
- Map rendering <3 seconds

### Completeness ✓
- All major protected area types covered
- Watershed data comprehensive
- Forest data accessible (at least summary level)

---

## Implementation Phases

### Phase 1: Foundation (Weeks 1-3)
**Goal:** Database and core data ingestion

**Deliverables:**
- PostgreSQL database with Ontario schema
- Provincial Parks ingested
- Conservation Authorities ingested
- Basic spatial queries working

**Success Criteria:**
- `SELECT COUNT(*) FROM ontario_provincial_parks` returns ~340
- `SELECT COUNT(*) FROM ontario_conservation_authorities` returns 36
- All geometries valid

### Phase 2: Agent (Weeks 4-6)
**Goal:** Ontario-specific agent capabilities

**Deliverables:**
- Ontario system prompts
- Ontario area lookup tool
- Conservation Authority tool
- Dataset RAG with Ontario catalog

**Success Criteria:**
- Agent correctly identifies Algonquin Provincial Park
- Agent explains what a Conservation Authority does
- Agent can search by region (Northern Ontario, etc.)

### Phase 3: Frontend (Weeks 7-8)
**Goal:** Ontario-branded user interface

**Deliverables:**
- Ontario branding and logo
- Map centered on Ontario
- Ontario example prompts
- Ontario context panel

**Success Criteria:**
- Landing page shows Ontario
- Example prompts work correctly
- Map loads Ontario layers

### Phase 4: Testing & Deployment (Weeks 9-12)
**Goal:** Production-ready system

**Deliverables:**
- Comprehensive test suite
- Documentation
- Deployment scripts
- Monitoring setup

**Success Criteria:**
- All tests passing
- Documentation complete
- Successfully deployed to staging
- Production deployment ready

---

## Data Acquisition Plan

### Immediate (No Barriers)
From Ontario GeoHub (Open Government License):
- Provincial Parks
- Conservation Reserves
- Conservation Authority boundaries
- Municipal boundaries
- Watersheds
- Ontario Hydro Network (water bodies)
- Forest Management Units

### Requires Download/Processing
- Forest Resources Inventory (large dataset, ~50GB)
  - **Recommendation:** Use simplified version or API-only access
- Canadian Protected Areas Database (filter for Ontario)

### May Require Special Access
- Species at Risk occurrences (sensitive data)
  - **Recommendation:** Use generalized locations only or exclude from MVP
- Real-time water quality data
  - **Recommendation:** Start with API integration if available

---

## Technology Stack

### Backend
- **Language:** Python 3.11+
- **Framework:** FastAPI
- **Database:** PostgreSQL 15+ with PostGIS 3.4+
- **LLM:** Claude Sonnet 4 (Anthropic) or GPT-4 (OpenAI)
- **Agent Framework:** LangGraph
- **Embeddings:** OpenAI text-embedding-3-small

### Frontend
- **Framework:** Next.js 14+
- **Mapping:** Leaflet or Mapbox GL JS
- **UI:** React, Tailwind CSS

### Infrastructure
- **Containerization:** Docker
- **Orchestration:** Kubernetes (production)
- **Monitoring:** Prometheus + Grafana
- **Observability:** Langfuse

### Data Processing
- **GIS:** GeoPandas, Fiona, Shapely
- **Downloads:** requests, urllib

---

## Risk Mitigation

### Technical Risks

**Risk:** Large datasets cause performance issues
- **Mitigation:** Use simplified geometries, implement tiling, add caching

**Risk:** Agent provides incorrect information
- **Mitigation:** Extensive testing, fact-checking layer, source attribution

**Risk:** Ontario data sources change or are deprecated
- **Mitigation:** Monitor sources, maintain update pipeline, document alternatives

### Data Risks

**Risk:** Cannot access all desired datasets
- **Mitigation:** Start with publicly available data, expand later with partnerships

**Risk:** Data quality issues (invalid geometries, missing attributes)
- **Mitigation:** Robust validation, geometry repair functions, data cleaning pipeline

### Operational Risks

**Risk:** Insufficient resources for ongoing maintenance
- **Mitigation:** Automate updates, comprehensive documentation, seek funding/partnerships

---

## Quick Start for Claude Code

### Step 1: Repository Setup (Day 1)
```bash
# Fork repositories
gh repo fork wri/project-zeno ontario-nature-watch-api
gh repo fork wri/project-zeno-next ontario-nature-watch-frontend

# Clone
git clone https://github.com/YOUR-ORG/ontario-nature-watch-api.git
cd ontario-nature-watch-api
```

### Step 2: Database Setup (Day 1)
```bash
# Create database
createdb ontario-nature-watch

# Apply schema
psql ontario-nature-watch -f sample_code/001_ontario_schema.sql

# Verify
psql ontario-nature-watch -c "\dt ontario_*"
```

### Step 3: Environment Configuration (Day 1)
```bash
# Copy environment file
cp sample_code/.env.ontario.example .env

# Edit (set DATABASE_URL, API keys)
nano .env
```

### Step 4: First Data Ingestion (Day 2)
```bash
# Adapt sample ingestion script
# Update URLs for Ontario GeoHub
# Run ingestion
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ontario-nature-watch"
python src/ingest/ingest_ontario_parks.py
```

### Step 5: Test Agent (Day 3)
```bash
# Add Ontario tools to agent
# Test with sample queries
python client.py "Show me Algonquin Provincial Park"
```

---

## Expected Outcomes

### User Experience
Users can:
- Ask questions about Ontario's natural areas in plain English
- Discover parks, conservation areas, and watersheds visually on a map
- Get detailed information about Conservation Authorities
- Understand forest composition and management
- Access water quality data for the Great Lakes
- Learn about species at risk (generalized locations)

### Data Coverage
System includes:
- 340+ Provincial Parks with facilities and boundaries
- 36 Conservation Authorities with jurisdiction and programs
- 290+ Conservation Reserves
- 300+ Watersheds with drainage information
- 47 Forest Management Units
- Major water bodies including Great Lakes shoreline
- Evaluated wetlands (Provincially Significant Wetlands)

### Capabilities
Agent can:
- Search areas by name, type, region, or size
- Calculate protected area coverage for any location
- Explain Conservation Authority responsibilities
- Describe forest composition for specific areas
- Provide watershed information and water quality data
- Understand and respond to Ontario-specific terminology

---

## Maintenance Plan

### Daily
- Monitor error logs
- Check system health metrics
- Respond to user reports

### Weekly
- Review agent conversation logs
- Check for data quality issues
- Update dataset catalog if new sources discovered

### Monthly
- Review and analyze usage patterns
- Update documentation
- Check for Ontario GeoHub updates

### Quarterly
- Refresh protected areas data (parks, reserves)
- Update Conservation Authority boundaries if changed
- Review and update agent prompts based on feedback

### Annually
- Update Forest Resources Inventory
- Review all data sources for changes
- Conduct comprehensive system audit
- Update dependencies and security patches

---

## Support Resources

### Documentation
- **Main Workplan:** Complete technical specification
- **Checklist:** Day-to-day implementation guide
- **Sample Code:** Working examples and templates

### External Resources
- **Ontario GeoHub:** https://geohub.lio.gov.on.ca
- **Conservation Ontario:** https://conservationontario.ca
- **Project Zeno:** https://github.com/wri/project-zeno

### Key Contacts
- Ontario GeoHub support: lio@ontario.ca
- Conservation Ontario: info@conservationontario.ca

---

## Success Metrics

### Technical Metrics
- ✅ Data coverage: >90% of Ontario protected areas
- ✅ Query performance: <2s for spatial searches
- ✅ Agent accuracy: >90% correct responses
- ✅ Uptime: >99% availability

### User Metrics
- ✅ Query success rate: >80% satisfactory results
- ✅ User satisfaction: >4.0/5.0 rating
- ✅ Return users: >30% within 30 days

### Impact Metrics
- ✅ Geographic coverage: Users from all Ontario regions
- ✅ Use cases: Education, planning, conservation, research
- ✅ Awareness: Increased understanding of Ontario's conservation system

---

## Next Actions

### Immediate (This Week)
1. ✅ Review all documentation thoroughly
2. ✅ Set up development environment
3. ✅ Create databases (development and test)
4. ✅ Configure environment variables
5. ✅ Apply database schema

### Short Term (Weeks 1-2)
1. ✅ Ingest core datasets (parks, CAs, watersheds)
2. ✅ Validate data quality
3. ✅ Create Ontario tools
4. ✅ Test basic agent queries

### Medium Term (Weeks 3-6)
1. ✅ Complete data ingestion
2. ✅ Customize agent fully
3. ✅ Set up frontend
4. ✅ Implement testing suite

### Long Term (Weeks 7-12)
1. ✅ Deploy to staging
2. ✅ User testing
3. ✅ Production deployment
4. ✅ Monitoring and maintenance setup

---

## Final Notes

### What This Project Achieves
- Makes Ontario's environmental data accessible through conversation
- Demonstrates the power of LLMs for geospatial discovery
- Creates a template for regional customization of global tools
- Supports environmental education and conservation planning

### What Makes It Valuable
- **Accessibility:** Complex geospatial data becomes conversational
- **Intelligence:** Automatic dataset selection and context understanding
- **Completeness:** Integrates multiple data sources seamlessly
- **Local Focus:** Deep Ontario knowledge, not shallow global coverage

### Why It Matters
- Increases public engagement with conservation data
- Supports environmental decision-making
- Showcases Ontario's environmental stewardship
- Enables new forms of environmental education

---

**Ready to Begin?**

Start with the implementation checklist (`ontario-implementation-checklist.md`) and work through Phase 1. Refer to the detailed workplan (`ontario-zeno-workplan.md`) when you need more context. Use the sample code as templates and adapt as needed.

Good luck with Ontario Nature Watch! 🍁

---

**Document Version:** 1.0
**Date:** 2024-11-14
**Author:** Project Planning Team
**For:** Claude Code Implementation
