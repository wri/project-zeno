"""
E2E Test Results Viewer

A simple Streamlit app for viewing E2E test results from Project Zeno.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Page configuration
st.set_page_config(
    page_title="E2E Test Results Viewer",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_test_files():
    """Load available test result files from the data/tests directory."""
    test_dir = Path("data/tests")
    if not test_dir.exists():
        return []

    detailed_files = list(test_dir.glob("*_detailed.csv"))
    return sorted(
        detailed_files, key=lambda x: x.stat().st_mtime, reverse=True
    )


def get_score_color(score):
    """Get color based on score value."""
    if pd.isna(score):
        return "#gray"
    elif score >= 0.8:
        return "#2E8B57"  # Green
    elif score >= 0.6:
        return "#FFD700"  # Gold
    elif score >= 0.4:
        return "#FF8C00"  # Orange
    else:
        return "#DC143C"  # Red


def get_column_presets():
    """Define column presets for different evaluation areas."""
    return {
        "All Scores": [
            "query",
            "overall_score",
            "aoi_score",
            "dataset_score",
            "pull_data_score",
            "answer_score",
            "test_mode",
            "execution_time",
        ],
        "AOI Evaluation": [
            "query",
            "expected_aoi_id",
            "actual_id",
            "aoi_score",
            "expected_aoi_name",
            "actual_name",
            "expected_subregion",
            "actual_subregion",
            "match_subregion",
            "expected_aoi_subtype",
            "actual_subtype",
            "expected_aoi_source",
            "actual_source",
        ],
        "Dataset Evaluation": [
            "query",
            "expected_dataset_id",
            "actual_dataset_id",
            "dataset_score",
            "expected_dataset_name",
            "actual_dataset_name",
            "expected_context_layer",
            "actual_context_layer",
        ],
        "Data Pull Evaluation": [
            "query",
            "pull_data_score",
            "expected_start_date",
            "actual_start_date",
            "expected_end_date",
            "actual_end_date",
            "row_count",
            "data_pull_success",
            "date_success",
        ],
        "Answer Evaluation": [
            "query",
            "expected_answer",
            "actual_answer",
            "answer_score",
        ],
        "Error Analysis": [
            "query",
            "overall_score",
            "test_mode",
            "execution_time",
            "error",
        ],
        "Trace & Debug": [
            "query",
            "thread_id",
            "trace_id",
            "trace_url",
            "test_mode",
            "execution_time",
            "overall_score",
            "error",
        ],
        "Full Details": [
            "query",
            "trace_url",
            "overall_score",
            "execution_time",
            "test_mode",
            "expected_aoi_id",
            "actual_id",
            "aoi_score",
            "expected_dataset_id",
            "actual_dataset_id",
            "dataset_score",
            "pull_data_score",
            "expected_answer",
            "actual_answer",
            "answer_score",
        ],
    }


st.title("🧪 E2E Test Results Viewer")

# Sidebar for file selection and filters
st.sidebar.header("📁 File Selection")

# File upload option
uploaded_file = st.sidebar.file_uploader(
    "Upload CSV file", type=["csv"], help="Upload a test results CSV file"
)

# Or select from existing files
test_files = load_test_files()
if test_files:
    st.sidebar.markdown("**Or select from existing files:**")
    selected_file = st.sidebar.selectbox(
        "Available test files",
        options=[None] + test_files,
        format_func=lambda x: "Select a file..."
        if x is None
        else f"{x.name} ({datetime.fromtimestamp(x.stat().st_mtime).strftime('%Y-%m-%d %H:%M')})",
    )
else:
    selected_file = None
    st.sidebar.warning("No test files found in data/tests directory")

# Load data
df = None
if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    st.sidebar.success(f"Loaded uploaded file: {uploaded_file.name}")
elif selected_file is not None:
    df = pd.read_csv(selected_file)
    st.sidebar.success(f"Loaded: {selected_file.name}")

if df is None:
    st.info(
        "👆 Please upload a CSV file or select an existing test results file from the sidebar"
    )
    st.stop()

# Sidebar filters
st.sidebar.header("🔍 Filters")

# Score-based filters
score_columns = [
    "overall_score",
    "aoi_score",
    "dataset_score",
    "pull_data_score",
    "answer_score",
]
available_score_cols = [col for col in score_columns if col in df.columns]

if available_score_cols:
    min_score = st.sidebar.slider(
        "Minimum Overall Score",
        min_value=0.0,
        max_value=1.0,
        value=0.0,
        step=0.1,
    )
    df = df[df["overall_score"] >= min_score]

# Test mode filter
if "test_mode" in df.columns:
    test_modes = df["test_mode"].unique()
    selected_modes = st.sidebar.multiselect(
        "Test Modes", options=test_modes, default=test_modes
    )
    df = df[df["test_mode"].isin(selected_modes)]

# Test group filter
if "test_group" in df.columns:
    test_groups = df["test_group"].dropna().unique()
    if len(test_groups) > 0:
        selected_groups = st.sidebar.multiselect(
            "Test Groups", options=test_groups, default=test_groups
        )
        df = df[
            df["test_group"].isin(selected_groups) | df["test_group"].isna()
        ]

# Error filter
if "error" in df.columns:
    show_errors_only = st.sidebar.checkbox("Show only tests with errors")
    if show_errors_only:
        df = df[df["error"].notna()]

st.sidebar.markdown(f"**Filtered results: {len(df)} tests**")

# Results Table
st.header("Test Results")

# Column preset selection
presets = get_column_presets()
all_columns = df.columns.tolist()

col1, col2 = st.columns([1, 2])

with col1:
    selected_preset = st.selectbox(
        "Choose a preset",
        options=["Custom"] + list(presets.keys()),
        index=1,  # Default to "All Scores"
    )

with col2:
    if selected_preset == "Custom":
        default_columns = [
            "query",
            "overall_score",
            "aoi_score",
            "dataset_score",
            "pull_data_score",
            "answer_score",
            "test_mode",
            "execution_time",
        ]
        default_columns = [
            col for col in default_columns if col in all_columns
        ]
    else:
        default_columns = [
            col for col in presets[selected_preset] if col in all_columns
        ]

    selected_columns = st.multiselect(
        "Select columns to display",
        options=all_columns,
        default=default_columns,
        key="column_selector",
    )

if selected_columns:
    display_df = df[selected_columns].copy()

    # Apply color coding to score columns
    def highlight_scores(val):
        if pd.isna(val):
            return ""
        try:
            score = float(val)
            if 0 <= score <= 1:
                color = get_score_color(score)
                return f"background-color: {color}; color: white; font-weight: bold"
        except (ValueError, TypeError):
            pass
        return ""

    # Style the dataframe - using .map instead of deprecated .applymap
    styled_df = display_df.style.map(
        highlight_scores,
        subset=[col for col in selected_columns if "score" in col.lower()],
    )

    st.dataframe(styled_df, use_container_width=True, height=600)

    # Download filtered results
    csv = display_df.to_csv(index=False)
    st.download_button(
        label="📥 Download filtered results as CSV",
        data=csv,
        file_name=f"filtered_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
