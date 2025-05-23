import chainlit as cl
from langchain.schema import AIMessage
from langchain_core.messages import AIMessageChunk, HumanMessage
from src.agents import zeno

commands = [
    {"id": "OWL", "icon": "image", "description": "Search Datasets"},
    {"id": "Eagle", "icon": "globe", "description": "Find disturbance alerts around the world"},
    {"id": "Koala", "icon": "pen-line", "description": "Understand KBAs around the world",},
]

@cl.password_auth_callback
def auth_callback(username: str, password: str):
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    if (username, password) == ("admin", "admin"):
        return cl.User(
            identifier="admin", metadata={"role": "admin", "provider": "credentials"}
        )
    else:
        return None

@cl.on_message
async def main(message: cl.Message):
    config = {
        "configurable": {
            "thread_id": cl.context.session.id
            },
        "callbacks": [cl.LangchainCallbackHandler()]
        }
    
    for update in zeno.stream(
        {
            "messages": [HumanMessage(content=message.content)],
            "user_persona": "ecologist"
        }, 
        stream_mode="updates", 
        config=config
    ):
        node = next(iter(update.keys()))
        for msg in update[node]["messages"]:
            await cl.Message(content=msg.content).send()

@cl.on_chat_start
async def start():
    await cl.context.emitter.set_commands(commands)
    print("Chat started")

@cl.on_stop
async def on_stop():
    print("Chat stopped")

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="Wildfire alerts in Odemira",
            message="Find wildfire alerts over Odemira, Lisbon in 2023"
        ),
        cl.Starter(
            label="Threats to biodiversity in Brazil",
            message="Explain the threats to biodiversity in Brazil"
        ),
    ]