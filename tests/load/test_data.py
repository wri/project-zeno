"""Test data for load testing the Zeno chat endpoint."""

import random
from typing import Dict, Optional


class QueryPatterns:
    """Realistic query patterns for different user behaviors."""

    # Quick geographic queries (30% of traffic)
    QUICK_QUERIES = [
        "What's the deforestation rate in Brazil from 2020 to 2023?",
        "Show me protected areas in Costa Rica established between 2019-2024",
        "Climate data for Kenya from 2021 to 2023",
        "Forest loss in Indonesia 2020-2023",
        "Biodiversity hotspots in Madagascar - data from 2022 to 2024",
        "Rainfall patterns in India from 2020 to 2023",
        "Land use changes in Ghana between 2019 and 2023",
        "Tree cover in the Amazon from 2021 to 2024",
        "Conservation areas in Tanzania established 2020-2023",
        "Agricultural land in Bangladesh changes from 2020 to 2023",
        "Mangrove forests in Vietnam trends 2021-2024",
        "Desert expansion in Niger from 2020 to 2023",
        "Wetlands in Botswana changes between 2019 and 2023",
        "Mountain forests in Nepal data from 2022 to 2024",
        "Coral reefs near Australia health trends 2020-2023",
    ]

    # Complex analysis queries (50% of traffic)
    ANALYSIS_QUERIES = [
        "Compare deforestation rates between Brazil and Indonesia from 2020 to 2023, focusing on primary forest loss",
        "Analyze the correlation between rainfall patterns and agricultural productivity in sub-Saharan Africa",
        "What are the trends in protected area coverage across Southeast Asian countries in the last decade?",
        "Show me biodiversity threat levels in Central American countries and their protected area effectiveness",
        "Compare forest fire frequency and intensity between Australia and California over the past 5 years",
        "Analyze land use change patterns in the Congo Basin and their impact on wildlife corridors",
        "What's the relationship between climate variables and species distribution in the Himalayas?",
        "Track mangrove forest changes in the Sundarbans and their coastal protection value",
        "Compare carbon sequestration potential across different forest types in the Amazon",
        "Analyze the effectiveness of conservation interventions in East African savannas",
        "Show trends in urban expansion and its impact on surrounding ecosystems in major cities",
        "What are the patterns of illegal logging detection across tropical forest regions?",
        "Analyze water stress indicators and their correlation with agricultural land abandonment",
        "Compare marine protected area coverage and fish population trends in the Pacific",
        "Track glacier retreat patterns and their impact on downstream water availability",
    ]

    # Conversation starters for multi-turn interactions
    CONVERSATION_STARTERS = [
        "I'm studying forest conservation in tropical regions",
        "I need to understand climate impacts on agriculture",
        "I'm researching biodiversity loss patterns",
        "Show me data about coastal ecosystem changes",
        "I want to analyze protected area effectiveness",
        "Help me understand deforestation drivers",
        "I'm looking at wildlife habitat connectivity",
        "Can you help me with carbon storage analysis?",
        "I need information about water resource management",
        "Show me trends in sustainable land use practices",
    ]

    # Follow-up questions for conversations
    FOLLOW_UPS = [
        "Can you show me more detailed data?",
        "What about the trends over time?",
        "How does this compare to other regions?",
        "What are the main drivers behind this?",
        "Can you break this down by country?",
        "Show me this data on a map",
        "What's the seasonal variation?",
        "How reliable is this data?",
        "What are the policy implications?",
        "Can you export this analysis?",
        "What's the uncertainty in these estimates?",
        "Show me the raw data behind this",
        "How does this relate to climate change?",
        "What conservation actions are being taken?",
        "Can you visualize this differently?",
    ]


# Note: we are not using user personas for load testing currently
class UserPersonas:
    """Different user persona types that affect query patterns."""

    PERSONAS = [
        "researcher",
        "policy_maker",
        "conservationist",
        "journalist",
        "student",
        "consultant",
        "ngo_worker",
        "government_official",
        "academic",
        "data_analyst",
    ]

    @classmethod
    def get_random_persona(cls) -> str:
        """Get a random user persona."""
        return random.choice(cls.PERSONAS)


# Note: UI context is not used in load testing currently
class UIContextGenerator:
    """Generate realistic UI context for requests."""

    SAMPLE_AOIS = [
        {
            "id": "gadm_123",
            "name": "São Paulo",
            "source": "gadm",
            "subtype": "state-province",
            "country": "Brazil",
        },
        {
            "id": "kba_456",
            "name": "Maya Biosphere Reserve",
            "source": "kba",
            "subtype": "protected-area",
            "country": "Guatemala",
        },
        {
            "id": "gadm_789",
            "name": "Central Kenya",
            "source": "gadm",
            "subtype": "region",
            "country": "Kenya",
        },
    ]

    SAMPLE_DATASETS = [
        {
            "id": 1,
            "name": "Forest Change Analysis",
            "type": "raster",
            "temporal": True,
        },
        {
            "id": 2,
            "name": "Protected Areas Database",
            "type": "vector",
            "temporal": False,
        },
        {
            "id": 3,
            "name": "Climate Variables",
            "type": "raster",
            "temporal": True,
        },
    ]

    DATE_RANGES = [
        {"start": "2020-01-01", "end": "2023-12-31"},
        {"start": "2022-01-01", "end": "2023-12-31"},
        {"start": "2021-01-01", "end": "2022-12-31"},
        {"start": "2019-01-01", "end": "2023-12-31"},
    ]

    @classmethod
    def generate_ui_context(
        cls, include_selections: bool = False
    ) -> Optional[Dict]:
        """Generate realistic UI context data."""
        if not include_selections or random.random() < 0.3:
            return None

        context = {}

        # Sometimes include AOI selection
        if random.random() < 0.6:
            context["aoi_selected"] = random.choice(cls.SAMPLE_AOIS)

        # Sometimes include dataset selection
        if random.random() < 0.4:
            context["dataset_selected"] = random.choice(cls.SAMPLE_DATASETS)

        # Sometimes include date range
        if random.random() < 0.5:
            context["daterange_selected"] = random.choice(cls.DATE_RANGES)

        return context if context else None


class TestDataGenerator:
    """Main class for generating test data."""

    def __init__(self):
        self.query_patterns = QueryPatterns()
        self.personas = UserPersonas()
        self.ui_context = UIContextGenerator()

    def get_quick_query(self) -> Dict:
        """Generate a quick query request."""
        import uuid

        return {
            "query": random.choice(self.query_patterns.QUICK_QUERIES),
            "thread_id": str(uuid.uuid4()),
        }

    def get_analysis_query(self) -> Dict:
        """Generate an analysis query request."""
        import uuid

        return {
            "query": random.choice(self.query_patterns.ANALYSIS_QUERIES),
            "thread_id": str(uuid.uuid4()),
        }

    def get_conversation_starter(self) -> Dict:
        """Generate a conversation starter."""
        import uuid

        return {
            "query": random.choice(self.query_patterns.CONVERSATION_STARTERS),
            "thread_id": str(uuid.uuid4()),
        }

    def get_follow_up(self, thread_id: str) -> Dict:
        """Generate a follow-up question for existing conversation."""
        return {
            "query": random.choice(self.query_patterns.FOLLOW_UPS),
            "thread_id": thread_id,
        }
