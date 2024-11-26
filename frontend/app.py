import json

import streamlit as st

import requests
import os

API_BASE_URL = os.environ["API_BASE_URL"]

st.set_page_config(page_icon="images/resource-racoon.jpg")
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

    st.subheader("Select a model:")
    available_models = requests.get(f"{API_BASE_URL}/models").json()["models"]

    model = st.selectbox(
        "Model", format_func=lambda x: x["model_name"], options=available_models
    )

    st.subheader("🧐 Try asking:")
    st.write(
        """
    - What is happening with Gold Mining Deforestation?
    - What do you know about Forest Protection in remote islands in Indonesia?
    - How many users are using GFW and how long did it take to get there?
    - I am interested in biodiversity conservation in Argentina
    - I would like to explore helping with forest loss in Amazon
    - Show datasets related to mangrooves
    - Find forest fires in milan for the year 2022
    - Show stats on forest fires over Ihorombe for 2022
    """
    )

# Chat input
if user_input := st.chat_input("Type your message here..."):
    st.chat_message("user").write(user_input)
    with requests.post(
        f"{API_BASE_URL}/stream",
        json=dict(query=user_input, model_id=model["model_id"]),
        stream=True,
    ) as stream:
        for chunk in stream.iter_lines():
            data = json.loads(chunk.decode("utf-8"))
            st.write(data)
