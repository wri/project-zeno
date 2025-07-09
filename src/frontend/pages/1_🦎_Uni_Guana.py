import json
import uuid
import requests
import streamlit as st
import folium
from streamlit_folium import folium_static
from app import API_BASE_URL, STREAMLIT_URL
from shapely.geometry import shape

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


def render_aoi_map(aoi_data, subregion_data=None):
    """
    Render AOI geojson data as a map using streamlit-folium.
    
    Args:
        aoi_data: Dictionary containing geojson data for AOI
        subregion_data: Optional dictionary containing geojson data for subregion
    """
    try:
        # Extract geojson from aoi_data
        if isinstance(aoi_data, dict) and 'geometry' in aoi_data:
            geojson_data = aoi_data['geometry']
        
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
        m = folium.Map(
            location=center,
            zoom_start=5,
            tiles="OpenStreetMap"
        )
        
        # Add AOI to map
        if geojson_data:
            folium.GeoJson(
                geojson_data,
                style_function=lambda feature: {
                    'fillColor': 'gray',
                    'color': 'gray',
                    'weight': 2,
                    'fillOpacity': 0.3,
                },
                popup=folium.Popup("Area of Interest", parse_html=True),
                tooltip="AOI"
            ).add_to(m)
        
        # Add subregions if provided
        if subregion_data and isinstance(subregion_data, list):
            try:
                for subregion in subregion_data:
                    if isinstance(subregion, dict) and 'geometry' in subregion:
                        subregion_geojson = subregion['geometry']
                        subregion_name = subregion.get('name', 'Subregion')
                        
                        folium.GeoJson(
                            subregion_geojson,
                            style_function=lambda feature: {
                                'fillColor': 'red',
                                'color': 'red',
                                'weight': 2,
                                'fillOpacity': 0.2,
                            },
                            popup=folium.Popup(subregion_name, parse_html=True),
                            tooltip=subregion_name
                        ).add_to(m)
            except Exception as e:
                st.warning(f"Could not render subregions: {str(e)}")
        
        # Display map in streamlit
        st.subheader("📍 Area of Interest")
        folium_static(m, width=700, height=400) # st_folium stalls the UI - use folium_static instead
        
    except Exception as e:
        st.error(f"Error rendering map: {str(e)}")
        st.json(aoi_data)  # Fallback to show raw data


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
        client = ZenoClient(
            base_url=API_BASE_URL, token=st.session_state.token
        )
        for stream in client.chat(
            user_input, thread_id=st.session_state.session_id
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
                subregion_data = update.get("subregion_aois") if update.get("subregion") is not None else None
                render_aoi_map(aoi_data, subregion_data)
            
            with st.expander("State Updates"):
                for key, value in update.items():
                    if key == "messages" or key == "aoi":
                        continue
                    st.badge(key)
                    st.code(value, language="json")
    st.session_state.messages.append({"role": "assistant", "content": content})
