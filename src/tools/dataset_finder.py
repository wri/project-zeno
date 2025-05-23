import os
from typing import Optional
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langchain_chroma import Chroma
from langchain_ollama.embeddings import OllamaEmbeddings
from pydantic import BaseModel, Field
from multiprocessing import Pool

from zeno.agents.layerfinder.prompts import LAYER_FINDER_PROMPT


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

dataset_finder_agent = haiku.with_structured_output(Dataset)


def call_agent(prompt):
    dataset = dataset_finder_agent.invoke([HumanMessage(content=prompt)])
    return dataset.model_dump()

embedder = OllamaEmbeddings(
    model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
)
db = Chroma(
    persist_directory="data/chroma_layers",
    embedding_function=embedder,
    create_collection_if_not_exists=False,
    collection_metadata={"hnsw:M": 1024,"hnsw:ef": 64}
)

@tool("dataset-finder-tool", return_direct=True)
def dataset_finder_tool(question: str) -> list[Dataset]:
    """
    Finds the most relevant datasets for the user's question.
    """
    print("dataset finder tool")
    search_results = db.similarity_search_with_relevance_scores(
        question,
        k=10,
        score_threshold=0.3,
    )
    documents = []
    for doc, score in search_results:
        doc.metadata.update(relevance=score)
        documents.append(doc)

    prompts = []
    for doc in documents:
        prompt = LAYER_FINDER_PROMPT.format(
            context=f"Dataset: {doc.metadata['dataset']}\n{doc.page_content}",
            question=question,
        )
        prompts.append(prompt)

    if prompts:
        with Pool(len(prompts)) as p:
            datasets = p.map(call_agent, prompts)
    else:
        datasets = []

    for dataset in datasets:
        doc = [doc for doc in documents if doc.metadata["dataset"] == dataset["dataset"]][
            0
        ]
        dataset["metadata"] = doc.metadata
        # TODO: check missing keys, also `zeno_id`
        # TODO: Change the embedder from Ollama to OpenAI or something else
        # dataset.uri = doc.metadata["gfw_metadata_url"]
        # dataset.tilelayer = doc.metadata["gfw_tile_url"]

    return datasets

    
    
    
    




