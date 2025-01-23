import json
import os
import uuid

import folium
import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import folium_static

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")


if "kba_session_id" not in st.session_state:
    st.session_state.kba_session_id = str(uuid.uuid4())
if "kba_messages" not in st.session_state:
    st.session_state.kba_messages = []


# Add a callback function to reset the session state
def reset_state():
    st.session_state.kba_session_id = str(uuid.uuid4())
    st.session_state.kba_messages = []
    st.session_state.custom_persona = ""


st.header("Keeper Kaola 🐨")
st.caption(
    "Zeno's Keeper Kaola, keeping a watch over the worlds Key Biodiversity Areas (KBAs)."
)

with st.sidebar:
    st.header("🐥")
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


def display_message(message):
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    else:
        if message["type"] == "kba_location":
            st.chat_message("assistant").write(
                "Found Key Biodiversity Areas in your area of interest..."
            )
            data = message["content"]
            artifact = data.get("artifact", {})
            artifact = json.loads(artifact)
            print(artifact)
            # plot the artifact which is a geojson featurecollection using folium
            geometry = artifact["features"][0]["geometry"]
            if geometry["type"] == "Polygon":
                pnt = geometry["coordinates"][0][0]
            else:
                pnt = geometry["coordinates"][0][0][0]
            m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=11)
            g = folium.GeoJson(artifact).add_to(m)  # noqa: F841
            folium_static(m, width=700, height=500)
        elif message["type"] == "report":
            st.chat_message("assistant").write(message["summary"])
            st.chat_message("assistant").write(message["metrics"])
            st.chat_message("assistant").write(message["regional_breakdown"])
            st.chat_message("assistant").write(message["actions"])
            st.chat_message("assistant").write(message["data_gaps"])
        elif message["type"] == "update":
            st.chat_message("assistant").write(message["content"])


def handle_stream_response(stream):
    for chunk in stream.iter_lines():
        data = json.loads(chunk.decode("utf-8"))

        if data.get("type") == "report":
            message = {
                "role": "assistant",
                "type": "report",
                "summary": data["summary"],
                "metrics": data["metrics"],
                "regional_breakdown": data["regional_breakdown"],
                "actions": data["actions"],
                "data_gaps": data["data_gaps"],
            }
        elif data.get("type") == "update":
            message = {
                "role": "assistant",
                "type": "update",
                "content": data["content"],
            }
        elif data.get("type") == "tool_call":
            message = {
                "role": "assistant",
                "type": "kba_location",
                "content": data,
            }
        st.session_state.kba_messages.append(message)
        display_message(message)


# Display chat history
if st.session_state.active_persona:
    for message in st.session_state.kba_messages:
        display_message(message)

    if user_input := st.chat_input("Type your message here..."):
        message = {"role": "user", "content": user_input, "type": "text"}
        st.session_state.kba_messages.append(message)
        display_message(message)

        with requests.post(
            f"{API_BASE_URL}/stream/kba",
            json={
                "query": user_input,
                "user_persona": st.session_state.active_persona,  # Include persona in the request
                "thread_id": st.session_state.kba_session_id,
            },
            stream=True,
        ) as stream:
            handle_stream_response(stream)
else:
    st.write("Please select or enter a user persona to start the chat.")
