import json
import os
import uuid

import folium

# import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

from streamlit_folium import st_folium

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")


if "gfw_session_id" not in st.session_state:
    st.session_state.gfw_session_id = str(uuid.uuid4())
if "waiting_for_input" not in st.session_state:
    st.session_state.waiting_for_input = False
if "gfw_messages" not in st.session_state:
    st.session_state.gfw_messages = []


# Add a callback function to reset the session state
def reset_state():
    st.session_state.gfw_session_id = str(uuid.uuid4())
    st.session_state.waiting_for_input = False
    st.session_state.gfw_messages = []


st.header("Investi Gator 🐊")
st.caption(
    "Zeno's Investi Gator is a curious agent hungry for data. It specializes in retrieving data from the Global Forest Watch API."
)

# Sidebar content
with st.sidebar:
    st.header("🐊")
    st.write(
        """
    "Zeno's Investi Gator is a curious agent hungry for data. It specializes in retrieving data from the Global Forest Watch API."
    """
    )

    st.subheader("🧐 Try asking:")
    st.write(
        """
    - What is current state of Cameroon's tree cover?
    - Which country has the most deforestation in the past 5 years?
    - Which state in Brazil has sequestered the most carbon? 
    """
    )


def display_message(message):
    """Helper function to display a single message"""
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    elif message["role"] == "assistant":
        if message["type"] == "location":

            st.chat_message("assistant").write("Found location you searched for...")
            data = message["content"]
            artifact = data.get("artifact", {})
            m = folium.Map(zoom_start=4)

            for _artifact in artifact:

                st.chat_message("assistant").write(_artifact["properties"])

                folium.GeoJson(_artifact).add_to(m)  # noqa: F841

            st_folium(m, width=700, height=500, returned_objects=[])
        elif message["type"] == "generated-query":
            data = message["content"]
            artifact = data["artifact"]

            st.chat_message("assistant").write(
                f"I've generated the following query: {artifact['sql_query']}."
            )

            st.chat_message("assistant").write(artifact["explanation"])

        elif message["type"] == "query-result":
            # st.write(message)

            st.chat_message("assistant").write(message["content"]["content"])
            data = message["content"]["artifact"]["data"]
            df = pd.DataFrame(data)
            st.table(data=df)

        else:
            st.chat_message("assistant").write(message["content"])


def handle_stream_response(stream):
    for chunk in stream.iter_lines():

        data = json.loads(chunk.decode("utf-8"))
        # Regular update messages from Zeno
        if data.get("type") == "update":
            message = {
                "role": "assistant",
                "type": "text",
                "content": data["content"],
            }
            st.session_state.gfw_messages.append(message)
            display_message(message)
        # Tool calls from Zeno
        elif data.get("type") == "tool_call":
            message = None
            if data.get("tool_name") == "location-tool":
                message = {
                    "role": "assistant",
                    "type": "location",
                    "content": data,
                }
            elif data.get("tool_name") == "relative-location-tool":
                message = {
                    "role": "assistant",
                    "type": "location",
                    "content": data,
                }
            # elif data.get("tool_name") == "generate-query-tool":

            #     message = {
            #         "role": "assistant",
            #         "type": "generated-query",
            #         "content": data,
            #     }
            # elif data.get("tool_name") == "execute-query-tool":
            #     message = {
            #         "role": "assistant",
            #         "type": "query-result",
            #         "content": data,
            #     }
            elif data.get("tool_name") == "explain-results-tool":
                message = {
                    "role": "assistant",
                    "type": "query-result",
                    "content": data,
                }

            else:
                message = {
                    "role": "assistant",
                    "type": "text",
                    "content": data["content"],
                }

            if message:
                message["avatar"] = "✅"
                st.session_state.gfw_messages.append(message)
                display_message(message)
        # Interrupted by human input
        elif data.get("type") == "interrupted":

            # payload = json.loads(data.get("payload"))
            # st.write(payload)
            # Store the state that we're waiting for input
            st.session_state.waiting_for_input = True
            # Add the interrupt message to the chat

            message = {
                "role": "assistant",
                "type": "text",
                "content": data["payload"],
            }
            st.session_state.gfw_messages.append(message)
            display_message(message)
            st.rerun()
        else:
            raise ValueError(f"Unknown message type: {data.get('type')}")


# Display chat history
for message in st.session_state.gfw_messages:
    display_message(message)

# Main chat input
if user_input := st.chat_input("Type your message here..."):
    # Add user message to history
    message = {"role": "user", "type": "text", "content": user_input}
    st.session_state.gfw_messages.append(message)
    display_message(message)

    # If we were waiting for input, this is a response to an interrupt
    query_type = "human_input" if st.session_state.waiting_for_input else "query"

    # Reset the waiting_for_input state
    if st.session_state.waiting_for_input:
        st.session_state.waiting_for_input = False

    with requests.post(
        f"{API_BASE_URL}/stream/gfw_data_api",
        json={
            "query": user_input,
            "thread_id": st.session_state.gfw_session_id,
            "query_type": query_type,
        },
        stream=True,
    ) as stream:
        handle_stream_response(stream)
