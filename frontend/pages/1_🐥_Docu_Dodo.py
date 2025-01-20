import json
import os
import uuid

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")

if "docfinder_session_id" not in st.session_state:
    st.session_state.docfinder_session_id = str(uuid.uuid4())
if "docfinder_messages" not in st.session_state:
    st.session_state.docfinder_messages = []

st.header("Docu Dodo 🐥")
st.caption(
    "Zeno's Docu Dodo, a trusty agent that digs through documents to find the information you need."
)

with st.sidebar:
    st.header("🐥")
    st.write(
        """
    Docu Dodo is expert at finding useful information from WRI & LCL documents. Give it a try!
    """
    )

    st.subheader("🧐 Try asking:")
    st.write(
        """
    - How many users are using GFW and how long did it take to get there?
    """
    )


def display_message(message):
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    else:
        st.chat_message("assistant").write(message["content"])


def handle_stream_response(stream):
    for chunk in stream.iter_lines():
        data = json.loads(chunk.decode("utf-8"))
        message = {
            "role": "assistant",
            "type": "text",
            "content": data["content"],
        }
        st.session_state.docfinder_messages.append(message)
        display_message(message)


# Display chat history
for message in st.session_state.docfinder_messages:
    display_message(message)


if user_input := st.chat_input("Type your message here..."):
    message = {"role": "user", "content": user_input, "type": "text"}
    st.session_state.docfinder_messages.append(message)
    display_message(message)

    with requests.post(
        f"{API_BASE_URL}/stream/docfinder",
        json={
            "query": user_input,
            "thread_id": st.session_state.docfinder_session_id,
        },
        stream=True,
    ) as stream:
        handle_stream_response(stream)
