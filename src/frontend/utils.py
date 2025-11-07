import json
import os
from datetime import datetime

import altair as alt
import folium
import pandas as pd
import streamlit as st
from shapely.geometry import shape
from streamlit_folium import folium_static

from client import ZenoClient

API_BASE_URL = os.environ.get(
    "API_BASE_URL",
    os.environ.get("LOCAL_API_BASE_URL", "http://localhost:8000"),
)


# TODO: move rendering logic to a separate module so
# that the threads can import
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
{meta.get("overview") or "N/A"}
{more_info}{download}

#### Function
{meta.get("function") or "N/A"}

#### Cautions
{meta.get("cautions") or "N/A"}

#### Citation
{meta.get("citation") or "N/A"}

#### Metadata
- **Date:** {meta.get("date_of_content") or "N/A"}
- **Update frequency:** {meta.get("frequency_of_updates", "")}
- **Source:** {meta.get("source") or "N/A"}
- **Tags:** {meta.get("tags", "")}
- **Spatial Resolution:** {meta.get("resolution") or "N/A"}
- **Geographic Coverage:** {meta.get("geographic_coverage") or "N/A"}
- **License:** {meta.get("license") or "N/A"}
- **Dataset ID:** {meta.get("gfw_dataset_id") or "N/A"}
- **Data API:** [link]({meta.get("data_api_url", "#")})
- **Relevance score:** {meta.get("relevance") or "N/A"}
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
        src_id = aoi_data.get("src_id")
        # fetch the geometry by src_id
        client = ZenoClient(
            base_url=API_BASE_URL, token=st.session_state.token
        )
        geom_response = client.fetch_geometry(
            source=aoi_data.get("source"), src_id=src_id
        )
        geojson_data = geom_response.get("geometry")

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
                tooltip=aoi_data.get("name", "AOI"),
            ).add_to(m)

        # Add subregions if provided
        if subregion_data and isinstance(subregion_data, list):
            try:
                for subregion in subregion_data:
                    if isinstance(subregion, dict):
                        subregion_source = subregion.get("source")
                        subregion_src_id = subregion.get("src_id")
                        subregion_geojson = client.fetch_geometry(
                            source=subregion_source, src_id=subregion_src_id
                        ).get("geometry")
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
                "Dataset ID": dataset_data.get("dataset_id", "N/A"),
                "Dataset Name": dataset_data.get("dataset_name", "N/A"),
                "Data Layer": dataset_data.get("data_layer", "N/A"),
                "Source": dataset_data.get("source", "N/A"),
                "Context Layer": dataset_data.get("context_layer", "N/A"),
                "Date Range": dataset_data.get("daterange", "N/A"),
                "Threshold": dataset_data.get("threshold", "N/A"),
                "Reason": dataset_data.get("reason", "N/A"),
                "Tile URL": dataset_data.get("tile_url", "N/A"),
                "Analytics API Endpoint": dataset_data.get(
                    "analytics_api_endpoint", "N/A"
                ),
                "Description": dataset_data.get("description", "N/A"),
                "Prompt Instructions": dataset_data.get(
                    "prompt_instructions", "N/A"
                ),
                "Methodology": dataset_data.get("methodology", "N/A"),
                "Cautions": dataset_data.get("cautions", "N/A"),
                "Function Usage Notes": dataset_data.get(
                    "function_usage_notes", "N/A"
                ),
                "Citation": dataset_data.get("citation", "N/A"),
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
            "type": "bar|line|pie|area|scatter|table|stacked-bar|grouped-bar",
            "data": [{...}],
            "xAxis": "field_name",
            "yAxis": "field_name",
            "colorField": "field_name" (optional),
            "stackField": "field_name" (optional, for stacked-bar),
            "groupField": "field_name" (optional, for grouped-bar),
            "seriesFields": ["field1", "field2", ...] (optional, for stacked-bar)
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
            xAxis = chart.get("xAxis", "")
            yAxis = chart.get("yAxis", "")
            colorField = chart.get("colorField", "")
            stackField = chart.get("stackField", "")
            groupField = chart.get("groupField", "")
            seriesFields = chart.get("seriesFields", [])

            # Validate required fields based on chart type
            if not chart_data or not xAxis:
                st.warning(f"Incomplete chart data for: {chart_title}")
                continue

            # For multi-series charts, seriesFields can replace yAxis
            if not yAxis and not seriesFields:
                st.warning(
                    f"Incomplete chart data for: {chart_title} (missing yAxis or seriesFields)"
                )
                continue

            # Convert to DataFrame
            df = pd.DataFrame(chart_data)

            st.subheader(chart_title)

            # Display insight if available
            if "insight" in chart:
                st.info(chart["insight"])

            # Create chart based on type
            if chart_type == "bar":
                # Handle multi-series bar charts
                if seriesFields:
                    # Transform data from wide to long format for multiple series
                    df_long = pd.melt(
                        df,
                        id_vars=[xAxis],
                        value_vars=seriesFields,
                        var_name="series",
                        value_name="value",
                    )
                    chart_obj = (
                        alt.Chart(df_long)
                        .mark_bar()
                        .encode(
                            x=alt.X(
                                f"{xAxis}:N",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                "value:Q",
                                title=yAxis if yAxis else "Value",
                            ),
                            color=alt.Color(
                                "series:N",
                                title="Series",
                            ),
                            xOffset=alt.XOffset("series:N"),
                            tooltip=[f"{xAxis}:N", "series:N", "value:Q"],
                        )
                        .properties(width=600, height=400, title=chart_title)
                    )
                else:
                    # Single-series bar chart
                    chart_obj = (
                        alt.Chart(df)
                        .mark_bar()
                        .encode(
                            x=alt.X(
                                f"{xAxis}:N",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                f"{yAxis}:Q",
                                title=yAxis.replace("_", " ").title(),
                            ),
                            color=(
                                alt.Color(f"{colorField}:N")
                                if colorField
                                else alt.value("steelblue")
                            ),
                        )
                        .properties(width=600, height=400, title=chart_title)
                    )

            elif chart_type == "line":
                # Handle multi-series line charts
                if seriesFields:
                    # Transform data from wide to long format for multiple series
                    df_long = pd.melt(
                        df,
                        id_vars=[xAxis],
                        value_vars=seriesFields,
                        var_name="series",
                        value_name="value",
                    )
                    chart_obj = (
                        alt.Chart(df_long)
                        .mark_line(point=True)
                        .encode(
                            x=alt.X(
                                f"{xAxis}:O",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                "value:Q",
                                title=yAxis if yAxis else "Value",
                            ),
                            color=alt.Color(
                                "series:N",
                                title="Series",
                            ),
                            tooltip=[f"{xAxis}:O", "series:N", "value:Q"],
                        )
                        .properties(width=600, height=400, title=chart_title)
                    )
                else:
                    # Single-series line chart
                    chart_obj = (
                        alt.Chart(df)
                        .mark_line(point=True)
                        .encode(
                            x=alt.X(
                                f"{xAxis}:O",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                f"{yAxis}:Q",
                                title=yAxis.replace("_", " ").title(),
                            ),
                            color=(
                                alt.Color(f"{colorField}:N")
                                if colorField
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
                        theta=alt.Theta(f"{yAxis}:Q"),
                        color=alt.Color(
                            f"{xAxis}:N",
                            title=xAxis.replace("_", " ").title(),
                        ),
                        tooltip=[f"{xAxis}:N", f"{yAxis}:Q"],
                    )
                    .properties(width=400, height=400, title=chart_title)
                )

            elif chart_type == "area":
                # Handle multi-series area charts
                if seriesFields:
                    # Transform data from wide to long format for multiple series
                    df_long = pd.melt(
                        df,
                        id_vars=[xAxis],
                        value_vars=seriesFields,
                        var_name="series",
                        value_name="value",
                    )
                    chart_obj = (
                        alt.Chart(df_long)
                        .mark_area()
                        .encode(
                            x=alt.X(
                                f"{xAxis}:O",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                "value:Q",
                                title=yAxis if yAxis else "Value",
                            ),
                            color=alt.Color(
                                "series:N",
                                title="Series",
                            ),
                            tooltip=[f"{xAxis}:O", "series:N", "value:Q"],
                        )
                        .properties(width=600, height=400, title=chart_title)
                    )
                else:
                    # Single-series area chart
                    chart_obj = (
                        alt.Chart(df)
                        .mark_area()
                        .encode(
                            x=alt.X(
                                f"{xAxis}:O",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                f"{yAxis}:Q",
                                title=yAxis.replace("_", " ").title(),
                            ),
                            color=(
                                alt.Color(f"{colorField}:N")
                                if colorField
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
                            f"{xAxis}:O",
                            title=xAxis.replace("_", " ").title(),
                        ),
                        y=alt.Y(
                            f"{yAxis}:Q",
                            title=yAxis.replace("_", " ").title(),
                        ),
                        color=(
                            alt.Color(f"{colorField}:N")
                            if colorField
                            else alt.value("steelblue")
                        ),
                    )
                    .properties(width=600, height=400, title=chart_title)
                )

            elif chart_type == "stacked-bar":
                # For stacked bar charts, we need to transform data to long format if seriesFields are provided
                if seriesFields:
                    # Transform data from wide to long format for stacking
                    df_long = pd.melt(
                        df,
                        id_vars=[xAxis],
                        value_vars=seriesFields,
                        var_name="category",
                        value_name="value",
                    )
                    chart_obj = (
                        alt.Chart(df_long)
                        .mark_bar()
                        .encode(
                            x=alt.X(
                                f"{xAxis}:N",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                "value:Q",
                                title="Value",
                            ),
                            color=alt.Color(
                                "category:N",
                                title="Category",
                            ),
                        )
                        .properties(width=600, height=400, title=chart_title)
                    )
                else:
                    # Use stackField if provided, otherwise use colorField for stacking
                    stack_field = stackField or colorField
                    chart_obj = (
                        alt.Chart(df)
                        .mark_bar()
                        .encode(
                            x=alt.X(
                                f"{xAxis}:N",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                f"{yAxis}:Q",
                                title=yAxis.replace("_", " ").title(),
                            ),
                            color=(
                                alt.Color(
                                    f"{stack_field}:N",
                                    title=stack_field.replace(
                                        "_", " "
                                    ).title(),
                                )
                                if stack_field
                                else alt.value("steelblue")
                            ),
                        )
                        .properties(width=600, height=400, title=chart_title)
                    )

            elif chart_type == "grouped-bar":
                # For grouped bar charts, use groupField to create side-by-side bars
                if groupField:
                    chart_obj = (
                        alt.Chart(df)
                        .mark_bar()
                        .encode(
                            x=alt.X(
                                f"{xAxis}:N",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                f"{yAxis}:Q",
                                title=yAxis.replace("_", " ").title(),
                            ),
                            color=alt.Color(
                                f"{groupField}:N",
                                title=groupField.replace("_", " ").title(),
                            ),
                            xOffset=alt.XOffset(f"{groupField}:N"),
                        )
                        .properties(width=600, height=400, title=chart_title)
                    )
                else:
                    # Fallback to regular bar chart if no groupField
                    chart_obj = (
                        alt.Chart(df)
                        .mark_bar()
                        .encode(
                            x=alt.X(
                                f"{xAxis}:N",
                                title=xAxis.replace("_", " ").title(),
                            ),
                            y=alt.Y(
                                f"{yAxis}:Q",
                                title=yAxis.replace("_", " ").title(),
                            ),
                            color=(
                                alt.Color(f"{colorField}:N")
                                if colorField
                                else alt.value("steelblue")
                            ),
                        )
                        .properties(width=600, height=400, title=chart_title)
                    )

            elif chart_type == "table":
                # For table type, display as a proper table instead of a chart
                st.dataframe(df, use_container_width=True)
                continue  # Skip the altair_chart rendering for tables

            else:
                st.warning(f"Unsupported chart type: {chart_type}")
                continue

            st.altair_chart(chart_obj, use_container_width=True)

    except Exception as e:
        st.error(f"Error rendering charts: {str(e)}")
        st.json(charts_data)  # Fallback to show raw data


def render_stream(stream):
    # node = stream["node"]
    update = json.loads(stream["update"])

    state_updates = "State Update: " + ", ".join(list(update.keys()))
    st.badge(state_updates, icon=":material/check:", color="green")
    if timestamp := stream.get("timestamp"):
        st.badge(timestamp, icon=":material/schedule:", color="blue")

    for msg in update["messages"]:
        msg_type = msg["kwargs"].get("type")
        if (
            msg_type == "tool"
            and msg["kwargs"].get("name") == "get_capabilities"
        ):
            continue

        content = msg["kwargs"]["content"]

        if isinstance(content, list):
            for content_item in content:
                if isinstance(content_item, dict):
                    if content_item["type"] == "text":
                        st.markdown(content_item["text"])
                    elif content_item["type"] == "thinking":
                        with st.expander("💭 Thinking...", expanded=False):
                            st.markdown(content_item["thinking"])
                    elif content_item["type"] == "tool_use":
                        st.code(content_item["name"])
                        st.code(content_item["input"], language="json")
                    else:
                        st.markdown(content_item)
                else:
                    st.markdown(content_item)
        else:
            st.markdown(content)
    # Render map if this is a tool node with AOI data
    aoi_data = None
    if "aoi" in update:
        aoi_data = update["aoi"]
        subregion_data = (
            update.get("subregion_aois")
            if update.get("subregion") is not None
            else None
        )
        render_aoi_map(aoi_data, subregion_data)

    # Render dataset map if this is a tool node with dataset data
    if "dataset" in update:
        dataset_data = update["dataset"]
        aoi_data = (
            update.get("aoi") or aoi_data
        )  # Include AOI as overlay if available
        render_dataset_map(dataset_data, aoi_data)

    # Render charts if this is a tool node with charts_data
    if "charts_data" in update:
        charts_data = update["charts_data"]
        thread_id = update.get("thread_id")
        checkpoint_id = update.get("checkpoint_id")
        client = ZenoClient(
            base_url=API_BASE_URL, token=st.session_state.token
        )

        render_charts(charts_data)

        if thread_id and checkpoint_id:
            st.download_button(
                label="Download data CSV",
                data=client.download_data(
                    thread_id=thread_id, checkpoint_id=checkpoint_id
                ),
                file_name=f"thread_{thread_id}_checkpoint_{checkpoint_id}_raw_data.csv",
                mime="text/csv",
            )

    # Render code blocks if this is a tool node with code_blocks
    if "code_blocks" in update:
        with st.expander("Code Blocks", expanded=False):
            code_blocks = "\n".join(update["code_blocks"])
            execution_outputs = "\n".join(update.get("execution_outputs", []))
            text_output = update.get("text_output")

            st.code(code_blocks, language="python")
            st.code(execution_outputs, language="python")
            st.markdown(text_output)

    with st.expander("State Updates"):
        for key, value in update.items():
            if key == "messages" or key == "aoi":
                continue
            st.badge(key)
            st.code(value, language="json")

    if not st.session_state.get("messages"):
        st.session_state.messages = []

    # st.session_state.messages.append({"role": "assistant", "content": content})


def display_sidebar_selections():
    # AOI Selection Dictionary
    AOI_OPTIONS = {
        "None": None,
        "Odisha": {
            "aoi": {
                "name": "Odisha, India",
                "gadm_id": "IND.26_1",
                "src_id": "IND.26_1",
                "subtype": "state-province",
            },
            "aoi_name": "Odisha",
            "subregion_aois": None,
            "subregion": None,
            "subtype": "state-province",
        },
        "Koraput": {
            "aoi": {
                "name": "Koraput, Odisha, India",
                "gadm_id": "IND.26.20_1",
                "src_id": "IND.26.20_1",
                "subtype": "district-county",
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
                "dataset_name": "Tree cover loss",
                "tile_url": "https://tiles.globalforestwatch.org/umd_tree_cover_loss/latest/dynamic/{z}/{x}/{y}.png?start_year=2001&end_year=2024&tree_cover_density_threshold=25&render_type=true_color",
                "context_layer": "Primary forest",
                "threshold": "30",
            }
        },
        "DIST_ALERT": {
            "dataset": {
                "dataset_id": 14,
                "source": "GFW",
                "dataset_name": "DIST-ALERT",
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

    elif selected_aoi_name == "None":
        st.session_state.pop("aoi_selected", None)
        st.session_state.pop("aoi_acknowledged", None)

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
            f"Current Dataset: {st.session_state['dataset_selected']['dataset']['dataset_name']}"
        )
    if st.session_state.get("daterange_selected"):
        st.info(
            f"Current Date Range: {st.session_state['daterange_selected']['start_date']} to {st.session_state['daterange_selected']['end_date']}"
        )
