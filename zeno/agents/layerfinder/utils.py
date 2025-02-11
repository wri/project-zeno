def make_context(docs):
    fmt_docs = []
    for doc in docs:
        dataset = doc.metadata["dataset"]
        content = f"Dataset: {dataset}\n{doc.page_content}"
        fmt_docs.append(content)

    # Join all formatted documents with double newlines
    return "\n\n".join(fmt_docs)
