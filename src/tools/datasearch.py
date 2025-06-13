from pathlib import Path
from typing import Any, Dict, List, Optional, Annotated
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.prompts import ChatPromptTemplate
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command

from pydantic import BaseModel, Field
import pandas as pd

from pylate import indexes, models, retrieve

data_dir = Path("data")
zeno_data = pd.read_csv(data_dir / "zeno_data_clean.csv")

# Load ColBERT model and index (pre-initialized for the agent)
colbert_model = models.ColBERT(model_name_or_path="lightonai/GTE-ModernColBERT-v1")
colbert_index = indexes.PLAID(
    index_folder=data_dir / "colbert-index",
    index_name="dataset"
)
colbert_retriever = retrieve.ColBERT(index=colbert_index)

# LLM
sonnet = ChatAnthropic(model="claude-3-7-sonnet-latest")

def rag_candidate_datasets(query: str, k=3):
    query_embedding = colbert_model.encode(
        query,
        batch_size=1,
        is_query=True,
        show_progress_bar=False
    )

    scores = colbert_retriever.retrieve(queries_embeddings=query_embedding, k=k)

    candidate_results = [
        zeno_data[zeno_data.dataset_id == int(score["id"])].iloc[0].to_dict()
        for score in scores[0]
    ]
    candidate_datasets = pd.DataFrame(candidate_results)
    return candidate_datasets

def select_best_dataset(query: str, candidate_datasets: pd.DataFrame):  
    class DatasetOption(BaseModel):
        id: int = Field(description="ID of the dataset that best matches the user query.")
        reason: str = Field(description="Short reason why the dataset is the best match.")


    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """Based on the query, return the ID of the dataset that can best answer the user query and provide reason why it is the best match.
    Look at the dataset description and contextual layers, as well as date & variables.

    Candidate datasets:

    {candidate_datasets}

    Query:

    {user_query}
    """,
            )
        ]
    )

    dataset_selection_chain = DATASET_SELECTION_PROMPT | sonnet.with_structured_output(DatasetOption)
    selection_result = dataset_selection_chain.invoke({
        "candidate_datasets": candidate_datasets[["dataset_id", "data_layer", "description", "context_layer", "date", "variables"]].to_csv(index=False),
        "user_query": query,
    })
    
    return selection_result
    
def extract_dataset_info(query: str, selection_id: int):
    class DateRange(BaseModel):
        # For precise ranges
        start_date: Optional[str] = Field(None, description="Start date in YYYY-MM-DD format if available")
        end_date: Optional[str] = Field(None, description="End date in YYYY-MM-DD format if available")
        # For sets of years
        years: Optional[List[int]] = Field(None, description="List of individual years requested")
        # For named periods
        period: Optional[str] = Field(None, description="Describes period like 'first half', 'Q2', etc.")
        # Original extracted string, for traceability
        original_text: Optional[str] = Field(None, description="The original date/daterange requested by the user")

    class DatasetInfo(BaseModel):
        dataset_id: int
        source: str
        data_layer: str
        context_layer: Optional[str] = Field(None, description="Pick a single context layer from the dataset if useful")
        daterange: Optional[DateRange] = None
        threshold: Optional[int] = None


    DATASET_PROMPT = ChatPromptTemplate.from_messages([
        ("user", """Given the user query and the dataset - extract the relevant information from the dataset to pull data from source.

    Dataset: 
    {dataset}

    User Query: 
    {user_query}    
    """),
    ])

    dataset_chain = DATASET_PROMPT | sonnet.with_structured_output(DatasetInfo)
    dataset_row = zeno_data[zeno_data.dataset_id == selection_id].iloc[0]
    final_info = dataset_chain.invoke({
        "user_query": query,
        "dataset": dataset_row.to_json(),
    })

    return final_info


@tool("pick-dataset")
def pick_dataset(query: str, tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """
    Given a user query, runs ColBERT RAG to retrieve relevant datasets, selects the best matching dataset with reasoning, and extracts relevant metadata needed for downstream querying.
    """
    # Step 1: ColBERT RAG lookup
    candidate_datasets = rag_candidate_datasets(query)

    # Step 2: LLM to select best dataset
    selection_result = select_best_dataset(query, candidate_datasets)

    # Step 3: LLM to extract structured info for downstream query
    dataset_info = extract_dataset_info(query, selection_result.id)

    tool_message = f"""
    Selected dataset: {dataset_info.data_layer}
    Context layer: {dataset_info.context_layer}
    Date range: {dataset_info.daterange}
    Threshold: {dataset_info.threshold}

    Reasoning: {selection_result.reason}
    """

    return Command(
        update={
            "dataset": dataset_info,
            "messages": [
                ToolMessage(
                    tool_message,
                    tool_call_id=tool_call_id
                )
            ],
        },
    )

if __name__ == "__main__":
    agent = create_react_agent(
        sonnet, 
        tools=[pick_dataset], 
        prompt="""You are a Data Agent that can ONLY HELP PICK a dataset using the `pick-dataset` tool.

        {instructions}
        """
    )

    user_queries = [
        "find threats to tigers in kbas of Odisha",
        "Show me forest data for congo not drc",
        "What is the deforestation rate in Ontario last year?",
        "I need urgent data on ilegal logging in Borgou!!",
        "How much tree cover has been lost in Sumatera since 2000?",
        "find threats to tigers in Simlipal Park",
        "find deforestation rate in Amazon",
        "find crocodile statistics in Satkosia Gorge",
        "find deforestation rate in PNG",
    ]

    for query in user_queries:
        for step in agent.stream({"messages": [{"role": "user", "content": query}]}, stream_mode="values"):
            message = step["messages"][-1]
            if isinstance(message, tuple):
                print(message)
            else:
                message.pretty_print()