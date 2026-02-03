import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Zeno", page_icon="🦣")

# API_BASE_URL = os.environ["API_BASE_URL"]
API_BASE_URL = os.environ["LOCAL_API_BASE_URL"]

STREAMLIT_URL = os.environ.get(
    "STREAMLIT_URL", "http://localhost:8501"
)  # URL where the Streamlit app is hosted

# Machine user API key for automatic authentication (optional)
ZENO_API_KEY = os.environ.get("ZENO_API_KEY")


# Handle navigation based on URL path
token = st.query_params.get("token")

if token:
    st.session_state["token"] = token
    st.query_params.clear()

# Auto-authenticate with machine user API key if available
if ZENO_API_KEY and not st.session_state.get("token"):
    st.session_state["token"] = ZENO_API_KEY

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
            key="login_button",
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
            user_type = st.session_state["user"].get("userType", "regular")
            if user_type == "machine":
                st.sidebar.success(
                    f"""
                    🤖 Machine user: {st.session_state["user"]["name"]}
                    """
                )
            else:
                st.sidebar.success(
                    f"""
                    Logged in as {st.session_state["user"]["name"]}
                    """
                )

    if st.session_state.get("user"):
        st.write("User info: ", st.session_state["user"])
        # Only show logout for non-API key auth
        if not ZENO_API_KEY and st.button("Logout", key="logout_button"):
            # NOTE: there is a logout endpoint in the API, but it only invalidates the browser cookies
            # and not the JWT. So in this case, we'll just clear the user info and token
            st.session_state.pop("user", None)
            st.session_state.pop("token", None)
            st.rerun()

# Agent data
agents = [
    {
        "name": "Uni Guana 🦎",
        "tagline": "A unified agent for all your data needs.",
        "description": "UniGuana brings together the best of all the tools you know and love. Find all the wisdom of Owl Gorithm, the keen eye of Earth Eagle, the sleuthing of Ivesitgator and the watchfulness of Keeper Koala, all in one place!",
    }
]

# Display agent cards in rows
for agent in agents:
    st.markdown(
        f"""
        <div class="agent-card">
            <div class="agent-name">{agent["name"]}</div>
            <div class="agent-tagline">{agent["tagline"]}</div>
            <div class="agent-description">{agent["description"]}</div>
        </div>
    """,
        unsafe_allow_html=True,
    )
