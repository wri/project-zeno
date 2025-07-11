import json
import uuid
from datetime import datetime

import altair as alt
import folium
import pandas as pd
import requests
import streamlit as st
from app import API_BASE_URL, STREAMLIT_URL
from shapely.geometry import shape
from streamlit_folium import folium_static

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
                "daterange": {
                    "start_date": "2020-01-01",
                    "end_date": "2023-12-31",
                    "years": [2020, 2021, 2022, 2023],
                    "period": "2020-2023",
                    "original_text": "2020 to 2023",
                },
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
                "daterange": {
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                    "years": [2024],
                    "period": "2024",
                    "original_text": "2024",
                },
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
        st.session_state["dataset_selected"] = DATASET_OPTIONS[
            selected_dataset_name
        ]
        st.session_state["dataset_acknowledged"] = False
        st.success(f"Selected Dataset: {selected_dataset_name}")
    elif selected_dataset_name == "None":
        st.session_state.pop("dataset_selected", None)
        st.session_state.pop("dataset_acknowledged", None)

    # Date Range Picker
    st.subheader("Date Range Selection")
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
            "years": None,
            "period": f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            "original_text": f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
        }

        # Check if daterange has changed
        if current_daterange != st.session_state.get("daterange_selected"):
            st.session_state["daterange_selected"] = current_daterange
            st.session_state["daterange_acknowledged"] = False
            st.success(f"Selected Date Range: {current_daterange['period']}")

    # Show current selections
    if st.session_state.get("aoi_selected"):
        st.info(f"Current AOI: {st.session_state['aoi_selected']['aoi_name']}")
    if st.session_state.get("dataset_selected"):
        st.info(
            f"Current Dataset: {st.session_state['dataset_selected']['dataset']['data_layer']}"
        )
    if st.session_state.get("daterange_selected"):
        st.info(
            f"Current Date Range: {st.session_state['daterange_selected']['period']}"
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


def render_aoi_map(aoi_data, subregion_data=None):
    """
    Render AOI geojson data as a map using streamlit-folium.

    Args:
        aoi_data: Dictionary containing geojson data for AOI
        subregion_data: Optional dictionary containing geojson data for subregion
    """
    try:
        # Extract geojson from aoi_data
        if isinstance(aoi_data, dict) and "geometry" in aoi_data:
            geojson_data = aoi_data["geometry"]

        # Calculate center from geojson bounds
        center = [0, 0]  # Default center

        if isinstance(geojson_data, dict):
            try:
                # Convert GeoJSON to shapely geometry
                geom = shape(geojson_data)

                # Get bounding box and calculate center
                minx, miny, maxx, maxy = geom.bounds
                center = [(miny + maxy) / 2, (minx + maxx) / 2]
            except (ValueError, AttributeError, TypeError):
                # If any error occurs during conversion, use default center
                center = [0, 0]

        # Create folium map
        m = folium.Map(location=center, zoom_start=5, tiles="OpenStreetMap")

        # Add AOI to map
        if geojson_data:
            folium.GeoJson(
                geojson_data,
                style_function=lambda feature: {
                    "fillColor": "gray",
                    "color": "gray",
                    "weight": 2,
                    "fillOpacity": 0.3,
                },
                popup=folium.Popup("Area of Interest", parse_html=True),
                tooltip="AOI",
            ).add_to(m)

        # Add subregions if provided
        if subregion_data and isinstance(subregion_data, list):
            try:
                for subregion in subregion_data:
                    if isinstance(subregion, dict) and "geometry" in subregion:
                        subregion_geojson = subregion["geometry"]
                        subregion_name = subregion.get("name", "Subregion")

                        folium.GeoJson(
                            subregion_geojson,
                            style_function=lambda feature: {
                                "fillColor": "red",
                                "color": "red",
                                "weight": 2,
                                "fillOpacity": 0.2,
                            },
                            popup=folium.Popup(
                                subregion_name, parse_html=True
                            ),
                            tooltip=subregion_name,
                        ).add_to(m)
            except Exception as e:
                st.warning(f"Could not render subregions: {str(e)}")

        # Display map in streamlit
        st.subheader("📍 Area of Interest")
        folium_static(
            m, width=700, height=400
        )  # st_folium stalls the UI - use folium_static instead

    except Exception as e:
        st.error(f"Error rendering map: {str(e)}")
        st.json(aoi_data)  # Fallback to show raw data


def render_dataset_map(dataset_data, aoi_data=None):
    """
    Render dataset tile layer as a map using streamlit-folium.

    Args:
        dataset_data: Dictionary containing dataset information with tile_url
        aoi_data: Optional dictionary containing geojson data for AOI overlay
    """
    try:
        # Extract tile_url from dataset_data
        tile_url = dataset_data.get("tile_url")
        if not tile_url:
            st.warning("No tile_url found in dataset")
            return

        # Calculate center from AOI if available, otherwise use default
        center = [0, 0]  # Default center
        zoom_start = 2  # Default zoom for global view

        if aoi_data and isinstance(aoi_data, dict) and "geometry" in aoi_data:
            try:
                # Convert GeoJSON to shapely geometry
                geom = shape(aoi_data["geometry"])

                # Get bounding box and calculate center
                minx, miny, maxx, maxy = geom.bounds
                center = [(miny + maxy) / 2, (minx + maxx) / 2]
                zoom_start = 5  # Closer zoom when AOI is available
            except (ValueError, AttributeError, TypeError):
                # If any error occurs during conversion, use default center
                center = [0, 0]
                zoom_start = 2

        # Create folium map
        m2 = folium.Map(
            location=center, zoom_start=zoom_start, tiles="OpenStreetMap"
        )

        # Add dataset tile layer
        dataset_name = dataset_data.get("data_layer", "Dataset Layer")
        folium.raster_layers.TileLayer(
            tiles=tile_url,
            attr="Dataset Tiles",
            name=dataset_name,
            overlay=True,
            control=True,
        ).add_to(m2)

        # Add AOI overlay if provided
        if aoi_data and isinstance(aoi_data, dict) and "geometry" in aoi_data:
            try:
                geojson_data = aoi_data["geometry"]
                folium.GeoJson(
                    geojson_data,
                    style_function=lambda feature: {
                        "fillColor": "blue",
                        "color": "blue",
                        "weight": 2,
                        "fillOpacity": 0.1,
                    },
                    popup=folium.Popup("Area of Interest", parse_html=True),
                    tooltip="AOI",
                ).add_to(m2)
            except Exception as e:
                st.warning(f"Could not render AOI overlay: {str(e)}")

        # Add layer control
        folium.LayerControl().add_to(m2)

        # Display map in streamlit
        st.subheader(f"🗺️ {dataset_name}")
        folium_static(m2, width=700, height=400)

        # Show dataset info
        with st.expander("Dataset Information"):
            dataset_info = {
                "Data Layer": dataset_data.get("data_layer", "N/A"),
                "Source": dataset_data.get("source", "N/A"),
                "Context Layer": dataset_data.get("context_layer", "N/A"),
                "Date Range": dataset_data.get("daterange", "N/A"),
                "Threshold": dataset_data.get("threshold", "N/A"),
            }
            for key, value in dataset_info.items():
                if value != "N/A":
                    st.write(f"**{key}:** {value}")

    except Exception as e:
        st.error(f"Error rendering dataset map: {str(e)}")
        st.json(dataset_data)  # Fallback to show raw data


def render_charts(charts_data):
    """
    Render charts using Altair based on charts_data schema.

    Args:
        charts_data: List of chart dictionaries with schema:
        {
            "id": "chart_1",
            "title": "Chart Title",
            "type": "bar|line|pie|area|scatter|table",
            "data": [{...}],
            "xAxis": "field_name",
            "yAxis": "field_name",
            "colorField": "field_name" (optional)
        }
    """
    try:
        if not charts_data or not isinstance(charts_data, list):
            return

        for chart in charts_data:
            if not isinstance(chart, dict):
                continue

            chart_title = chart.get("title", "Chart")
            chart_type = chart.get("type", "bar").lower()
            chart_data = chart.get("data", [])
            x_axis = chart.get("xAxis", "")
            y_axis = chart.get("yAxis", "")
            color_field = chart.get("colorField", "")

            if not chart_data or not x_axis or not y_axis:
                st.warning(f"Incomplete chart data for: {chart_title}")
                continue

            # Convert to DataFrame
            df = pd.DataFrame(chart_data)

            st.subheader(chart_title)

            # Display insight if available
            if "insight" in chart:
                st.info(chart["insight"])

            # Create chart based on type
            if chart_type == "bar":
                chart_obj = (
                    alt.Chart(df)
                    .mark_bar()
                    .encode(
                        x=alt.X(
                            f"{x_axis}:N",
                            title=x_axis.replace("_", " ").title(),
                        ),
                        y=alt.Y(
                            f"{y_axis}:Q",
                            title=y_axis.replace("_", " ").title(),
                        ),
                        color=alt.Color(f"{color_field}:N")
                        if color_field
                        else alt.value("steelblue"),
                    )
                    .properties(width=600, height=400, title=chart_title)
                )

            elif chart_type == "line":
                chart_obj = (
                    alt.Chart(df)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X(
                            f"{x_axis}:O",
                            title=x_axis.replace("_", " ").title(),
                        ),
                        y=alt.Y(
                            f"{y_axis}:Q",
                            title=y_axis.replace("_", " ").title(),
                        ),
                        color=alt.Color(f"{color_field}:N")
                        if color_field
                        else alt.value("steelblue"),
                    )
                    .properties(width=600, height=400, title=chart_title)
                )

            elif chart_type == "pie":
                chart_obj = (
                    alt.Chart(df)
                    .mark_arc()
                    .encode(
                        theta=alt.Theta(f"{y_axis}:Q"),
                        color=alt.Color(
                            f"{x_axis}:N",
                            title=x_axis.replace("_", " ").title(),
                        ),
                        tooltip=[f"{x_axis}:N", f"{y_axis}:Q"],
                    )
                    .properties(width=400, height=400, title=chart_title)
                )

            elif chart_type == "area":
                chart_obj = (
                    alt.Chart(df)
                    .mark_area()
                    .encode(
                        x=alt.X(
                            f"{x_axis}:O",
                            title=x_axis.replace("_", " ").title(),
                        ),
                        y=alt.Y(
                            f"{y_axis}:Q",
                            title=y_axis.replace("_", " ").title(),
                        ),
                        color=alt.Color(f"{color_field}:N")
                        if color_field
                        else alt.value("steelblue"),
                    )
                    .properties(width=600, height=400, title=chart_title)
                )

            elif chart_type == "scatter":
                chart_obj = (
                    alt.Chart(df)
                    .mark_point()
                    .encode(
                        x=alt.X(
                            f"{x_axis}:O",
                            title=x_axis.replace("_", " ").title(),
                        ),
                        y=alt.Y(
                            f"{y_axis}:Q",
                            title=y_axis.replace("_", " ").title(),
                        ),
                        color=alt.Color(f"{color_field}:N")
                        if color_field
                        else alt.value("steelblue"),
                    )
                    .properties(width=600, height=400, title=chart_title)
                )

            elif chart_type == "table":
                chart_obj = (
                    alt.Chart(df)
                    .mark_bar()
                    .encode(
                        x=alt.X(
                            f"{x_axis}:N",
                            title=x_axis.replace("_", " ").title(),
                        ),
                        y=alt.Y(
                            f"{y_axis}:Q",
                            title=y_axis.replace("_", " ").title(),
                        ),
                        color=alt.Color(f"{color_field}:N")
                        if color_field
                        else alt.value("steelblue"),
                    )
                    .properties(width=600, height=400, title=chart_title)
                )
            else:
                st.warning(f"Unsupported chart type: {chart_type}")
                continue

            st.altair_chart(chart_obj, use_container_width=True)

    except Exception as e:
        st.error(f"Error rendering charts: {str(e)}")
        st.json(charts_data)  # Fallback to show raw data


