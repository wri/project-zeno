# Ontario Nature Watch - System Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE LAYER                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │           Next.js Frontend (ontario-nature-watch-frontend)      │   │
│  │                                                                   │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ Chat         │  │ Map View     │  │ Ontario Context      │  │   │
│  │  │ Interface    │  │ (Leaflet)    │  │ Panel                │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  │                                                                   │   │
│  │  Ontario Branding │ Example Prompts │ Regional Filters          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                           │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ HTTPS/WebSocket
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        API LAYER (FastAPI)                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                  LangGraph Agent                                │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  System Prompt: Ontario Nature Watch Context             │  │    │
│  │  │  - Conservation Authorities knowledge                     │  │    │
│  │  │  - Provincial Park system                                 │  │    │
│  │  │  - Ontario regions and geography                          │  │    │
│  │  │  - Great Lakes ecosystem                                  │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                                                                  │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │    │
│  │  │ Ontario      │  │ Conservation │  │ Ontario Analytics    │ │    │
│  │  │ Area Lookup  │  │ Authority    │  │ Tool                 │ │    │
│  │  │ Tool         │  │ Tool         │  │                      │ │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘ │    │
│  │                                                                  │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │    │
│  │  │ Forest Data  │  │ Great Lakes  │  │ Dataset RAG          │ │    │
│  │  │ Tool         │  │ Tool         │  │ (Vector Search)      │ │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘ │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  Connected to: Anthropic Claude API (or OpenAI)                          │
│                                                                           │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │         PostgreSQL 15 + PostGIS 3.4                             │    │
│  │                                                                  │    │
│  │  Ontario Tables:                                                │    │
│  │  ├─ ontario_provincial_parks          (~340 records)           │    │
│  │  ├─ ontario_conservation_authorities   (36 records)            │    │
│  │  ├─ ontario_conservation_reserves      (~290 records)          │    │
│  │  ├─ ontario_watersheds                 (300+ records)          │    │
│  │  ├─ ontario_municipalities             (444 records)           │    │
│  │  ├─ ontario_forest_management_units    (47 records)            │    │
│  │  ├─ ontario_waterbodies                (thousands)             │    │
│  │  ├─ ontario_wetlands                   (thousands)             │    │
│  │  └─ ontario_species_at_risk            (restricted)            │    │
│  │                                                                  │    │
│  │  Functions:                                                     │    │
│  │  ├─ search_ontario_areas()                                     │    │
│  │  └─ calculate_protected_area_coverage()                        │    │
│  │                                                                  │    │
│  │  Indexes: GiST spatial indexes on all geometries               │    │
│  │  Projection: EPSG:4326 (WGS84)                                 │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │         Vector Database (Chroma)                                │    │
│  │                                                                  │    │
│  │  Ontario Datasets Catalog Embeddings                            │    │
│  │  - Dataset descriptions                                         │    │
│  │  - Topics and keywords                                          │    │
│  │  - For intelligent dataset selection                            │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                           │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   EXTERNAL DATA SOURCES                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌──────────────────────┐  ┌──────────────────────┐                    │
│  │  Ontario GeoHub      │  │  Conservation        │                    │
│  │  (geohub.lio.gov)    │  │  Ontario             │                    │
│  │                      │  │  (co-opendata...)    │                    │
│  │  - Parks             │  │  - CA Programs       │                    │
│  │  - Reserves          │  │  - Watershed Data    │                    │
│  │  - Municipalities    │  │                      │                    │
│  │  - Watersheds        │  │                      │                    │
│  │  - FMUs              │  │                      │                    │
│  │  - Water bodies      │  │                      │                    │
│  └──────────────────────┘  └──────────────────────┘                    │
│                                                                           │
│  ┌──────────────────────┐  ┌──────────────────────┐                    │
│  │  CPCAD (Federal)     │  │  Great Lakes Info    │                    │
│  │  (canada.ca)         │  │  Network (GLIN)      │                    │
│  │                      │  │  (gis.glin.net)      │                    │
│  │  - Protected Areas   │  │  - Water Quality     │                    │
│  │  (Ontario subset)    │  │  - Lake Levels       │                    │
│  └──────────────────────┘  └──────────────────────┘                    │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

## Data Flow: User Query Example

