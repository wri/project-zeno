import json
from typing import Dict, List, Optional

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self


# Add this mixin to all models
class JSONSerializable(BaseModel):
    def to_dict(self):
        return json.loads(json.dumps(self, default=lambda o: o.dict()))


class Dataset(JSONSerializable):
    title: str = Field(description="The title of the dataset")
    dataset: str = Field(description="The slug of the dataset")
    explanation: str = Field(
        description="A one paragraph explanation of why this dataset is relevant to the user's problem"
    )
    uri: Optional[str] = Field(None, description="The URI of the dataset")
    tilelayer: Optional[str] = Field(None, description="The tilelayer of the dataset")
    score: bool = Field(
        description="Relevance score 'true' if the dataset is relvant and 'false' otherwise"
    )

    @model_validator(mode="after")
    def set_uri_and_tilelayer(self) -> Self:
        self.uri = f"https://data-api.globalforestwatch.org/dataset/{self.dataset}"
        self.tilelayer = f"https://tiles.globalforestwatch.org/{self.dataset}/latest/dynamic/{{z}}/{{x}}/{{y}}.png"
        return self


class LayerFinderResponse(JSONSerializable):
    datasets: List[Dataset]


haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)

layerfinder_agent = haiku.with_structured_output(LayerFinderResponse)
