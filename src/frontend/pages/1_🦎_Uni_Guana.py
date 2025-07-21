import uuid
from datetime import datetime

import requests
import streamlit as st
from app import API_BASE_URL, STREAMLIT_URL

from client import ZenoClient
from utils import render_stream

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

    # AOI Selection Dictionary
    AOI_OPTIONS = {
        "None": None,
        "Odisha": {
            "aoi": {
                "name": "Odisha, India",
                "gadm_id": 1534,
                "GID_1": "IND.26_1",
                "subtype": "state-province",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [82.19806406848329, 21.82733671447052],
                            [82.19806406848329, 18.309508358985113],
                            [86.75537603715372, 18.309508358985113],
                            [86.75537603715372, 21.82733671447052],
                            [82.19806406848329, 21.82733671447052],
                        ]
                    ],
                },
            },
            "aoi_name": "Odisha",
            "subregion_aois": None,
            "subregion": None,
            "subtype": "state-province",
        },
        "Koraput": {
            "aoi": {
                "name": "Koraput, Odisha, India",
                "gadm_id": 22056,
                "GID_2": "IND.26.20_1",
                "subtype": "district-county",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [82.69889130216421, 18.823028264440254],
                            [82.69889130216421, 18.796325063722534],
                            [82.72949498909782, 18.796325063722534],
                            [82.72949498909782, 18.823028264440254],
                            [82.69889130216421, 18.823028264440254],
                        ]
                    ],
                },
            },
            "aoi_name": "Koraput",
            "subregion_aois": None,
            "subregion": None,
            "subtype": "district-county",
        },
    }

    # Dataset Selection Dictionary
    DATASET_OPTIONS = {
        "None": None,
        "Tree Cover Loss": {
            "dataset": {
                "dataset_id": 0,
                "source": "GFW",
                "data_layer": "Tree cover loss",
                "tile_url": "https://tiles.globalforestwatch.org/umd_tree_cover_loss/latest/dynamic/{z}/{x}/{y}.png?start_year=2001&end_year=2024&tree_cover_density_threshold=25&render_type=true_color",
                "context_layer": "Primary forest",
                "threshold": "30",
            }
        },
        "DIST_ALERT": {
            "dataset": {
                "dataset_id": 14,
                "source": "GFW",
                "data_layer": "DIST-ALERT",
                "tile_url": "https://tiles.globalforestwatch.org/umd_glad_dist_alerts/latest/dynamic/{z}/{x}/{y}.png?render_type=true_color",
                "context_layer": "driver",
                "threshold": None,
            }
        },
    }

    # AOI Dropdown
    selected_aoi_name = st.selectbox(
        "Select Area of Interest",
        options=list(AOI_OPTIONS.keys()),
        index=0,
        key="aoi_dropdown",
    )

    if selected_aoi_name != "None" and AOI_OPTIONS[
        selected_aoi_name
    ] != st.session_state.get("aoi_selected"):
        st.session_state["aoi_selected"] = AOI_OPTIONS[selected_aoi_name]
        st.session_state["aoi_acknowledged"] = False
        st.success(f"Selected AOI: {selected_aoi_name}")
        aoi_data = AOI_OPTIONS[selected_aoi_name]["aoi"]

    elif selected_aoi_name == "None":
        st.session_state.pop("aoi_selected", None)
        st.session_state.pop("aoi_acknowledged", None)
        aoi_data = None

    # Dataset Dropdown
    selected_dataset_name = st.selectbox(
        "Select Dataset",
        options=list(DATASET_OPTIONS.keys()),
        index=0,
        key="dataset_dropdown",
    )

    if selected_dataset_name != "None" and DATASET_OPTIONS[
        selected_dataset_name
    ] != st.session_state.get("dataset_selected"):
        st.session_state["dataset_selected"] = DATASET_OPTIONS[selected_dataset_name]
        st.session_state["dataset_acknowledged"] = False
        st.success(f"Selected Dataset: {selected_dataset_name}")
    elif selected_dataset_name == "None":
        st.session_state.pop("dataset_selected", None)
        st.session_state.pop("dataset_acknowledged", None)

    # Date Range Picker
    st.subheader("Date Range Selection")

    # Checkbox to enable/disable date range selection
    enable_date_range = st.checkbox(
        "Enable Date Range Filter",
        value=False,
        key="enable_date_range_checkbox",
        help="Check this box to filter data by date range",
    )

    if enable_date_range:
        col1, col2 = st.columns(2)

        with col1:
            start_date = st.date_input(
                "Start Date",
                value=datetime(2024, 1, 1).date(),
                min_value=datetime(2000, 1, 1).date(),
                max_value=datetime.now().date(),
                key="start_date_picker",
            )

        with col2:
            end_date = st.date_input(
                "End Date",
                value=datetime(2024, 12, 31).date(),
                min_value=datetime(2000, 1, 1).date(),
                max_value=datetime.now().date(),
                key="end_date_picker",
            )

        # Validate date range
        if start_date > end_date:
            st.error("Start date must be before end date")
        else:
            # Create daterange object
            current_daterange = {
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            }

            # Check if daterange has changed
            if current_daterange != st.session_state.get("daterange_selected"):
                st.session_state["daterange_selected"] = current_daterange
                st.session_state["daterange_acknowledged"] = False
                st.success(
                    f"Selected Date Range: {current_daterange['start_date']} to {current_daterange['end_date']}"
                )
    else:
        # Clear date range selection when disabled
        if st.session_state.get("daterange_selected") is not None:
            st.session_state["daterange_selected"] = None
            st.session_state["daterange_acknowledged"] = False
            st.info("Date range filter disabled")

    # Show current selections
    if st.session_state.get("aoi_selected"):
        st.info(f"Current AOI: {st.session_state['aoi_selected']['aoi_name']}")
    if st.session_state.get("dataset_selected"):
        st.info(
            f"Current Dataset: {st.session_state['dataset_selected']['dataset']['data_layer']}"
        )
    if st.session_state.get("daterange_selected"):
        st.info(
            f"Current Date Range: {st.session_state['daterange_selected']['start_date']} to {st.session_state['daterange_selected']['end_date']}"
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

if user_input := st.chat_input("Type your message here..."):
    ui_context = {}

    if selected_aoi and not st.session_state.get("aoi_acknowledged"):
        ui_context["aoi_selected"] = selected_aoi
        st.session_state["aoi_acknowledged"] = True
    if selected_dataset and not st.session_state.get("dataset_acknowledged"):
        ui_context["dataset_selected"] = selected_dataset
        st.session_state["dataset_acknowledged"] = True
    if selected_daterange and not st.session_state.get("daterange_acknowledged"):
        ui_context["daterange_selected"] = selected_daterange
        st.session_state["daterange_acknowledged"] = True

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        client = ZenoClient(base_url=API_BASE_URL, token=st.session_state.token)
        for stream in client.chat(
            query=user_input,
            user_persona="Researcher",
            ui_context=ui_context,
            thread_id=st.session_state.session_id,
        ):

            render_stream(stream)
