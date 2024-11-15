import json

import streamlit as st

import requests

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

    st.subheader("🧐 Try asking:")
    st.write(
        """
    - What is happening with Gold Mining Deforestation?
    - What do you know about Forest Protection in remote islands in Indonesia?
    - How many users are using GFW and how long did it take to get there?
    """
    )

# Chat input
if user_input := st.chat_input("Type your message here..."):
    st.chat_message("user").write(user_input)

    with requests.post("http://127.0.0.1:8000/stream", json=dict(query=user_input), stream=True, ) as stream:
        for chunk in stream.iter_lines():
            data = json.loads(chunk.decode("utf-8"))
            st.write(data)
