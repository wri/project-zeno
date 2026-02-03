import json
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
import requests
import streamlit as st
from app import API_BASE_URL, STREAMLIT_URL, ZENO_API_KEY

st.set_page_config(page_title="Labs Monitoring", page_icon="📊", layout="wide")


def render_aoi_selection(aoi_selection: dict):
    """Render AOI selection section."""
    st.subheader("🗺️ Areas of Interest")
    aois = aoi_selection.get("aois", [])
    if aois:
        aoi_df = pd.DataFrame(aois)
        display_cols = ["name", "aoi_type", "subtype", "src_id"]
        display_cols = [c for c in display_cols if c in aoi_df.columns]
        st.dataframe(aoi_df[display_cols], use_container_width=True)
    else:
        st.info("No areas of interest found.")


def render_dataset_info(dataset: dict):
    """Render dataset information section."""
    st.subheader("📁 Dataset")
    if dataset:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Dataset ID", dataset.get("dataset_id", "N/A"))
        with col2:
            st.metric("Dataset Name", dataset.get("dataset_name", "N/A"))
        with col3:
            st.metric(
                "Context Layer", dataset.get("context_layer", "None") or "None"
            )

        with st.expander("Dataset Details"):
            if dataset.get("description"):
                st.write("**Description:**", dataset.get("description"))
            if dataset.get("methodology"):
                st.write("**Methodology:**", dataset.get("methodology"))
            if dataset.get("cautions"):
                st.warning(f"**Cautions:** {dataset.get('cautions')}")
            if dataset.get("citation"):
                st.caption(f"**Citation:** {dataset.get('citation')}")


def render_analytics_data(analytics_data: list):
    """Render analytics data section."""
    st.subheader("📊 Analytics Data")
    if analytics_data:
        for i, analytics_item in enumerate(analytics_data):
            with st.expander(
                f"Data Source {i + 1}: {analytics_item.get('dataset_name', 'Unknown')}",
                expanded=(i == 0),
            ):
                st.write(
                    f"**AOIs:** {', '.join(analytics_item.get('aoi_names', []))}"
                )
                st.write(
                    f"**Period:** {analytics_item.get('start_date')} to {analytics_item.get('end_date')}"
                )
                if analytics_item.get("source_url"):
                    st.caption(f"Source: {analytics_item.get('source_url')}")

                # Display the data
                raw_data = analytics_item.get("data", {})
                if raw_data:
                    if isinstance(raw_data.get("data"), list):
                        df = pd.DataFrame(raw_data["data"])
                        st.dataframe(df, use_container_width=True)

                        if len(df) > 0:
                            st.write(f"**Rows:** {len(df)}")
                            numeric_cols = df.select_dtypes(
                                include=["number"]
                            ).columns
                            if len(numeric_cols) > 0:
                                st.write("**Summary Statistics:**")
                                st.dataframe(
                                    df[numeric_cols].describe(),
                                    use_container_width=True,
                                )
                    else:
                        st.json(raw_data)
    else:
        st.info("No analytics data available.")


def render_insights(insights: list, insights_error: str = None):
    """Render insights section."""
    st.subheader("💡 Insights")
    if insights:
        for insight in insights:
            st.info(insight)
    else:
        if insights_error:
            st.error(f"Insights generation error: {insights_error}")
        else:
            st.info("No insights generated.")


def render_charts(charts_data: list):
    """Render charts section."""
    st.subheader("📈 Charts")
    if charts_data:
        for chart in charts_data:
            with st.container():
                st.write(f"**{chart.get('title', 'Chart')}**")
                st.caption(chart.get("insight", ""))

                chart_type = chart.get("type", "bar")
                chart_data = chart.get("data", [])

                if chart_data:
                    df = pd.DataFrame(chart_data)

                    x_axis = chart.get("xAxis") or chart.get("x_axis", "")
                    y_axis = chart.get("yAxis") or chart.get("y_axis", "")

                    if chart_type == "bar":
                        if x_axis and y_axis and x_axis in df.columns:
                            st.bar_chart(df, x=x_axis, y=y_axis)
                        else:
                            st.bar_chart(df)
                    elif chart_type == "line":
                        if x_axis and y_axis and x_axis in df.columns:
                            st.line_chart(df, x=x_axis, y=y_axis)
                        else:
                            st.line_chart(df)
                    elif chart_type == "area":
                        if x_axis and y_axis and x_axis in df.columns:
                            st.area_chart(df, x=x_axis, y=y_axis)
                        else:
                            st.area_chart(df)
                    else:
                        st.dataframe(df, use_container_width=True)

                st.divider()
    else:
        st.info("No charts available.")


