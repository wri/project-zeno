import json
import os
import uuid

import folium
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import folium_static

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")

# Initialize session state variables
if "zeno_session_id" not in st.session_state:
    st.session_state.zeno_session_id = str(uuid.uuid4())
if "waiting_for_input" not in st.session_state:
    st.session_state.waiting_for_input = False
if "messages" not in st.session_state:
    st.session_state.messages = []

st.header("Zeno")
st.caption(
    "Your intelligent EcoBot, saving the forest faster than a 🐼 eats bamboo"
)

# Sidebar content
with st.sidebar:
    st.header("Meet Zeno!")
    st.write(
        """
    **Zeno** is your AI sidekick, trained on all your blog posts! It is a concious consumer and is consuming a local produce only. It can help you with questions about your blog posts. Give it a try!
    """
    )

    st.subheader("🧐 Try asking:")
    st.write(
        """
    - Provide data about disturbance alerts in Aveiro summarized by natural lands
    - What is happening with Gold Mining Deforestation?
    - What do you know about Forest Protection in remote islands in Indonesia?
    - How many users are using GFW and how long did it take to get there?
    - I am interested in understanding tree cover loss
    - I am interested in biodiversity conservation in Argentina
    - I would like to explore helping with forest loss in Amazon
    - Show datasets related to mangrooves
    - Find forest fires in milan for the year 2022
    - Show stats on forest fires over Ihorombe for 2021
    """
    )


def display_message(message):
    """Helper function to display a single message"""
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    elif message["role"] == "assistant":
        if message["type"] == "location":
            st.chat_message("assistant").write(
                "Found location you searched for..."
            )
            data = message["content"]
            artifact = data.get("artifact", {})
            artifact = artifact[0]

            # artifact is a single feature
            st.chat_message("assistant").write(artifact["properties"])

            geometry = artifact["geometry"]
            if geometry["type"] == "Polygon":
                pnt = geometry["coordinates"][0][0]
            else:
                pnt = geometry["coordinates"][0][0][0]
            m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=11)
            g = folium.GeoJson(artifact).add_to(m)  # noqa: F841
            folium_static(m, width=700, height=500)
        elif message["type"] == "alerts":
            st.chat_message("assistant").write(
                "Computing distributed alerts statistics..."
            )
            # plot the stats
            data = message["content"]
            stats = data.get("content", {})
            print(stats)
            stats = json.loads(stats)
            stats = {k: v for k, v in stats.items() if k != "landcover"}
            st.bar_chart(pd.DataFrame(stats))

            # plot the artifact which is a geojson featurecollection
            artifact = data.get("artifact", {})
            if artifact:
                first_feature = artifact["features"][0]
                geometry = first_feature["geometry"]
                if geometry["type"] == "Polygon":
                    pnt = geometry["coordinates"][0][0]
                else:
                    pnt = geometry["coordinates"][0][0][0]
                m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=11)
                g = folium.GeoJson(artifact).add_to(m)  # noqa: F841
                folium_static(m, width=700, height=500)
        elif message["type"] == "context":
            st.chat_message("assistant").write(
                f"Adding context layer {message['content']}"
            )
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
            st.session_state.messages.append(message)
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
            elif data.get("tool_name") == "dist-alerts-tool":
                message = {
                    "role": "assistant",
                    "type": "alerts",
                    "content": data,
                }
            elif data.get("tool_name") == "context-layer-tool":
                message = {
                    "role": "assistant",
                    "type": "context",
                    "content": data["content"],
                }
            else:
                message = {
                    "role": "assistant",
                    "type": "text",
                    "content": data["content"],
                }

            if message:
                message["avatar"] = "✅"
                st.session_state.messages.append(message)
                display_message(message)
        # Interrupted by human input
        elif data.get("type") == "interrupted":
            payload = json.loads(data.get("payload"))
            # Store the state that we're waiting for input
            st.session_state.waiting_for_input = True
            # Add the interrupt message to the chat
            message = {
                "role": "assistant",
                "type": "text",
                "content": f"Pick one of the options: {[row[0] for row in payload]}",
            }
            st.session_state.messages.append(message)
            display_message(message)
            st.rerun()
        else:
            raise ValueError(f"Unknown message type: {data.get('type')}")


# Display chat history
for message in st.session_state.messages:
    display_message(message)

# Main chat input
if user_input := st.chat_input("Type your message here..."):
    # Add user message to history
    message = {"role": "user", "type": "text", "content": user_input}
    st.session_state.messages.append(message)
    display_message(message)

    # If we were waiting for input, this is a response to an interrupt
    query_type = (
        "human_input" if st.session_state.waiting_for_input else "query"
    )

    # Reset the waiting_for_input state
    if st.session_state.waiting_for_input:
        st.session_state.waiting_for_input = False

    with requests.post(
        f"{API_BASE_URL}/stream",
        json={
            "query": user_input,
            "thread_id": st.session_state.zeno_session_id,
            "query_type": query_type,
        },
        stream=True,
    ) as stream:
        print(f"\nPOST... (query_type: {query_type})\n")
        handle_stream_response(stream)
