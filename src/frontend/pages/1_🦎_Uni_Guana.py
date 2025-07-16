import json
import uuid

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
                            popup=folium.Popup(subregion_name, parse_html=True),
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
        m2 = folium.Map(location=center, zoom_start=zoom_start, tiles="OpenStreetMap")

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
                        color=(
                            alt.Color(f"{color_field}:N")
                            if color_field
                            else alt.value("steelblue")
                        ),
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
                        color=(
                            alt.Color(f"{color_field}:N")
                            if color_field
                            else alt.value("steelblue")
                        ),
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
                        color=(
                            alt.Color(f"{color_field}:N")
                            if color_field
                            else alt.value("steelblue")
                        ),
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
                        color=(
                            alt.Color(f"{color_field}:N")
                            if color_field
                            else alt.value("steelblue")
                        ),
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
                        color=(
                            alt.Color(f"{color_field}:N")
                            if color_field
                            else alt.value("steelblue")
                        ),
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


# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input("Type your message here..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        client = ZenoClient(base_url=API_BASE_URL, token=st.session_state.get("token"))
        for stream in client.chat(user_input, thread_id=st.session_state.session_id):
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
