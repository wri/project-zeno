import json
import os

import folium
import requests
import streamlit as st
from streamlit_folium import folium_static

API_BASE_URL = os.environ.get("API_BASE_URL")


st.set_page_config(page_icon="images/zeno.jpg", layout="wide")
st.header("Zeno")
st.caption("Your intelligent EcoBot, saving the forest faster than a 🐼 eats bamboo")

# Sidebar content
with st.sidebar:
    st.image("images/zeno.jpg")
    st.header("Meet Zeno!")
    st.write(
        """
    **Zeno** is your AI sidekick, trained on all your blog posts! It is a concious consumer and is consuming a local produce only. It can help you with questions about your blog posts. Give it a try!
    """
    )

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


if user_input := st.chat_input("Type your message here..."):
    st.chat_message("user").write(user_input)
    with requests.post(
        f"{API_BASE_URL}/stream",
        json=dict(query=user_input, model_id="gpt-4o-mini"),
        stream=True,
    ) as stream:
        for chunk in stream.iter_lines():
            data = json.loads(chunk.decode("utf-8"))
            if data.get("artifact", {}).get("type") == "FeatureCollection":
                geom = data.get("artifact")["features"][0]["geometry"]
                if geom["type"] == "Polygon":
                    pnt = geom["coordinates"][0][0]
                else:
                    pnt = geom["coordinates"][0][0][0]

                m = folium.Map(location=[pnt[1], pnt[0]], zoom_start=11)
                g = folium.GeoJson(
                    data.get("artifact"),
                ).add_to(m)
                folium_static(m, width=700, height=500)
            else:
                st.write(data)
