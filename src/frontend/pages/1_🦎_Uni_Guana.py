import json
import uuid

import requests
import streamlit as st
from app import API_BASE_URL, STREAMLIT_URL

from client import ZenoClient

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
    - Find Tree cover loss in Odisha between 2015 - 2020
    - Find disturbance alerts & their main drivers in Koraput in first quarter of 2024
    """
    )

    if not st.session_state.get("token"):
        st.button(
            "Login with Global Forest Watch",
            on_click=lambda: st.markdown(
                f'<meta http-equiv="refresh" content="0;url=https://api.resourcewatch.org/auth?callbackUrl={STREAMLIT_URL}&token=true">',
                unsafe_allow_html=True,
            ),
        )
    else:
        user_info = requests.get(
            f"{API_BASE_URL}/api/auth/me",
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


# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input(
    (
        "Please login to start a chat..."
        if not st.session_state.get("token")
        else "Type your message here..."
    ),
    disabled=not st.session_state.get("token"),
):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        client = ZenoClient(
            base_url=API_BASE_URL, token=st.session_state.token
        )
        for stream in client.chat(
            user_input, thread_id=st.session_state.session_id
        ):
            node = stream["node"]
            update = json.loads(stream["update"])
            for msg in update["messages"]:
                content = msg["kwargs"]["content"]

                if isinstance(content, list):
                    for msg in content:
                        full_response += str(msg) + "\n"
                else:
                    full_response += str(content)
            message_placeholder.markdown(full_response + "▌")
        message_placeholder.markdown(full_response)
    st.session_state.messages.append(
        {"role": "assistant", "content": full_response}
    )
