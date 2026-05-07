"""Session module - DEPRECATED.

The ZenoSession class is no longer needed. The harness now uses LangGraph's
native state management (tools return Command to update state) and streaming
(stream_writer for custom events, astream for consuming).

Use create_zeno_agent() from factory.py and invoke it directly:

    agent = create_zeno_agent(model=my_model)
    async for event in agent.astream(
        {"messages": [HumanMessage(content=query)]},
        stream_mode=["updates", "custom"],
    ):
        ...
"""
