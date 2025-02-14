from typing import Optional

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field


class Dataset(BaseModel):
    title: str = Field(description="The title of the dataset")
    dataset: str = Field(description="The uuid of the dataset")
    explanation: str = Field(
        description="A one paragraph explanation of why this dataset is relevant to the user's problem"
    )
    uri: Optional[str] = Field(None, description="The URI of the dataset")
    tilelayer: Optional[str] = Field(None, description="The tilelayer of the dataset")
    metadata: Optional[dict] = Field(
        None, description="GFW metadata record for the dataset"
    )
    is_relevant: Optional[bool] = Field(
        description="Relevance of the dataset, 'true' if the dataset is relvant and 'false' otherwise"
    )


haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)

layerfinder_agent = haiku.with_structured_output(Dataset)
