from langchain_anthropic import ChatAnthropic

from zeno.agents.docfinder.tool_document_retrieve import retriever_tool

haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)

tools = [retriever_tool]

docfinder_agent = haiku.bind_tools(tools)
