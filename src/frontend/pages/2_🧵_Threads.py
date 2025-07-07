import json

import requests
import streamlit as st
from app import API_BASE_URL

st.set_page_config(page_title="🧵 Threads", page_icon="🧵")

st.title("🧵 Your Threads")


# Helper to get auth token from session (if available)
def get_auth_headers():
    token = st.session_state.get("token")

    return {"Authorization": f"Bearer {token}"}


# Fetch threads
def fetch_threads():
    resp = requests.get(
        f"{API_BASE_URL}/api/threads", headers=get_auth_headers()
    )

    if resp.status_code == 200:
        return resp.json()

    st.error("Failed to fetch threads")
    return []


# Fetch a single thread
def fetch_thread(thread_id):
    with requests.get(
        f"{API_BASE_URL}/api/threads/{thread_id}",
        headers=get_auth_headers(),
        stream=True,
    ) as stream:
        st.subheader(f"Thread {selected_id}")

        for chunk in stream.iter_lines():
            if chunk:
                data = json.loads(chunk.decode("utf-8"))
                st.write(data)


threads = []
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
            # st.write("User info: ", st.session_state["user"])
            if st.button("Logout"):
                # NOTE: there is a logout endpoint in the API, but it only invalidates the browser cookies
                # and not the JWT. So in this case, we'll just clear the user info and token
                st.session_state.pop("user", None)
                st.session_state.pop("token", None)
                st.rerun()


threads = fetch_threads()

if not threads:
    st.info("No threads found.")
else:
    thread_options = {f"{t['id']}": t for t in threads}
    selected_id = st.radio(
        "Select a thread to view:",
        list(thread_options.keys()),
        format_func=lambda tid: f"Thread {tid}",
    )

    if selected_id:
        thread = fetch_thread(selected_id)
