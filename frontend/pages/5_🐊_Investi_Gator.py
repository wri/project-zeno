import json
import os
import uuid

import folium

import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

from streamlit_folium import st_folium

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")
LOCAL_API_BASE_URL = os.environ.get("LOCAL_API_BASE_URL")


if "gfw_session_id" not in st.session_state:
    st.session_state.gfw_session_id = str(uuid.uuid4())
if "waiting_for_input" not in st.session_state:
    st.session_state.waiting_for_input = False
if "gfw_messages" not in st.session_state:
    st.session_state.gfw_messages = []


# Add a callback function to reset the session state
def reset_state():
    st.session_state.gfw_session_id = str(uuid.uuid4())
    st.session_state.waiting_for_input = False
    st.session_state.gfw_messages = []


st.header("Investi Gator 🐊")
st.caption(
    "Zeno's Investi Gator is a curious agent hungry for data. It specializes in retrieving data from the Global Forest Watch API."
)

# Sidebar content
with st.sidebar:
    st.header("🐊")
    st.write(
        """
    "Zeno's Investi Gator is a curious agent hungry for data. It specializes in retrieving data from the Global Forest Watch API."
    """
    )

    st.subheader("🧐 Try asking:")
    st.write(
        """
    - What is current state of Cameroon's tree cover?
    - Which country has the most deforestation in the past 5 years?
    - Which state in Brazil has sequestered the most carbon? 
    """
    )

    if not st.session_state.get("token"):
        st.button(
            "Login with Global Forest Watch",
            on_click=lambda: st.markdown(
                '<meta http-equiv="refresh" content="0;url=https://api.resourcewatch.org/auth?callbackUrl=http://localhost:8501&token=true">',
                unsafe_allow_html=True,
            ),
        )
    else:

        user_info = requests.get(
            f"{LOCAL_API_BASE_URL}auth/me",
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


def display_message(message):
    """Helper function to display a single message"""
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    elif message["role"] == "assistant":
        if message["type"] == "location":

            st.chat_message("assistant").write("Found location you searched for...")
            data = message["content"]
            artifact = data.get("artifact", {})
            m = folium.Map(zoom_start=4)

            for _artifact in artifact:

                # artifact = artifact[0]

                # artifact is a single feature
                st.chat_message("assistant").write(_artifact["properties"])

                # geometry = _artifact["geometry"]

                folium.GeoJson(_artifact).add_to(m)  # noqa: F841

            st_folium(m, width=700, height=500, returned_objects=[])

        elif message["type"] == "query":
            # sql_query = json.loads(message["content"]["content"])["sql_query"]

            # st.chat_message("assistant").write(f"Results for query: {sql_query} ")
            # Query + explanation
            st.chat_message("assistant").write(
                "Here is the query that I've come up with, with an explanation: "
            )
            st.chat_message("assistant").write(message["content"]["content"])

            st.chat_message("assistant").write(
                "Here are the results of this query executed against the GFW Data API: "
            )
            data = message["content"]["artifact"]["result"]
            df = pd.DataFrame(data)
            st.table(data=df)
        # elif message["type"] == "alerts":
        #     st.chat_message("assistant").write(
        #         "Computing distributed alerts statistics..."
        #     )
        #     # plot the stats
        #     data = message["content"]
        #     stats = data.get("content", {})
        #     stats = json.loads(stats)
        #     print(stats)
        #     df = pd.DataFrame(list(stats.items()), columns=["Category", "Value"])
        #     st.bar_chart(df, x="Category", y="Value")

        #     # plot the artifact which is a geojson featurecollection
        #     artifact = data.get("artifact", {})
        #     if artifact:
        #         first_feature = artifact["features"][0]
        #         geometry = first_feature["geometry"]
        #         if geometry["type"] == "Polygon":
        #             pnt = geometry["coordinates"][0][0]
        #         else:
        #             pnt = geometry["coordinates"][0][0][0]

        #         m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=11)

        #         minx, miny, maxx, maxy = gpd.GeoDataFrame.from_features(
        #             artifact
        #         ).total_bounds

        #         print("BOUNDS: ", minx, miny, maxx, maxy)

        #         m.fit_bounds([[miny, minx], [maxy, maxx]])

        #         g = folium.GeoJson(artifact).add_to(m)  # noqa: F841
        #         st_folium(m, width=700, height=500, returned_objects=[])
        # elif message["type"] == "context":
        #     data = message["content"]
        #     st.chat_message("assistant").write(
        #         f"Adding context layer {data['content']}"
        #     )
        #     m = folium.Map(location=[0, 0], zoom_start=3)
        #     g = folium.TileLayer(
        #         data["artifact"]["tms_url"],
        #         name=data["content"],
        #         attr=data["content"],
        #     ).add_to(
        #         m
        #     )  # noqa: F841
        #     st_folium(m, width=700, height=500, returned_objects=[])

        # elif message["type"] == "stac":
        #     st.chat_message("assistant").write(
        #         "Found satellite images for your area of interest, here are the stac ids: "
        #     )
        #     data = message["content"]
        #     artifact = data.get("artifact", {})
        #     # create a grid of 2 x 5 images
        #     cols = st.columns(5)
        #     for idx, stac_item in enumerate(artifact["features"]):
        #         stac_id = stac_item["id"]
        #         stac_href = next(
        #             (
        #                 link["href"]
        #                 for link in stac_item["links"]
        #                 if link["rel"] == "thumbnail"
        #             ),
        #             None,
        #         )
        #         with cols[idx % 5]:
        #             st.chat_message("assistant").image(
        #                 stac_href, caption=stac_id, width=100
        #             )
        else:
            st.chat_message("assistant").write(message["content"])


def handle_stream_response(stream):
    for chunk in stream.iter_lines():
        data = json.loads(chunk.decode("utf-8"))

        # st.write(data)

        # Regular update messages from Zeno
        if data.get("type") == "update":
            message = {
                "role": "assistant",
                "type": "text",
                "content": data["content"],
            }
            st.session_state.gfw_messages.append(message)
            display_message(message)
        # Tool calls from Zeno
        elif data.get("type") == "tool_call":
            message = None
            if data.get("tool_name") == "location-tool":
                message = {
                    "role": "assistant",
                    "type": "location",
                    "content": data,
                }
            elif data.get("tool_name") == "relative-location-tool":
                message = {
                    "role": "assistant",
                    "type": "location",
                    "content": data,
                }
            elif data.get("tool_name") == "query-tool":
                message = {
                    "role": "assistant",
                    "type": "query",
                    "content": data,
                }
            # elif data.get("tool_name") == "dist-alerts-tool":
            #     message = {
            #         "role": "assistant",
            #         "type": "alerts",
            #         "content": data,
            #     }
            # elif data.get("tool_name") == "context-layer-tool":
            #     message = {
            #         "role": "assistant",
            #         "type": "context",
            #         "content": data,
            #     }
            # elif data.get("tool_name") == "stac-tool":
            #     message = {
            #         "role": "assistant",
            #         "type": "stac",
            #         "content": data,
            #     }
            else:
                message = {
                    "role": "assistant",
                    "type": "text",
                    "content": data["content"],
                }

            if message:
                message["avatar"] = "✅"
                st.session_state.gfw_messages.append(message)
                display_message(message)
        # Interrupted by human input
        elif data.get("type") == "interrupted":
            payload = json.loads(data.get("payload"))
            # Store the state that we're waiting for input
            st.session_state.waiting_for_input = True
            # Add the interrupt message to the chat
            message = {
                "role": "assistant",
                "type": "text",
                "content": f"Pick one of the options: {[ (row[0], row[1]) for row in payload]}",
            }
            st.session_state.gfw_messages.append(message)
            display_message(message)
            st.rerun()
        else:
            raise ValueError(f"Unknown message type: {data.get('type')}")


# Display chat history
for message in st.session_state.gfw_messages:
    display_message(message)

# Main chat input
if user_input := st.chat_input("Type your message here..."):
    # Add user message to history
    message = {"role": "user", "type": "text", "content": user_input}
    st.session_state.gfw_messages.append(message)
    display_message(message)

    # If we were waiting for input, this is a response to an interrupt
    query_type = "human_input" if st.session_state.waiting_for_input else "query"

    # Reset the waiting_for_input state
    if st.session_state.waiting_for_input:
        st.session_state.waiting_for_input = False

    with requests.post(
        f"{LOCAL_API_BASE_URL}/stream/gfw_data_api",
        json={
            "query": user_input,
            "thread_id": st.session_state.gfw_session_id,
            "query_type": query_type,
        },
        headers={"Authorization": f"Bearer {st.session_state.token}"},
        stream=True,
    ) as stream:
        import logging

        logging.error(f"STREAM: {stream.content}")
        handle_stream_response(stream)
