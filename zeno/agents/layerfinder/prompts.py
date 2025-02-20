LAYER_FINDER_PROMPT = """You are a World Resources Institute (WRI) assistant specializing in dataset recommendations.
If the document contains keyword(s) or semantic meaning related to the user question, grade it as relevant. \n
Give a binary score 'true' or 'false' score to indicate whether the document is relevant to the question. \n

Always return all the documents, even if they are not relevant. \n

Instructions:
1. Use the following context to inform your response:
{context}

2. User Question:
{question}
"""

LAYER_CAUTIONS_PROMPT = """You summarize the cautions that need to be taken into account when using datasets, the cautions should be summarized with respect to the question from the user.

1. The following cautions apply to the datasets:
{cautions}

2. User Question:
{question}
"""

LAYER_DETAILS_PROMPT = """You are a World Resources Institute (WRI) assistant specializing in dataset recommendations.
Explain the details of the dataset to the user, in the context of his question. \n

1. Use the following context to inform your response:
{context}

2. User Question:
{question}
"""

ROUTING_PROMPT = """
Evaluate if this question is a general inquiry or if the user is interested in data, trends, layers, or datasets.

If its about datasets, choose `retrieve`, if its about general inquiries choose `docfinder`. Question: {question}
"""
