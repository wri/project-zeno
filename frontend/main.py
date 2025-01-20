import streamlit as st

st.set_page_config(page_title="Zeno", page_icon="🦣")

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

# Sidebar
st.sidebar.success(
    """
    Pick an agent for Zeno 🦣 to help you:
    1. Docu Dodo 🐥
    2. Owl Gorithm 🦉
    3. Earthy Eagle 🦅
    """
)

# Agent data
agents = [
    {
        "name": "Docu Dodo 🐥",
        "tagline": "A trusty agent that digs through documents to find the information you need.",
        "description": "Specializes in finding and analyzing WRI & LCL documents. Can search through various document types, extract key information, and provide relevant summaries.",
    },
    {
        "name": "Owl Gorithm 🦉",
        "tagline": "A wise, data-savvy agent for discovering relevant datasets.",
        "description": "Expert at finding relevant datasets hosted by WRI & LCL. It tries its best to find the dataset & explain why it is relevant to your query.",
    },
    {
        "name": "Earthy Eagle 🦅",
        "tagline": "An eagle-eyed agent focused on detecting distribution or deforestation alerts.",
        "description": "Specializes in detecting distribution alerts. It assists in finding alerts for specific locations and timeframes. Additionally, it helps in understanding the distribution of alerts within a location and provides satellite images for validation.",
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
