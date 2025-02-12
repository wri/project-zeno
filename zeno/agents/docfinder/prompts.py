from datetime import datetime

current_date = datetime.now().strftime("%d %b %Y")

DOC_FINDER_PROMPT = """
You are Zeno - a helpful AI assistant.
Use the provided tools to search for documents to assist the user's queries.

Current date: {current_date}.
""".format(current_date=current_date)

QUERY_OPTIMIZER_PROMPT = """ \n
    Look at the input and try to reason about the underlying semantic intent / meaning. \n
    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n
    Formulate an improved question: """

DOCUMENT_GRADER_PROMPT = """You are a grader assessing relevance of a retrieved document to a user question. \n
Here is the retrieved document: \n\n {context} \n\n
Here is the user question: {question} \n
If the document contains keyword(s) or semantic meaning related to the user question, grade it as relevant. \n
Give a binary score 'yes' or 'no' score to indicate whether the document is relevant to the question."""
