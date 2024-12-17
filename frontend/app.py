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

if "zeno_session_id" not in st.session_state:
    st.session_state.zeno_session_id = str(uuid.uuid4())

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
    - Provide data about disturbance alerts in Aveiro summarized by landcover
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

def handle_stream_response(stream):
    for chunk in stream.iter_lines():
        data = json.loads(chunk.decode("utf-8"))

        if data.get("type") == "human_input":
            # Show a dropdown with options & a submit button
            selected_option = st.selectbox(data["question"], data["options"])
            if st.button("Submit"):
                # Send another POST request with the selected option
                with requests.post(
                    f"{API_BASE_URL}/stream",
                    json={
                        "query": selected_option,
                        "thread_id": st.session_state.zeno_session_id,
                        "query_type": "human_input"
                    },
                    stream=True,
                ) as response:
                    handle_stream_response(response)
        elif data.get("type") == "tool_call":
            if data.get("tool_name") == "location-tool":
                st.chat_message("assistant").write("Found location you searched for...")
                artifact = data.get("artifact", {})
                for feature in artifact["features"]:
                    st.chat_message("assistant").write(f"Found {feature['properties']['name']} in {feature['properties']['gadmid']}")

                # Add the artifact to the map
                geometry = artifact["features"][0]["geometry"]
                if geometry["type"] == "Polygon":
                    pnt = geometry["coordinates"][0][0]
                else:
                    pnt = geometry["coordinates"][0][0][0]

                m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=11)
                g = folium.GeoJson(
                    artifact,
                ).add_to(m)
                folium_static(m, width=700, height=500)
            elif data.get("tool_name") == "dist-alerts-tool":
                st.chat_message("assistant").write("Computing distributed alerts statistics...")
                table = json.loads(data["content"])
                st.bar_chart(pd.DataFrame(table).T)
            elif data.get("tool_name") == "context-layer-tool":
                st.chat_message("assistant").write(f"Adding context layer {data['content']}")
            else:
                st.chat_message("assistant").write(data["content"])
        elif data.get("type") == "update":
            st.chat_message("assistant").write(data["content"])
        else:
            raise ValueError(f"Unknown message type: {data.get('type')}")

if user_input := st.chat_input("Type your message here..."):
    st.chat_message("user").write(user_input)
    with requests.post(
        f"{API_BASE_URL}/stream",
        json={
            "query": user_input,
            "thread_id": st.session_state.zeno_session_id,
            "query_type": "query"
        },
        stream=True,
    ) as stream:
        handle_stream_response(stream)
