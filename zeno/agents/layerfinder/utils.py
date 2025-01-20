import json


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