def render_codeact_parts(codeact_parts: list):
    """Render code execution parts section."""
    if codeact_parts:
        st.subheader("🔧 Code Execution")
        for part in codeact_parts:
            with st.expander(f"Code Part: {part.get('type', 'unknown')}"):
                if part.get("code"):
                    st.code(part.get("code"), language="python")
                if part.get("output"):
                    st.text(part.get("output"))


def render_follow_ups(follow_ups: list):
    """Render follow-up suggestions section."""
    if follow_ups:
        st.subheader("💭 Follow-up Suggestions")
        for suggestion in follow_ups:
            st.write(f"• {suggestion}")


if "token" not in st.session_state:
    st.session_state["token"] = None

# Auto-authenticate with machine user API key if available
if ZENO_API_KEY and not st.session_state.get("token"):
    st.session_state["token"] = ZENO_API_KEY

# Sidebar content
with st.sidebar:
    st.header("📊 Labs Monitoring")
    st.write(
        """
    Query the Labs Monitoring endpoint to pull data for specified areas and datasets.
    View analytics data, insights, and charts.
    """
    )

    if not st.session_state.get("token"):
        st.button(
            "Login with Global Forest Watch",
            key="login_labs",
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
            user_type = st.session_state["user"].get("userType", "regular")
            if user_type == "machine":
                st.sidebar.success(
                    f"""
                    🤖 Machine user: {st.session_state["user"]["name"]}
                    """
                )
            else:
                st.sidebar.success(
                    f"""
                    Logged in as {st.session_state["user"]["name"]}
                    """
                )

    if st.session_state.get("user"):
        # Only show logout for non-API key auth
        if not ZENO_API_KEY and st.button("Logout", key="logout_labs"):
            st.session_state.pop("user", None)
            st.session_state.pop("token", None)
            st.rerun()

# Main content
st.title("📊 Labs Monitoring")
st.write("Query data from the Labs Monitoring API endpoint.")

# Dataset options
DATASETS = {
    0: "Global all ecosystem disturbance alerts (DIST-ALERT)",
    1: "Global land cover",
    2: "Global natural/semi-natural grassland extent",
    3: "SBTN Natural Lands Map",
    4: "Tree cover loss",
    5: "Tree cover gain",
    6: "Forest greenhouse gas net flux",
    7: "Tree cover",
    8: "Tree cover loss by dominant driver",
    9: "Deforestation (sLUC) Emission Factors by Agricultural Crop",
}

# Input form
with st.form("monitoring_form"):
    st.subheader("Query Parameters")

    col1, col2 = st.columns(2)

    with col1:
        dataset_id = st.selectbox(
            "Dataset",
            options=list(DATASETS.keys()),
            format_func=lambda x: f"{x}: {DATASETS[x]}",
            index=0,  # Default to Global all ecosystem disturbance alerts (DIST-ALERT)
        )

        start_date = st.date_input(
            "Start Date",
            value=date.today() - timedelta(days=365),
        )

    with col2:
        area_ids_input = st.text_area(
            "Area IDs (one per line)",
            value="gadm:BRA",
            help="Format: source:src_id (e.g., gadm:BRA, kba:6072, wdpa:148322)",
        )

        end_date = st.date_input(
            "End Date",
            value=date.today(),
        )

    insights_query = st.text_input(
        "Insights Query (optional)",
        value="Analyse this data",
        help="Query for generating insights. Leave empty to skip insights generation.",
    )

    submitted = st.form_submit_button("Fetch Data", type="primary")

# Process form submission
if submitted:
    if not st.session_state.get("token"):
        st.error("Please login to use this feature.")
    else:
        # Parse area IDs
        area_ids = [
            aid.strip()
            for aid in area_ids_input.strip().split("\n")
            if aid.strip()
        ]

        if not area_ids:
            st.error("Please provide at least one area ID.")
        else:
            # Clear previous data
            if "labs_data" in st.session_state:
                del st.session_state["labs_data"]

            st.divider()

            # Create placeholders for streaming content
            status_placeholder = st.empty()
            metadata_placeholder = st.empty()
            aoi_placeholder = st.empty()
            dataset_placeholder = st.empty()
            analytics_placeholder = st.empty()
            insights_placeholder = st.empty()
            charts_placeholder = st.empty()
            codeact_placeholder = st.empty()
            followup_placeholder = st.empty()

            status_placeholder.info("🔄 Connecting to streaming endpoint...")

            stream_completed = False
            try:
                params = {
                    "dataset_id": dataset_id,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "area_ids": area_ids,
                }
                if insights_query:
                    params["insights_query"] = insights_query
                else:
                    params["insights_query"] = ""

                # Use streaming endpoint with httpx for better streaming support
                with httpx.stream(
                    "GET",
                    f"{API_BASE_URL}/api/labs/monitoring/stream",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {st.session_state['token']}"
                    },
                    timeout=300.0,  # 5 minute timeout for long-running requests
                ) as response:
                    if response.status_code != 200:
                        status_placeholder.error(
                            f"API Error ({response.status_code}): Failed to connect to stream"
                        )
                    else:
                        # Accumulate full response for session state
                        full_data = {}

                        # Process stream line by line using httpx iter_lines
                        for line in response.iter_lines():
                            print("--------------------------------")
                            print(f"LINE: {line}")
                            if not line:
                                continue

                            try:
                                event = json.loads(line)
                                event_type = event.get("type")
                                event_data = event.get("data")

                                if event_type == "metadata":
                                    status_placeholder.info(
                                        f"📊 [{datetime.now().strftime('%H:%M:%S')}] Received metadata, fetching analytics data..."
                                    )

                                    # Store metadata
                                    full_data.update(
                                        {
                                            "query": event_data.get("query"),
                                            "date_range": event_data.get(
                                                "date_range"
                                            ),
                                            "aoi_selection": event_data.get(
                                                "aoi_selection"
                                            ),
                                            "dataset": event_data.get(
                                                "dataset"
                                            ),
                                        }
                                    )

                                    # Render metadata sections immediately
                                    metadata_placeholder.empty()
                                    with metadata_placeholder.container():
                                        col1, col2 = st.columns(2)
                                        with col1:
                                            st.metric(
                                                "Query",
                                                event_data.get("query", "N/A"),
                                            )
                                        with col2:
                                            date_range = event_data.get(
                                                "date_range", {}
                                            )
                                            st.metric(
                                                "Date Range",
                                                f"{date_range.get('start_date', 'N/A')} to {date_range.get('end_date', 'N/A')}",
                                            )

                                    aoi_placeholder.empty()
                                    with aoi_placeholder.container():
                                        render_aoi_selection(
                                            event_data.get("aoi_selection", {})
                                        )

                                    dataset_placeholder.empty()
                                    with dataset_placeholder.container():
                                        render_dataset_info(
                                            event_data.get("dataset", {})
                                        )

                                elif event_type == "analytics_data":
                                    status_placeholder.info(
                                        f"💡 [{datetime.now().strftime('%H:%M:%S')}] Received analytics data, generating insights..."
                                    )

                                    # Store analytics data
                                    full_data["analytics_data"] = (
                                        event_data.get("analytics_data", [])
                                    )

                                    # Render analytics section immediately
                                    analytics_placeholder.empty()
                                    with analytics_placeholder.container():
                                        render_analytics_data(
                                            event_data.get(
                                                "analytics_data", []
                                            )
                                        )

                                elif event_type == "insights":
                                    status_placeholder.info(
                                        f"✨ [{datetime.now().strftime('%H:%M:%S')}] Received insights!"
                                    )

                                    # Store insights data
                                    full_data.update(
                                        {
                                            "insights": event_data.get(
                                                "insights", []
                                            ),
                                            "charts_data": event_data.get(
                                                "charts_data", []
                                            ),
                                            "codeact_parts": event_data.get(
                                                "codeact_parts", []
                                            ),
                                            "follow_up_suggestions": event_data.get(
                                                "follow_up_suggestions", []
                                            ),
                                            "insights_error": event_data.get(
                                                "insights_error"
                                            ),
                                        }
                                    )

                                    # Render insights sections immediately
                                    insights_placeholder.empty()
                                    with insights_placeholder.container():
                                        render_insights(
                                            event_data.get("insights", []),
                                            event_data.get("insights_error"),
                                        )

                                    charts_placeholder.empty()
                                    with charts_placeholder.container():
                                        render_charts(
                                            event_data.get("charts_data", [])
                                        )

                                    codeact_placeholder.empty()
                                    with codeact_placeholder.container():
                                        render_codeact_parts(
                                            event_data.get("codeact_parts", [])
                                        )

                                    followup_placeholder.empty()
                                    with followup_placeholder.container():
                                        render_follow_ups(
                                            event_data.get(
                                                "follow_up_suggestions", []
                                            )
                                        )

                                elif event_type == "error":
                                    status_placeholder.error(
                                        f"❌ Error: {event_data.get('message', 'Unknown error')}"
                                    )

                                elif event_type == "complete":
                                    status_placeholder.success(
                                        f"✅ [{datetime.now().strftime('%H:%M:%S')}] Data fetched successfully!"
                                    )
                                    # Store full data in session state
                                    st.session_state["labs_data"] = full_data
                                    stream_completed = True

                                    # Re-render all sections from full_data so analytics (and everything else)
                                    # is visible even when Streamlit hasn't flushed mid-loop. Without this,
                                    # the UI only updates when the script run ends, and the final state
                                    # is guaranteed to show all received data.
                                    metadata_placeholder.empty()
                                    with metadata_placeholder.container():
                                        col1, col2 = st.columns(2)
                                        with col1:
                                            st.metric(
                                                "Query",
                                                full_data.get("query", "N/A"),
                                            )
                                        with col2:
                                            dr = full_data.get(
                                                "date_range", {}
                                            )
                                            st.metric(
                                                "Date Range",
                                                f"{dr.get('start_date', 'N/A')} to {dr.get('end_date', 'N/A')}",
                                            )
                                    aoi_placeholder.empty()
                                    with aoi_placeholder.container():
                                        render_aoi_selection(
                                            full_data.get("aoi_selection", {})
                                        )
                                    dataset_placeholder.empty()
                                    with dataset_placeholder.container():
                                        render_dataset_info(
                                            full_data.get("dataset", {})
                                        )
                                    analytics_placeholder.empty()
                                    with analytics_placeholder.container():
                                        render_analytics_data(
                                            full_data.get("analytics_data", [])
                                        )
                                    insights_placeholder.empty()
                                    with insights_placeholder.container():
                                        render_insights(
                                            full_data.get("insights", []),
                                            full_data.get("insights_error"),
                                        )
                                    charts_placeholder.empty()
                                    with charts_placeholder.container():
                                        render_charts(
                                            full_data.get("charts_data", [])
                                        )
                                    codeact_placeholder.empty()
                                    with codeact_placeholder.container():
                                        render_codeact_parts(
                                            full_data.get("codeact_parts", [])
                                        )
                                    followup_placeholder.empty()
                                    with followup_placeholder.container():
                                        render_follow_ups(
                                            full_data.get(
                                                "follow_up_suggestions", []
                                            )
                                        )

                            except json.JSONDecodeError as e:
                                st.warning(f"Failed to parse stream line: {e}")

            except Exception as e:
                status_placeholder.error(f"Error fetching data: {str(e)}")

            # Rerun so the cached-results block runs: it renders from session state and
            # reliably shows analytics (and everything else). Placeholder updates during
            # the stream are not flushed until the script exits, so the final view was
            # inconsistent without this.
            if stream_completed:
                st.rerun()

# Display cached results if available (when not actively streaming)
if "labs_data" in st.session_state and not submitted:
    data = st.session_state["labs_data"]

    st.divider()

    # Query and Date Range Info
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Query", data.get("query", "N/A"))
    with col2:
        date_range = data.get("date_range", {})
        st.metric(
            "Date Range",
            f"{date_range.get('start_date', 'N/A')} to {date_range.get('end_date', 'N/A')}",
        )

    # Use helper functions for consistent rendering
    render_aoi_selection(data.get("aoi_selection", {}))
    render_dataset_info(data.get("dataset", {}))
    render_analytics_data(data.get("analytics_data", []))
    render_insights(data.get("insights", []), data.get("insights_error"))
    render_charts(data.get("charts_data", []))
    render_codeact_parts(data.get("codeact_parts", []))
    render_follow_ups(data.get("follow_up_suggestions", []))

    # Raw JSON Data (collapsible)
    with st.expander("🔍 View Raw JSON Response"):
        st.json(data)
