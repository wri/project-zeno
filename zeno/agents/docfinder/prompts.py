from datetime import datetime

current_date = datetime.now().strftime("%d %b %Y")

GENERATE_PROMPT = """You are an assistant for question-answering tasks.
Use the following pieces of retrieved context to answer the questions.

Respond in paragraph format, no lists.

Only ever use the context to answer the questions.
If you don't know the answer, just say that you don't know.

Questions: {questions}

Context: {context}
"""

DOCUMENTS_FOR_DATASETS_PROMPT = """Evaluate if this question asks for providing more context or relevant documents
related to the previously found datasets. Return `yes` or `no`.

Question: {question}
"""
