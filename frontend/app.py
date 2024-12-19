import json
import os
import uuid
from dotenv import load_dotenv
import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import folium_static

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")

# Initialize session state variables
if "zeno_session_id" not in st.session_state:
    st.session_state.zeno_session_id = str(uuid.uuid4())
if "current_options" not in st.session_state:
    st.session_state.current_options = None
if "current_question" not in st.session_state:
    st.session_state.current_question = None
if "messages" not in st.session_state:
    st.session_state.messages = []

st.header("Zeno")
st.caption("Your intelligent EcoBot, saving the forest faster than a 🐼 eats bamboo")

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
            st.chat_message("assistant").write("Found location you searched for...")
            data = message["content"]
            artifact = data.get("artifact", {})
            for feature in artifact["features"]:
                st.chat_message("assistant").write(
                    f"Found {feature['properties']['name']} in {feature['properties']['gadmid']}"
                )

            geometry = artifact["features"][0]["geometry"]
            if geometry["type"] == "Polygon":
                pnt = geometry["coordinates"][0][0]
            else:
                pnt = geometry["coordinates"][0][0][0]

            m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=11)
            g = folium.GeoJson(artifact).add_to(m)
            folium_static(m, width=700, height=500)
        elif message["type"] == "alerts":
            st.chat_message("assistant").write(
                "Computing distributed alerts statistics..."
            )
            table = json.loads(message["content"]["content"])
            st.bar_chart(pd.DataFrame(table).T)
        elif message["type"] == "context":
            st.chat_message("assistant").write(
                f"Adding context layer {message['content']}"
            )
        else:
            st.chat_message("assistant").write(message["content"])


def handle_human_input_submission(selected_index):
    if st.session_state.current_options and selected_index is not None:
        with requests.post(
            f"{API_BASE_URL}/stream",
            json={
                "query": str(selected_index),
                "thread_id": st.session_state.zeno_session_id,
                "query_type": "human_input",
            },
            stream=True,
        ) as response:
            print("\n POST HUMAN INPUT...\n")
            handle_stream_response(response)


def handle_stream_response(stream):
    for chunk in stream.iter_lines():
        data = json.loads(chunk.decode("utf-8"))

        if data.get("type") == "human_input":
            # Store the options and question in session state
            st.session_state.current_options = data["options"]
            st.session_state.current_question = data["question"]
            st.session_state.waiting_for_input = True
            st.rerun()

        elif data.get("type") == "tool_call":
            message = None
            if data.get("tool_name") == "location-tool":
                message = {"role": "assistant", "type": "location", "content": data}
            elif data.get("tool_name") == "dist-alerts-tool":
                message = {"role": "assistant", "type": "alerts", "content": data}
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
                st.session_state.messages.append(message)
                display_message(message)

        elif data.get("type") == "update":
            message = {"role": "assistant", "type": "text", "content": data["content"]}
            st.session_state.messages.append(message)
            display_message(message)
        else:
            raise ValueError(f"Unknown message type: {data.get('type')}")


# Display chat history
for message in st.session_state.messages:
    display_message(message)

# Handle human input interface if options are available
if st.session_state.current_options:
    selected_option = st.selectbox(
        st.session_state.current_question,
        st.session_state.current_options,
        key="selected_option",
    )
    selected_index = st.session_state.current_options.index(selected_option)
    if st.button("Submit"):
        handle_human_input_submission(selected_index)
        # Clear the options after submission
        st.session_state.current_options = None
        st.session_state.current_question = None

# Main chat input
if user_input := st.chat_input("Type your message here..."):
    # Add user message to history
    message = {"role": "user", "type": "text", "content": user_input}
    st.session_state.messages.append(message)
    display_message(message)

    with requests.post(
        f"{API_BASE_URL}/stream",
        json={
            "query": user_input,
            "thread_id": st.session_state.zeno_session_id,
            "query_type": "query",
        },
        stream=True,
    ) as stream:
        print("\nPOST...\n")
        handle_stream_response(stream)
