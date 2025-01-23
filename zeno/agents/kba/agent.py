from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field

from zeno.agents.kba.tool_kba_info import kba_info_tool


class KBAResponse(BaseModel):
    summary: str = Field(description="100 words summary of the response")
    analysis: str = Field(description="Detail analysis of the dataset")
    data: str = Field(
        description="CSV file with sitecode, siteName & any other relevant statistics or data points"
    )


haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)


tools = [kba_info_tool]
kba_info_agent = haiku.bind_tools(tools)
kba_response_agent = haiku.with_structured_output(KBAResponse)
