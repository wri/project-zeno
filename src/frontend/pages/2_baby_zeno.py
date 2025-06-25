import streamlit as st
import json
import uuid
from client import ZenoClient

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("Baby Zeno")

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("What is up?"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)

    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        client = ZenoClient()
        for stream in client.chat(prompt, thread_id=st.session_state.session_id):
            node = stream['node']
            update = json.loads(stream['update'])
            for msg in update['messages']:
                content = msg['kwargs']['content']
                
                if isinstance(content, list):
                    for msg in content:
                        full_response += str(msg) + "\n"
                else:
                    full_response += str(content)
            message_placeholder.markdown(full_response + "▌")
        message_placeholder.markdown(full_response)
    st.session_state.messages.append({"role": "assistant", "content": full_response})
