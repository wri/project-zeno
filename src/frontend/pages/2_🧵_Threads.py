import requests
import streamlit as st
from app import API_BASE_URL

from client import ZenoClient
from utils import display_sidebar_selections, render_stream

st.set_page_config(page_title="🧵 Threads", page_icon="🧵")

st.title("🧵 Your Threads")


# Fetch threads
def fetch_threads():
    if not st.session_state.get("token"):
        return []
    client = ZenoClient(base_url=API_BASE_URL, token=st.session_state.token)
    return client.list_threads()


@st.dialog("Delete Thread")
def delete_dialog(thread_id):
    client = ZenoClient(base_url=API_BASE_URL, token=st.session_state.token)

    st.text(
        ":warning: Are you sure you want to delete this thread? This action cannot be undone"
    )
    _, col1, col2 = st.columns([0.5, 0.25, 0.25])
    with col1:
        if st.button("Cancel", key=f"cancel_delete_{thread_id}"):
            st.rerun()
    with col2:
        if st.button(
            ":wastebasket: Delete!", key=f"confirm_delete_{thread_id}"
        ):
            try:
                client.delete_thread(thread_id)
                st.session_state["thread_delete_successful"] = True
                st.rerun()
            except Exception as e:
                st.session_state["thread_delete_error"] = e
                st.rerun()


@st.dialog("Update Thread Name")
def update_thread_name_dialog(thread_id):
    client = ZenoClient(base_url=API_BASE_URL, token=st.session_state.token)

    new_name = st.text_input(
        label="New Thread Name",
        label_visibility="collapsed",
        value=thread_options[thread_id]["name"],
        key=f"name-{thread_id}",
    )
    _, col1, col2 = st.columns([0.55, 0.2, 0.25])
    with col1:
        if st.button("Cancel", key=f"cancel_update_{thread_id}"):
            st.rerun()
    with col2:
        if st.button(":floppy_disk: Save!", key=f"confirm_update_{thread_id}"):
            try:
                client.update_thread(thread_id, new_name)
                st.session_state["thread_update_successful"] = True
                st.rerun()
            except Exception as e:
                st.session_state["thread_update_error"] = e
                st.rerun()


# Fetch a single thread
def fetch_thread(thread_id):
    client = ZenoClient(base_url=API_BASE_URL, token=st.session_state.token)

    col1, col2, col3 = st.columns([0.8, 0.1, 0.1])
    with col1:
        st.header(f"{thread_options[thread_id]['name']}")

    with col2:
        if st.button(":pencil2:", key=f"save-{thread_id}"):
            update_thread_name_dialog(thread_id)

    with col3:
        if col3.button(":wastebasket:", key=f"delete-{thread_id}"):
            delete_dialog(thread_id)

    for stream in client.fetch(thread_id):
        render_stream(stream)


threads = []
with st.sidebar:
    threads = fetch_threads()

    thread_options = {f"{t['id']}": t for t in threads}
    st.session_state["selected_id"] = st.radio(
        "Select a thread to view:",
        list(thread_options.keys()),
        format_func=lambda tid: thread_options[tid]["name"],
    )

    display_sidebar_selections()

    if not st.session_state.get("token"):
        st.button(
            "Login with Global Forest Watch",
            key="login_threads",
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
            if st.button("Logout", key="logout_threads"):
                # NOTE: there is a logout endpoint in the API, but it only invalidates the browser cookies
                # and not the JWT. So in this case, we'll just clear the user info and token
                st.session_state.pop("user", None)
                st.session_state.pop("token", None)
                st.rerun()


selected_aoi = st.session_state.get("aoi_selected")
selected_dataset = st.session_state.get("dataset_selected")
selected_daterange = st.session_state.get("daterange_selected")

# Extract aoi_data from selected AOI for use in chat processing
aoi_data = selected_aoi["aoi"] if selected_aoi else None

if not threads:
    st.info(
        "No threads found. Please log in and/or start a new thread to begin."
    )

if st.session_state.get("thread_delete_successful"):
    st.success("Thread deleted successfully!")
    st.session_state.pop("thread_delete_successful", None)

if st.session_state.get("thread_delete_error"):
    st.error(
        f"Error deleting thread: {st.session_state['thread_delete_error']}"
    )

if st.session_state.get("thread_update_successful"):
    st.success("Thread name updated successfully!")
    st.session_state.pop("thread_update_successful", None)

if st.session_state.get("thread_update_error"):
    st.error(
        f"Error updating thread name: {st.session_state['thread_update_error']}"
    )

if thread_id := st.session_state.get("selected_id"):
    thread = fetch_thread(thread_id)

    if user_input := st.chat_input(
        (
            "Please login to start a chat..."
            if not st.session_state.get("token")
            else "Type your message here..."
        ),
        disabled=not st.session_state.get("token"),
    ):
        ui_context = {}

        if selected_aoi and not st.session_state.get("aoi_acknowledged"):
            ui_context["aoi_selected"] = selected_aoi
            st.session_state["aoi_acknowledged"] = True
        if selected_dataset and not st.session_state.get(
            "dataset_acknowledged"
        ):
            ui_context["dataset_selected"] = selected_dataset
            st.session_state["dataset_acknowledged"] = True
        if selected_daterange and not st.session_state.get(
            "daterange_acknowledged"
        ):
            ui_context["daterange_selected"] = selected_daterange
            st.session_state["daterange_acknowledged"] = True

        st.session_state.messages.append(
            {"role": "user", "content": user_input}
        )
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            client = ZenoClient(
                base_url=API_BASE_URL, token=st.session_state.token
            )
            for stream in client.chat(
                query=user_input,
                user_persona="Researcher",
                ui_context=ui_context,
                thread_id=thread_id,
            ):
                render_stream(stream)