```
User Query: "Show me wilderness parks in Northern Ontario"
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Frontend: Chat Interface                                    │
│  Sends: POST /api/chat with query                           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent: Processes query                                      │
│  1. Understands: "wilderness parks" = park_class             │
│  2. Understands: "Northern Ontario" = region filter          │
│  3. Selects tool: ontario_area_lookup                        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Ontario Area Lookup Tool                                    │
│  Executes: search_ontario_areas(                             │
│    query='wilderness',                                       │
│    area_types=['provincial_park'],                          │
│    region='Northern Ontario'                                │
│  )                                                           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Database: Spatial Query                                     │
│  SELECT * FROM ontario_provincial_parks                      │
│  WHERE park_class = 'wilderness'                            │
│    AND ST_Within(                                           │
│      geometry,                                              │
│      (SELECT geometry FROM ontario_regions                  │
│       WHERE name = 'Northern Ontario')                      │
│    )                                                        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Results: List of parks                                      │
│  - Killarney Provincial Park (49,000 ha)                    │
│  - Woodland Caribou Provincial Park (450,000 ha)            │
│  - Quetico Provincial Park (475,000 ha)                     │
│  - ... (with geometries)                                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent: Formats response                                     │
│  Creates natural language summary + structured data          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Frontend: Displays results                                  │
│  - Chat: "I found X wilderness parks in Northern Ontario"   │
│  - Map: Shows parks highlighted in green                    │
│  - List: Clickable park details                             │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### Frontend (Next.js)
**Responsibilities:**
- User interface and interaction
- Map rendering and visualization
- Ontario branding and theming
- Example prompts and help text
- Regional filtering UI

**Key Files:**
- `pages/index.tsx` - Main chat interface
- `components/Map/Map.tsx` - Map component
- `components/OntarioLayers.tsx` - Ontario-specific map layers
- `config/ontario-config.js` - Ontario configuration
- `styles/ontario-theme.css` - Ontario branding

### API (FastAPI)
**Responsibilities:**
- Request handling and routing
- Agent orchestration
- Tool coordination
- Response formatting
- Authentication (if enabled)

**Key Files:**
- `src/api/main.py` - API entry point
- `src/api/routes/chat.py` - Chat endpoint
- `src/api/routes/ontario.py` - Ontario-specific endpoints
- `src/api/ontario_analytics.py` - Analytics service

### Agent (LangGraph)
**Responsibilities:**
- Query understanding
- Tool selection
- Context management
- Response generation
- Multi-turn conversations

**Key Files:**
- `src/agent/agent.py` - Agent definition
- `src/agent/prompts/ontario_system_prompt.py` - System prompt
- `src/agent/tools/ontario_area_lookup.py` - Ontario tools
- `src/agent/tools/conservation_authority_tool.py` - CA tool

### Database (PostgreSQL + PostGIS)
**Responsibilities:**
- Spatial data storage
- Geometry operations
- Attribute queries
- Spatial indexes
- Data integrity

**Key Files:**
- `db/migrations/001_ontario_schema.sql` - Schema
- `db/functions/search_areas.sql` - Search function
- `db/indexes/spatial_indexes.sql` - Indexes

### Data Ingestion
**Responsibilities:**
- Download data from sources
- Transform to standard schema
- Validate geometries
- Load into database
- Update tracking

**Key Files:**
- `src/ingest/ingest_ontario_parks.py` - Parks
- `src/ingest/ingest_ontario_cas.py` - Conservation Authorities
- `src/ingest/ingest_ontario_watersheds.py` - Watersheds
- `src/ingest/embed_datasets.py` - Dataset embeddings

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Production Environment                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐     ┌──────────────┐    ┌──────────────┐ │
│  │              │     │              │    │              │ │
│  │  Frontend    │────▶│  API         │───▶│  Database    │ │
│  │  (Vercel)    │     │  (ECS/K8s)   │    │  (RDS)       │ │
│  │              │     │              │    │  PostGIS     │ │
│  └──────────────┘     └──────────────┘    └──────────────┘ │
│                              │                               │
│                              ▼                               │
│                       ┌──────────────┐                       │
│                       │  Langfuse    │                       │
│                       │  (Observ.)   │                       │
│                       └──────────────┘                       │
│                                                               │
│  ┌──────────────┐     ┌──────────────┐                      │
│  │  Redis       │     │  S3          │                      │
│  │  (Cache)     │     │  (Data)      │                      │
│  └──────────────┘     └──────────────┘                      │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Monitoring: Prometheus + Grafana                      │ │
│  │  Logs: CloudWatch / Loki                               │ │
│  │  Alerts: PagerDuty / Slack                             │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Ontario-Specific Components

### Conservation Authority Integration
```
Conservation Authority Tool
    │
    ├─ Lookup by name/acronym
    │   └─ Returns: jurisdiction, watersheds, programs
    │
    ├─ Get managed watersheds
    │   └─ Returns: list of watersheds with details
    │
    └─ Find by location
        └─ Returns: CA responsible for given coordinates
```

### Provincial Park System
```
Ontario Area Lookup Tool
    │
    ├─ Search by park class
    │   ├─ Wilderness
    │   ├─ Natural Environment
    │   ├─ Waterway
    │   ├─ Recreational
    │   ├─ Nature Reserve
    │   ├─ Cultural Heritage
    │   └─ Recreation Trail
    │
    ├─ Search by region
    │   ├─ Southern Ontario
    │   ├─ Central Ontario
    │   ├─ Eastern Ontario
    │   ├─ Northern Ontario
    │   └─ Far North
    │
    └─ Search by size
        └─ Returns: parks matching criteria
```

### Forest Management
```
Ontario Forest Tool (if implemented)
    │
    ├─ Get FMU information
    │   └─ Returns: management company, plan dates
    │
    ├─ Get forest composition
    │   └─ Returns: forest types, age classes
    │
    └─ Get harvest data
        └─ Returns: sustainable harvest info
```

## Scaling Considerations

### Database
- **Current:** Single PostgreSQL instance
- **Scale:** Read replicas for query distribution
- **Future:** Sharding by region if needed (unlikely for Ontario-only)

### API
- **Current:** Single API instance
- **Scale:** Horizontal scaling with load balancer
- **Future:** Auto-scaling based on traffic

### Caching
- **Current:** Redis for query results
- **Scale:** Redis cluster for high availability
- **Future:** CDN for static assets and common queries

### Data Updates
- **Current:** Weekly batch updates
- **Scale:** Real-time updates for time-sensitive data
- **Future:** Change detection and incremental updates

---

**Architecture Version:** 1.0  
**Last Updated:** 2024-11-14  
**Status:** Design Complete, Ready for Implementation
