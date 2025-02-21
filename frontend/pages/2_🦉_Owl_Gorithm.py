import json
import os
import uuid

import folium
import requests
import streamlit as st
from dotenv import load_dotenv
from folium_vectorgrid import VectorGridProtobuf
from streamlit_folium import folium_static

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")

if "layerfinder_session_id" not in st.session_state:
    st.session_state.layerfinder_session_id = str(uuid.uuid4())
if "layerfinder_messages" not in st.session_state:
    st.session_state.layerfinder_messages = []

st.header("Owl Gorithm 🦉")
st.caption(
    "Zeno's Owl Gorithm is a wise, data-savvy agent for discovering relevant datasets."
)

with st.sidebar:
    st.header("🦉")
    st.write(
        """
    Owl Gorithm is expert at finding relevant datasets hosted by WRI & LCL. It tries its best to find the dataset & explain why it is relevant to your query. Give it a try!
    """
    )

    st.subheader("🧐 Try asking:")
    st.write(
        """
        - My interest is in understanding tree cover loss, what datasets are available?
        - Suggest datasets to understand deforestation in Brazil
        - What data should I look at to better estimate above ground biomass in the Amazon?
    """
    )


def generate_markdown(data):
    meta = data.get("metadata", {})
    more_info = (
        f"\n[More Information]({meta.get('learn_more')})"
        if meta.get("learn_more")
        else ""
    )
    download = (
        f"\n\n[Download data]({meta.get('download_data')})"
        if meta.get("download_data")
        else ""
    )

    return f"""#### Overview
{meta.get('overview') or "N/A"}
{more_info}{download}

#### Function
{meta.get('function') or "N/A"}

#### Cautions
{meta.get('cautions') or "N/A"}

#### Citation
{meta.get('citation') or "N/A"}

#### Metadata
- **Date:** {meta.get('date_of_content') or "N/A"}
- **Update frequency:** {meta.get('frequency_of_updates', '')}
- **Source:** {meta.get('source') or "N/A"}
- **Tags:** {meta.get('tags', '')}
- **Spatial Resolution:** {meta.get('resolution') or "N/A"}
- **Geographic Coverage:** {meta.get('geographic_coverage') or "N/A"}
- **License:** {meta.get('license') or "N/A"}
- **Dataset ID:** {meta.get('gfw_dataset_id') or 'N/A'}
- **Data API:** [link]({meta.get('data_api_url', '#')})
- **Relevance score:** {meta.get('relevance') or "N/A"}
"""


def display_message(message):
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    elif message["role"] == "nodata":
        st.chat_message("assistant").write(message["content"])
    else:
        data = message["content"]
        header = f"""### {data.get('metadata', {}).get('title', 'Dataset')}

{data['explanation']}"""
        st.markdown(header)

        if "tilelayer" in message["content"]:
            m = folium.Map(location=[0, 0], zoom_start=1, tiles="cartodb positron")
            if ".pbf" in data["tilelayer"]:
                vc = VectorGridProtobuf(
                    data["tilelayer"],
                    data.get("metadata", {}).get("title", "GFW Dataset"),
                    {},
                ).add_to(
                    m
                )  # noqa: F841
            else:
                g = folium.TileLayer(
                    data["tilelayer"],
                    name=data["dataset"],
                    attr=data["dataset"],
                ).add_to(
                    m
                )  # noqa: F841
            folium_static(m, width=700, height=300)

        md_output = generate_markdown(data)
        with st.expander("More info", expanded=False):
            st.markdown(md_output, unsafe_allow_html=True)


def handle_stream_response(stream):
    irrelevant_messages = []
    data = None
    for chunk in stream.iter_lines():
        data = json.loads(chunk.decode("utf-8"))
        if "node" not in data:
            continue
        if data["node"] == "cautions":
            with st.expander("⚠️ Cautions Summary", expanded=False):
                st.markdown(data["content"])
        elif data["node"] == "docfinder":
            st.chat_message("assistant").write(data["content"])
        else:
            message = {
                "role": "assistant",
                "type": "text",
                "content": data["content"],
            }
            st.session_state.layerfinder_messages.append(message)
            if message["content"].get("is_relevant"):
                display_message(message)
            else:
                irrelevant_messages.append(message)

    with st.expander("Low relevance datasets", expanded=False):
        for message in irrelevant_messages:
            data = message["content"]
            header = f"""### {data.get('metadata', {}).get('title', 'Dataset')}

{data['explanation']}

Relevance: {data['metadata'].get('relevance')}"""
            st.markdown(header)
    if not irrelevant_messages and not data:
        message = {
            "role": "nodata",
            "content": "No relevant datasets found.",
            "type": "text",
        }
        st.session_state.layerfinder_messages.append(message)
        display_message(message)


# Display chat history
for message in st.session_state.layerfinder_messages:
    display_message(message)

if user_input := st.chat_input("Type your message here..."):
    message = {"role": "user", "content": user_input, "type": "text"}
    st.session_state.layerfinder_messages.append(message)
    display_message(message)

    with requests.post(
        f"{API_BASE_URL}/stream/layerfinder",
        json={
            "query": user_input,
            "thread_id": st.session_state.layerfinder_session_id,
        },
        stream=True,
    ) as stream:
        handle_stream_response(stream)