selected_aoi = st.session_state.get("aoi_selected")
selected_dataset = st.session_state.get("dataset_selected")
selected_daterange = st.session_state.get("daterange_selected")

# Extract aoi_data from selected AOI for use in chat processing
aoi_data = selected_aoi["aoi"] if selected_aoi else None


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
        client = ZenoClient(
            base_url=API_BASE_URL, token=st.session_state.token
        )
        for stream in client.chat(
            query=user_input,
            user_persona="Researcher",
            ui_context=ui_context,
            thread_id=st.session_state.session_id,
        ):
            node = stream["node"]
            update = json.loads(stream["update"])
            state_updates = "State Update: " + ", ".join(list(update.keys()))
            st.badge(state_updates, icon=":material/check:", color="green")

            for msg in update["messages"]:
                content = msg["kwargs"]["content"]
                if isinstance(content, list):
                    for msg in content:
                        if msg["type"] == "text":
                            st.text(msg["text"])
                        elif msg["type"] == "tool_use":
                            st.code(msg["name"])
                            st.code(msg["input"], language="json")
                else:
                    st.text(content)
            # Render map if this is a tool node with AOI data
            if node == "tools" and "aoi" in update:
                aoi_data = update["aoi"]
                subregion_data = (
                    update.get("subregion_aois")
                    if update.get("subregion") is not None
                    else None
                )
                render_aoi_map(aoi_data, subregion_data)

            # Render dataset map if this is a tool node with dataset data
            if node == "tools" and "dataset" in update:
                dataset_data = update["dataset"]
                aoi_data = (
                    update.get("aoi") or aoi_data
                )  # Include AOI as overlay if available
                render_dataset_map(dataset_data, aoi_data)

            # Render charts if this is a tool node with charts_data
            if node == "tools" and "charts_data" in update:
                charts_data = update["charts_data"]
                render_charts(charts_data)

            with st.expander("State Updates"):
                for key, value in update.items():
                    if key == "messages" or key == "aoi":
                        continue
                    st.badge(key)
                    st.code(value, language="json")
    st.session_state.messages.append({"role": "assistant", "content": content})
