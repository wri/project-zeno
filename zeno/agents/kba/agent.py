import json

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field

from zeno.agents.kba.tool_kba_info import kba_info_tool

from pydantic import BaseModel, Field
from typing import List, Dict, Optional


# Add this mixin to all models
class JSONSerializable(BaseModel):
    def to_dict(self):
        return json.loads(json.dumps(self, default=lambda o: o.dict()))


class KBAMetrics(JSONSerializable):
    total_kbas: int
    threatened_kbas: int
    protected_coverage: float
    key_species: int
    habitat_types: List[Dict[str, float]]
    threat_categories: List[Dict[str, float]]


class RegionalStats(JSONSerializable):
    region_name: str
    kba_count: int
    protection_status: float
    primary_threats: List[str]
    trend: float  # positive/negative change


class KBAActionItem(JSONSerializable):
    priority: str  # "High", "Medium", "Low"
    area: str
    issue: str
    recommended_action: str
    expected_impact: str
    timeframe: str


class KBAResponse(JSONSerializable):
    summary: str = Field(
        description="Concise summary highlighting key patterns and critical insights, formatted as markdown with highlighing and bolding."
    )
    metrics: KBAMetrics = Field(description="Core KBA statistics for visualization")
    regional_breakdown: List[RegionalStats] = Field(
        description="Geographic distribution and trends"
    )
    actions: List[KBAActionItem] = Field(description="Prioritized conservation actions")
    data_gaps: List[str] = Field(description="Missing or incomplete data areas")


# haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)
sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0)


tools = [kba_info_tool]
kba_info_agent = sonnet.bind_tools(tools)
kba_response_agent = sonnet.with_structured_output(KBAResponse)
