import json
import os
import uuid

import folium
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium
from typing import Dict, Any, Optional

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")


if "kba_session_id" not in st.session_state:
    st.session_state.kba_session_id = str(uuid.uuid4())
if "waiting_for_input" not in st.session_state:
    st.session_state.waiting_for_input = False
if "kba_messages" not in st.session_state:
    st.session_state.kba_messages = []


# Add a callback function to reset the session state
def reset_state():
    st.session_state.kba_session_id = str(uuid.uuid4())
    st.session_state.waiting_for_input = False
    st.session_state.kba_messages = []
    st.session_state.custom_persona = ""


st.header("Keeper Kaola 🐨")
st.caption(
    "Zeno's Keeper Kaola, keeping a watch over the worlds Key Biodiversity Areas (KBAs)."
)

with st.sidebar:
    st.header("🐨")
    st.write(
        """
    Keeper Kaola is an expert at planning interventions and answering queries about KBAs - from habitat analysis to species protection strategies.
    """
    )

    # Add user persona selection
    st.subheader("Select or Enter User Persona")
    user_personas = [
        "I am a conservation manager responsible for overseeing a network of Key Biodiversity Areas. I have basic GIS skills, I am comfortable visualising data but not conducting advanced analysis. I need to identify and understand threats, such as illegal logging or habitat degradation, and monitor changes in ecosystem health over time to allocate resources effectively and plan conservation interventions.",
        "I am a program manager implementing nature-based solutions projects focused on agroforestry and land restoration. I am comfortable using tools like QGIS for mapping and visualisation. I need to track project outcomes, such as tree cover gain and carbon sequestration, and prioritise areas for intervention based on risks like soil erosion or forest loss.",
        "I am an investment analyst for an impact fund supporting reforestation and agroforestry projects. I have limited GIS skills and rely on intuitive dashboards or visualisations to understand geospatial insights. I need independent geospatial insights to monitor portfolio performance, assess project risks, and ensure investments align with our net-zero commitments.",
        "I am a sustainability manager responsible for ensuring our company’s agricultural supply chains meet conversion-free commitments. I have limited GIS skills and can only use simple web-based tools or dashboards. I need to monitor and address risks such as land conversion to maintain compliance and support sustainable sourcing decisions.",
        "I am an advocacy program manager for an NGO working on Indigenous Peoples’ land rights. I have basic GIS skills, enabling me to visualise data but not perform advanced analysis. I need to use data to highlight land use changes, advocate for stronger tenure policies, and empower local communities to monitor their territories.",
        "I am a journalist covering environmental issues and corporate accountability, with basic GIS skills that enable me to interpret geospatial data by eye but not produce charts or insights myself. I need reliable, accessible data to track whether companies are meeting their EU Deforestation Regulation (EUDR) commitments, identify instances of non-compliance, and write compelling, data-driven stories that hold businesses accountable for their environmental impact.",
    ]

    selected_persona = st.selectbox(
        "Choose a persona", user_personas, on_change=reset_state
    )
    custom_persona = st.text_input("Or enter a custom persona", on_change=reset_state)

    # Determine active persona
    active_persona = custom_persona if custom_persona else selected_persona
    if st.session_state.get("active_persona") != active_persona:
        st.session_state.active_persona = active_persona
        reset_state()
        st.rerun()

    if st.session_state.get("active_persona"):
        st.success(f"**{st.session_state.active_persona}**", icon="🕵️‍♂️")

def render_text_insight(insight):
    st.header(insight["title"])
    st.write(insight["description"])
    st.write(insight["data"])
    st.markdown("---")

def render_table_insight(insight):
    st.header(insight["title"])
    st.write(insight["description"])
    df = pd.DataFrame(insight["data"])
    st.table(df)
    st.markdown("---")

def render_timeseries_plot(insight):
    """
    Render a single time series insight with clear formatting.

    Args:
        insight: A TimeSeriesInsight object
    """
    st.header(insight["title"])
    st.markdown(insight["description"])

    df = pd.DataFrame(insight["data"])
    df = df.sort_values('year')
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Latest Value",
            f"{df['value'].iloc[-1]:.2f}",
            f"{df['value'].iloc[-1] - df['value'].iloc[-2]:.2f}"
        )

    with col2:
        st.metric(
            "Average",
            f"{df['value'].mean():.2f}"
        )

    with col3:
        st.metric(
            "Total Change",
            f"{df['value'].iloc[-1] - df['value'].iloc[0]:.2f}"
        )

    # Plot the time series
    st.line_chart(
        df.set_index('year')['value'],
        use_container_width=True
    )

    # Show data table in expander
    with st.expander("View Data", expanded=False):
        st.dataframe(
            df.style.format({
                'value': '{:.2f}'
            })
        )

