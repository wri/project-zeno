from dotenv import load_dotenv

_ = load_dotenv(".env")

import json

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from zeno.tools.layerretrieve.layer_retrieve_tool import retriever

local_llm = "qwen2.5:7b"
# llm = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0)
llm = ChatOllama(model=local_llm, temperature=0)
# llm = ChatOpenAI(model="gpt-4o", temperature=0)


rag_prompt = """You are a World Resources Institute (WRI) assistant specializing in dataset recommendations.

Instructions:
1. Use the following context to inform your response:
{context}

2. User Question:
{question}

3. Response Format to be a valid JSON with list of datasets in the following format:
    {{
        "datasets": [
            {{
                "dataset": The slug of the dataset,
                "explanation": A two-line explanation of why this dataset is relevant to the user's problem
            }},
            ...
        ]
    }}
"""


def clean_json_response(response: str) -> dict:
    """Clean JSON response from LLM by removing any markdown formatting."""
    # Remove markdown code block indicators if present
    cleaned = response.strip().replace("```json", "").replace("```", "")
    # Parse the cleaned string into a dict
    return json.loads(cleaned)


def make_context(docs):
    fmt_docs = []
    for doc in docs:
        dataset = doc.metadata["dataset"]
        content = f"Dataset: {dataset}\n{doc.page_content}"
        fmt_docs.append(content)

    # Join all formatted documents with double newlines
    return "\n\n".join(fmt_docs)


def retrieve(state):
    print("---RETRIEVE---")
    question = state["question"]
    documents = retriever.invoke(question)
    return {"documents": documents}


def generate(state):
    print("---GENERATE---")
    question = state["question"]
    documents = state["documents"]
    loop_step = state.get("loop_step", 0)

    # RAG generation
    docs_txt = make_context(documents)
    rag_prompt_fmt = rag_prompt.format(context=docs_txt, question=question)
    generation = llm.invoke([HumanMessage(content=rag_prompt_fmt)])
    print("\n\n")
    print(generation.content)
    generation_content = clean_json_response(generation.content)
    print(generation_content)
    datasets = clean_json_response(generation.content)["datasets"]
    for dataset in datasets:
        dataset["uri"] = (
            f"https://data-api.globalforestwatch.org/dataset/{dataset['dataset']}"
        )
        dataset["tilelayer"] = (
            f"https://tiles.globalforestwatch.org/{dataset['dataset']}/latest/dynamic/{{z}}/{{x}}/{{y}}.png"
        )

    return {
        "messages": json.dumps(datasets),
        "loop_step": loop_step + 1,
        "route": "layerfinder",
    }
