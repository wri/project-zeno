import streamlit as st
import requests
import os
from folium_vectorgrid import VectorGridProtobuf
from streamlit_folium import folium_static
from dotenv import load_dotenv
import folium
import json
import uuid

load_dotenv()
API_BASE_URL = os.environ.get("API_BASE_URL")

LOCAL_API_BASE_URL = os.environ["LOCAL_API_BASE_URL"]


if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "token" not in st.session_state:
    st.session_state["token"] = None


# Sidebar content
with st.sidebar:
    st.header("🐊")
    st.write(
        """
    "Zeno's Uniguana is a friendly, knowledgeable guide to the Land and Carbon lab data.
    """
    )

    st.subheader("🧐 Try asking:")
    st.write(
        """
    - What is current state of Cameroon's tree cover?
    - Find alerts over the Amazon distributed by natural lands layer for the year 2022?
    - What data should I look at to better estimate above ground biomass in the Amazon?
    """
    )

    if not st.session_state.get("token"):
        st.button(
            "Login with Global Forest Watch",
            on_click=lambda: st.markdown(
                '<meta http-equiv="refresh" content="0;url=https://api.resourcewatch.org/auth?callbackUrl=http://localhost:8501&token=true">',
                unsafe_allow_html=True,
            ),
        )
    else:

        user_info = requests.get(
            f"{LOCAL_API_BASE_URL}/api/auth/me",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {st.session_state['token']}",
            },
        )

        if user_info.status_code == 200:
            st.session_state["user"] = user_info.json()
            st.sidebar.success(
                f"""
                Logged in as {st.session_state['user']['name']}
                """
            )

    if st.session_state.get("user"):
        st.write("User info: ", st.session_state["user"])
        if st.button("Logout"):
            # NOTE: there is a logout endpoint in the API, but it only invalidates the browser cookies
            # and not the JWT. So in this case, we'll just clear the user info and token
            st.session_state.pop("user", None)
            st.session_state.pop("token", None)
            st.rerun()


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


def generate_doc_card(doc):
    return f"""### {doc["metadata"]["title"]}

{doc["page_content"]}

[{doc["metadata"]["link"]}]({doc["metadata"]["link"]})
"""


def display_message(message):
    if message["role"] == "cautions":
        with st.expander("⚠️ Cautions Summary", expanded=False):
            st.markdown(message["content"])
    elif message["role"] == "user":
        st.chat_message("user").write(message["content"])
    elif message["role"] in ["nodata"]:
        st.chat_message("assistant").write(message["content"])
    elif message["role"] == "docfinder":
        if isinstance(message["content"], list):
            with st.expander("Blog posts found", expanded=False):
                for doc in message["content"]:
                    st.markdown(generate_doc_card(doc))
        else:
            st.chat_message("assistant").write(message["content"])
    elif message["role"] == "irrelevant_datasets":
        with st.expander("Low relevance datasets", expanded=False):
            for data in message["content"]:
                header = f"""### {data.get('metadata', {}).get('title', 'Dataset')}

{data['explanation']}

Relevance: {data['metadata'].get('relevance')}"""
                st.markdown(header)
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

    for chunk in stream.iter_lines():
        if chunk:
            data = json.loads(chunk.decode("utf-8"))
            st.write(data)


# def handle_stream_response(stream):
#     irrelevant_messages = []
#     data = None
#     for chunk in stream.iter_lines():
#         data = json.loads(chunk.decode("utf-8"))
#         if "node" not in data:
#             continue
#         if data["node"] == "cautions":
#             message = {
#                 "role": "cautions",
#                 "content": data["content"],
#             }
#         elif data["node"] == "docfinder":
#             message = {
#                 "role": "docfinder",
#                 "content": data["content"],
#             }
#         else:
#             message = {
#                 "role": "assistant",
#                 "content": data["content"],
#             }
#             if not message["content"].get("is_relevant"):
#                 irrelevant_messages.append(data["content"])
#                 continue

#         st.session_state.messages.append(message)
#         display_message(message)

#     if irrelevant_messages:
#         message = {
#             "role": "irrelevant_datasets",
#             "content": irrelevant_messages,
#         }
#         st.session_state.messages.append(message)
#         display_message(message)
#     elif not data:
#         message = {
#             "role": "nodata",
#             "content": "No relevant datasets found.",
#         }
#         st.session_state.messages.append(message)
#         display_message(message)


# Display chat history
for message in st.session_state.messages:
    display_message(message)

if user_input := st.chat_input(
    (
        "Please login to start a chat..."
        if not st.session_state.get("token")
        else "Type your message here..."
    ),
    disabled=not st.session_state.get("token"),
):
    message = {"role": "user", "content": user_input, "type": "text"}
    st.session_state.messages.append(message)
    display_message(message)

    with requests.post(
        f"{LOCAL_API_BASE_URL}/api/chat",
        json={"query": user_input, "thread_id": st.session_state.session_id},
        headers={"Authorization": f"Bearer {st.session_state['token']}"},
        stream=True,
    ) as stream:

        handle_stream_response(stream)