def render_chart_insight(insight):
    st.header(insight["title"])
    st.write(insight["description"])

    if True:
        df = pd.DataFrame({
            'Category': insight["data"]["categories"],
            'Value': insight["data"]["values"]
        })
        st.bar_chart(
            data=df.set_index('Category')['Value'],
            use_container_width=True
        )
    # elif insight["chart_type"] == "pie":
    #     df = pd.DataFrame({
    #         'Category': insight["data"]["categories"],
    #         'Value': insight["data"]["values"]
    #     })
    #     st.pie_chart(
    #         data=df.set_index('Category')['Value'],
    #         use_container_width=True
    #     )
    st.markdown("---")



def display_message(message):
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    else:
        if message["type"] == "tool_call":
            if message["name"] == "kba-data-tool":
                st.chat_message("assistant").write(message["content"])
                artifact = message.get("artifact", {})
                if artifact:
                    artifact = json.loads(artifact)
                    # plot the artifact which is a geojson featurecollection using folium
                    geometry = artifact["features"][0]["geometry"]
                    if geometry["type"] == "Polygon":
                        pnt = geometry["coordinates"][0][0]
                    else:
                        pnt = geometry["coordinates"][0][0][0]
                    m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=9)
                    g = folium.GeoJson(artifact).add_to(m)  # noqa: F841
                    st_folium(m, width=700, height=500)
            elif message["name"] == "location-tool":
                artifact = message.get("artifact", {})
                artifact = artifact[0]

                geometry = artifact["geometry"]
                if geometry["type"] == "Polygon":
                    pnt = geometry["coordinates"][0][0]
                else:
                    pnt = geometry["coordinates"][0][0][0]
                m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=9)
                g = folium.GeoJson(artifact).add_to(m)  # noqa: F841
                st_folium(m, width=700, height=500)
                st.chat_message("assistant").write("Pick one of the options: " + message["content"])
            elif message["name"] == "kba-insights-tool":
                insights = json.loads(message["insights"])["insights"]
                for insight in insights:
                    if insight["type"] == "text":
                        render_text_insight(insight)
                    elif insight["type"] == "table":
                        render_table_insight(insight)
                    elif insight["type"] == "chart":
                        render_chart_insight(insight)
            elif message["name"] == "kba-timeseries-tool":
                insights = json.loads(message["insights"])["insights"]
                for insight in insights:
                    render_timeseries_plot(insight)
            else:
                st.chat_message("assistant").markdown(message["content"])
        elif message["type"] == "update":
            st.chat_message("assistant").write(message["content"])


def handle_stream_response(stream):
    for chunk in stream.iter_lines():
        data = json.loads(chunk.decode("utf-8"))

        if data.get("type") == "update":
            message = {
                "role": "assistant",
                "type": "update",
                "content": data["content"],
            }
            st.session_state.kba_messages.append(message)
            display_message(message)
        elif data.get("type") == "tool_call":
            tool_name = data.get("tool_name")
            if tool_name == "kba-data-tool":
                message = {
                    "role": "assistant",
                    "type": "tool_call",
                    "name": tool_name,
                    "content": data["content"],
                    "artifact": data["artifact"],
                }
            elif tool_name == "location-tool":
                message = {
                    "role": "assistant",
                    "type": "tool_call",
                    "name": tool_name,
                    "content": data["content"],
                    "artifact": data["artifact"],
                }
            elif tool_name == "kba-insights-tool":
                message = {
                    "role": "assistant",
                    "type": "tool_call",
                    "name": tool_name,
                    "insights": data["content"],
                }
            elif tool_name == "kba-timeseries-tool":
                message = {
                    "role": "assistant",
                    "type": "tool_call",
                    "name": tool_name,
                    "insights": data["content"],
                }
            else:
                message = {
                    "role": "assistant",
                    "type": "tool_call",
                    "name": tool_name,
                    "content": data["content"],
                }
            st.session_state.kba_messages.append(message)
            display_message(message)
        elif data.get("type") == "interrupted":
            payload = json.loads(data.get("payload"))
            st.session_state.waiting_for_input = True
            message = {
                "role": "assistant",
                "type": "text",
                "content": f"Pick one of the options: {[row[0] for row in payload]}",
            }
            st.session_state.kba_messages.append(message)
            display_message(message)
            st.rerun()
        else:
            raise ValueError(f"Unknown message type: {data.get('type')}")


# Display chat history
if st.session_state.active_persona:
    for message in st.session_state.kba_messages:
        display_message(message)

    if user_input := st.chat_input("Type your message here..."):
        message = {"role": "user", "content": user_input, "type": "text"}
        st.session_state.kba_messages.append(message)
        display_message(message)

        query_type = "human_input" if st.session_state.waiting_for_input else "query"
        if st.session_state.waiting_for_input:
            st.session_state.waiting_for_input = False
        request = {
                "query": user_input,
                "user_persona": st.session_state.active_persona,  # Include persona in the request
                "thread_id": st.session_state.kba_session_id,
                "query_type": query_type,
        }
        with requests.post(
            f"{API_BASE_URL}/stream/kba",
            json=request,
            stream=True,
        ) as stream:
            handle_stream_response(stream)
else:
    st.write("Please select or enter a user persona to start the chat.")
