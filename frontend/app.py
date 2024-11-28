import json

import folium
import requests
import os

import streamlit as st
from streamlit_folium import st_folium
from dotenv import load_dotenv

_ = load_dotenv()

API_BASE_URL = os.environ["API_BASE_URL"]


st.set_page_config(page_icon="images/resource-racoon.jpg", layout="wide")
st.header("Resource Raccoon")
st.caption("Your intelligent EcoBot, saving the forest faster than a 🐼 eats bamboo")

# Sidebar content
with st.sidebar:
    st.image("images/resource-racoon.jpg")
    st.header("Meet Resource Raccoon!")
    st.write(
        """
    **Resource Raccoon** is your AI sidekick at WRI, trained on all your blog posts! It is a concious consumer and is consuming a local produce only. It can help you with questions about your blog posts. Give it a try!
    """
    )

    # st.subheader("Select a model:")
    # available_models = requests.get(f"{API_BASE_URL}/models").json()["models"]

    # model = st.selectbox(
    #     "Model", format_func=lambda x: x["model_name"], options=available_models
    # )

    st.subheader("🧐 Try asking:")
    st.write(
        """
    - Provide data about disturbance alerts in Aveiro summarized by landcover
    - What is happening with Gold Mining Deforestation?
    - What do you know about Forest Protection in remote islands in Indonesia?
    - How many users are using GFW and how long did it take to get there?
    - I am interested in understanding tree cover loss
    - I am interested in biodiversity conservation in Argentina
    - I would like to explore helping with forest loss in Amazon
    - Show datasets related to mangrooves
    - Find forest fires in milan for the year 2022
    - Show stats on forest fires over Ihorombe for 2021
    """
    )

# Note: the following section is commented to preseve the work that @DanielW has
# done to enable the streaming response of the chat messages.

# =========== BEGIN STREAMING RESPONSE ===============
if user_input := st.chat_input("Type your message here..."):
    st.chat_message("user").write(user_input)
    with requests.post(
        f"{API_BASE_URL}/stream",
        json=dict(query=user_input, model_id="gpt-4o-mini"),
        stream=True,
    ) as stream:
        for chunk in stream.iter_lines():
            data = json.loads(chunk.decode("utf-8"))
            st.write(data)
# =========== /END STREAMING RESPONSE ===============

# # Initialize session state for messages and selected dataset
# if "messages" not in st.session_state:
#     st.session_state["messages"] = []
# if "selected_dataset" not in st.session_state:
#     st.session_state["selected_dataset"] = None
# if "route" not in st.session_state:
#     st.session_state["route"] = None

# col1, col2 = st.columns([4, 6])


# def display_in_streamlit(base64_string):
#     image_html = f'<img src="data:image/png;base64,{base64_string}">'
#     st.markdown(image_html, unsafe_allow_html=True)


# # Left column (40% width) - Chat Interface
# with col1:
#     # User input and API call - only happens on new input
#     user_input = st.text_input("You:", key="user_input")
#     if user_input and user_input not in [
#         msg.get("user", "") for msg in st.session_state["messages"]
#     ]:
#         response = requests.post(
#             f"{API_BASE_URL}/query",
#             json={"query": user_input, "model_id": model["model_id"]},
#         )
#         data = response.json()
#         st.session_state["route"] = data["route"]
#         print(data)
#         # datasets = json.loads(data["messages"][0]["content"])

#         try:
#             st.session_state["messages"] = []
#             st.session_state["messages"].append({"user": user_input})
#             st.session_state["messages"].append({"bot": data})
#         except Exception as e:
#             st.error(f"Error processing response: {str(e)}")

#     # Display conversation and dataset buttons
#     for msg_idx, message in enumerate(st.session_state["messages"]):
#         if "user" in message:
#             st.write(f"**You**: {message['user']}")
#         else:
#             st.write("**Assistant**:")
#             data = message["bot"]
#             try:
#                 match st.session_state["route"]:
#                     case "layerfinder":
#                         datasets = json.loads(data["messages"][0]["content"])
#                         for idx, dataset in enumerate(datasets):
#                             st.write(f"**Dataset {idx+1}:** {dataset['explanation']}")
#                             st.write(f"**URL**: {dataset['uri']}")

#                             # Generate a unique key for each button that includes both message and dataset index
#                             button_key = f"dataset_{msg_idx}_{idx}"
#                             if st.button(f"Show Dataset {idx+1}", key=button_key):
#                                 st.session_state["selected_dataset"] = dataset[
#                                     "tilelayer"
#                                 ]
#                                 print(f"changed state to: {dataset['tilelayer']}")
#                     case "firealert":
#                         for msg in data["messages"]:
#                             if (
#                                 msg["name"] != "barchart-tool"
#                             ):  # Only print non-chart messages
#                                 st.write(msg["content"])
#                     case "docfinder":
#                         for msg in data["messages"]:
#                             st.write(msg["content"])
#                         # st.write(data["messages"][0]["content"])
#                     case _:
#                         st.write("Unable to find an agent for task")
#             except Exception as e:
#                 st.error(f"Error processing response: {str(e)}")

# # Right column (60% width) - Map Visualization
# with col2:
#     if st.session_state["route"] == "layerfinder":
#         st.header("Map Visualization")
#         m = folium.Map(location=[0, 0], zoom_start=2)

#         if st.session_state["selected_dataset"]:
#             print("yes")
#             folium.TileLayer(
#                 tiles=st.session_state["selected_dataset"],
#                 attr="Global Forest Watch",
#                 name="Selected Dataset",
#                 overlay=True,
#                 control=True,
#             ).add_to(m)

#         folium.LayerControl().add_to(m)
#         st_folium(m, width=700, height=500)
#     elif st.session_state["route"] == "firealert":
#         st.header("Fire Alert Statistics")
#         # Display barchart from the most recent message
#         if st.session_state["messages"]:
#             for message in reversed(st.session_state["messages"]):
#                 if "bot" in message:
#                     data = message["bot"]
#                     for msg in data["messages"]:
#                         if msg["name"] == "barchart-tool":
#                             display_in_streamlit(msg["content"])
#                             break
#                     break
#     else:
#         st.header("Visualization")
#         st.write("Select a dataset or query to view visualization")
