import json
import uuid

import requests
import streamlit as st
from app import API_BASE_URL, STREAMLIT_URL

from client import ZenoClient
from utils import display_sidebar_selections, render_stream

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

    st.subheader("UI Selections")

    display_sidebar_selections()

    if not st.session_state.get("token"):
        st.button(
            "Login with Global Forest Watch",
            key="login_uniguana",
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
                Logged in as {st.session_state["user"]["name"]}
                """
            )

    if st.session_state.get("user"):
        st.write("User info: ", st.session_state["user"])
        if st.button("Logout", key="logout_uniguana"):
            # NOTE: there is a logout endpoint in the API, but it only invalidates the browser cookies
            # and not the JWT. So in this case, we'll just clear the user info and token
            st.session_state.pop("user", None)
            st.session_state.pop("token", None)
            st.rerun()


selected_aoi = st.session_state.get("aoi_selected")
selected_dataset = st.session_state.get("dataset_selected")
selected_daterange = st.session_state.get("daterange_selected")

# Extract aoi_data from selected AOI for use in chat processing
aoi_data = selected_aoi["aoi"] if selected_aoi else None


# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

client = ZenoClient(base_url=API_BASE_URL, token=st.session_state.token)
quota_info = client.get_quota_info()
remaining_prompts = quota_info["promptQuota"] - quota_info["promptsUsed"]

if user_input := st.chat_input(
    f"Type your message here... (remaining prompts: {remaining_prompts})"
):
    ui_context = {}

    if selected_aoi and not st.session_state.get("aoi_acknowledged"):
        ui_context["aoi_selected"] = selected_aoi
        st.session_state["aoi_acknowledged"] = True
    if selected_dataset and not st.session_state.get("dataset_acknowledged"):
        ui_context["dataset_selected"] = selected_dataset
        st.session_state["dataset_acknowledged"] = True
    if selected_daterange and not st.session_state.get(
        "daterange_acknowledged"
    ):
        ui_context["daterange_selected"] = selected_daterange
        st.session_state["daterange_acknowledged"] = True

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        for stream in client.chat(
            query=user_input,
            user_persona="Researcher",
            ui_context=ui_context,
            thread_id=st.session_state.session_id,
        ):
            # Handle trace_info node to capture trace ID
            if stream.get("node") == "trace_info":
                update = json.loads(stream["update"])
                if "trace_id" in update:
                    st.session_state.current_trace_id = update["trace_id"]
                    st.success(f"🔍 Trace ID: {update['trace_id']}")
                continue

            render_stream(stream)
