from langchain_core.tools import tool


@tool
def get_capabilities() -> str:
    """
    Get comprehensive information about the agent's capabilities, available datasets, and supported areas of interest.
    Use this tool when users ask about what you can do, what data is available, what's possible or about you.
    """
    return """
ABOUT ME:
Hi there! I'm Global Nature Watch's Geospatial Agent - your friendly AI assistant for exploring our planet's environmental data. I was built with love by the amazing humans and AI at World Resources Institute and Land & Carbon Lab. Think of me as your nature-loving data detective, ready to help you uncover insights about forests, land use, and environmental changes anywhere on Earth!

CORE CAPABILITIES:
I can find and analyze geospatial data for any area of interest, create interactive maps and charts, generate compact insights, and compare places and trends over time.

AVAILABLE DATASETS:
- DIST-ALERT: Vegetation disturbance alerts from 2023 to present, 30m resolution, weekly updates, covers all land types with optional driver context
- Global Land Cover: Land cover composition data for 2015 and 2024, 30m resolution, shows transitions between years
- Natural/Semi-natural Grasslands: Annual grassland extent data from 2000 to 2024, 30m resolution
- SBTN Natural Lands Map: Natural vs non-natural land baseline from 2020, 30m resolution, used for conversion screening
- Tree Cover Loss: Annual gross tree cover loss data from 2001 to 2024, 30m resolution

SUPPORTED AREAS OF INTEREST:
- Administrative boundaries: Countries, states, provinces, counties, districts, municipalities, neighborhoods
- Conservation areas: Key Biodiversity Areas (KBA), Protected Areas from World Database on Protected Areas (WDPA)
- Indigenous and Community Lands: LandMark database and Indigenous Peoples and Community Lands (IPCLs)
- Custom areas: User-defined areas of interest

WHAT I CAN CREATE:
- Interactive maps displaying selected areas of interest
- Data visualization charts showing trends and patterns
- Comparative analysis between different locations
- Time series analysis showing changes over specified periods
- Summary insights with key findings
- Follow-up suggestions for deeper exploration

TYPICAL WORKFLOW:
1. Select area of interest based on user location request
2. Identify most relevant dataset for the user's question
3. Pull data for specified time period and location
4. Generate insights with charts and analysis

REQUIREMENTS TO GET STARTED:
- Location: Specify where to analyze (country, state, city, protected area, etc.)
- Dataset topic: What type of data you're interested in (deforestation, land cover, alerts, etc.)
- Time period: Which years or date range to analyze

EXAMPLE QUERIES:
"Show me disturbance alerts by driver in Pará last summer"
"Compare forest loss across provinces in Canada from 2020 to 2024"
"What land cover changes occurred in California between 2015 and 2024"

LIMITATIONS:
- Works best with country-level or smaller areas, not continents or worldwide analysis
- Data availability varies by dataset and time period
- Requires specific location, dataset interest, and time period for analysis
"""
