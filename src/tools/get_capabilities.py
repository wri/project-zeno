from langchain_core.tools import tool

from src.tools.datasets_config import DATASETS


def _load_datasets_info() -> str:
    """Load dataset information from the datasets configuration."""
    datasets_info = []
    for dataset in DATASETS:
        print(dataset.get("dataset_name"))
        name = dataset.get("dataset_name", "Unknown")
        content_date = dataset.get("content_date", "Unknown")
        resolution = dataset.get("resolution", "Unknown")
        update_frequency = dataset.get("update_frequency", "Unknown")
        description = dataset.get("description", "Unknown")

        # Create a concise description
        description_parts = []
        if content_date != "Unknown":
            description_parts.append(f"from {content_date}")
        if resolution != "Unknown":
            description_parts.append(f"{resolution} resolution")
        if update_frequency != "Unknown":
            description_parts.append(f"{update_frequency} updates")
        if description != "Unknown":
            description_parts.append(f"{description}")

        # Add context layers info if available
        context_layers = dataset.get("context_layers")
        if context_layers:
            context_desc = ", ".join(
                [layer.get("description", "") for layer in context_layers]
            )
            if context_desc:
                description_parts.append(f"with {context_desc.lower()}")

        description = (
            ", ".join(description_parts)
            if description_parts
            else "detailed environmental data"
        )
        datasets_info.append(f"- {name}: {description.capitalize()}")

    return "\n".join(datasets_info)


@tool("get_capabilities")
def get_capabilities() -> str:
    """
    Get comprehensive information about the agent's capabilities, available datasets, and supported areas of interest.
    Use this tool when users ask about what you can do, what data is available, what's possible or about you.
    """
    datasets_section = _load_datasets_info()

    return f"""ABOUT ME:
I am Global Nature Watch's Geospatial Agent, an AI assistant specialized in environmental data analysis and visualization. Developed by World Resources Institute and Land & Carbon Lab, I provide access to comprehensive geospatial datasets and analytical capabilities for monitoring forests, land use changes, and environmental trends worldwide.

CORE CAPABILITIES:
I can locate and analyze geospatial data for any specified area of interest, generate interactive visualizations and charts, produce data-driven insights, and perform comparative analysis across regions and time periods.

AVAILABLE DATASETS:
{datasets_section}

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
