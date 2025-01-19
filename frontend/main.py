import streamlit as st

st.set_page_config(page_title="Zeno", page_icon=":zap:")

st.title("Zeno")

st.write("Zeno is a helpful AI assistant.")

st.sidebar.success("Pick an agent")

st.markdown(
    """
Zeno is a helpful AI assistant.
It has a set of agents that can help you with different tasks.
1. Zeno - a general purpose agent that can help you with any task.
2. Distalert Agent - a tool that can help you with finding disturbance alerts.
3. DocFinder Agent - a tool that can help you with finding WRI & LCL documents.
4. LayerFinder Agent - a tool that can help you with finding relevant datasets hosted by WRI & LCL.
"""
)
