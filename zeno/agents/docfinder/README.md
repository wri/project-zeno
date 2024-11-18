# RAG Agent for Zeno

Mostly ported from the [Agentic RAG](https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_agentic_rag/)
blog post.

The agent is built against LLama for now, and can be used like this

```python
from langchain_core.messages import HumanMessage
from rag.agent import graph

query="How many users are using GFW and how long did it take to get there?"
for chunk in graph.stream({"messages": [HumanMessage(content=query)]}):
    for node_name, node_results in chunk.items():
        
        print(node_name, node_results["messages"][0].content)
```