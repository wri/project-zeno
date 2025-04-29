import streamlit as st
import os
import requests


LOCAL_API_BASE_URL = os.environ["LOCAL_API_BASE_URL"]


st.set_page_config(page_title="Zeno", page_icon="🦣")


# Handle navigation based on URL path
token = st.query_params.get("token")

if token:
    st.session_state["token"] = token
    st.query_params.clear()


# Custom CSS for cards
st.markdown(
    """
    <style>
    .agent-card {
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #ddd;
        margin-bottom: 20px;
        background-color: white;
    }
    .agent-name {
        color: #1E88E5;
        font-size: 24px;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .agent-tagline {
        color: #424242;
        font-size: 18px;
        font-style: italic;
        margin-bottom: 15px;
    }
    .agent-description {
        color: #616161;
        font-size: 16px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

st.title("Zeno 🦣")

st.write(
    "Zeno the mammoth is at your service: Ready to find, fetch & filter your data needs."
)


with st.sidebar:

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


# Agent data
agents = [
    {
        "name": "Owl Gorithm 🦉",
        "tagline": "A wise, data-savvy agent for WRI content such as blog posts and datasets.",
        "description": "Expert at finding relevant content datasets hosted by WRI & LCL. It tries its best to find the dataset & explain why it is relevant to your query.",
    },
    {
        "name": "Earthy Eagle 🦅",
        "tagline": "An eagle-eyed agent focused on detecting disturbances or deforestation alerts.",
        "description": "Specializes in detecting disturbances or deforestation alerts. It assists in finding alerts for specific locations and timeframes. Additionally, it helps in understanding the distribution of alerts within a location and provides satellite images for validation.",
    },
    {
        "name": "Keeper Koala 🐨",
        "tagline": "Keeping a watch over the worlds Key Biodiversity Areas (KBAs).",
        "description": "Specializing in planning interventions and answering queries about KBAs - from habitat analysis to species protection strategies. Keeper Koala helps ensure critical ecosystems get the attention they need.",
    },
    {
        "name": "Investi Gator 🐊",
        "tagline": "Keeping a watch over the worlds Key Biodiversity Areas (KBAs).",
        "description": "Specializing in planning interventions and answering queries about KBAs - from habitat analysis to species protection strategies. Keeper Koala helps ensure critical ecosystems get the attention they need.",
    },
]


# Display agent cards in rows
for agent in agents:
    st.markdown(
        f"""
        <div class="agent-card">
            <div class="agent-name">{agent['name']}</div>
            <div class="agent-tagline">{agent['tagline']}</div>
            <div class="agent-description">{agent['description']}</div>
        </div>
    """,
        unsafe_allow_html=True,
    )
