import argparse
import json
import uuid
from typing import Any, Dict, Iterator, Optional, List

import requests


class ZenoClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        token: Optional[str] = None,
    ):
        """
        Initialize the Zeno API client.

        Args:
            base_url: The base URL of the Zeno API server
            token: The bearer token for authentication
        """
        self.base_url = base_url
        self.token = token

    def list_threads(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/threads"
        if not self.token:
            raise ValueError("Token is required to list threads.")
        headers = {"Authorization": f"Bearer {self.token}"}
        with requests.get(url, headers=headers) as response:
            if response.status_code != 200:
                raise Exception(
                    f"Request failed with status code {response.status_code}: {response.text}"
                )
            try:
                threads = response.json()
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse JSON response: {e}")
            return threads

    def fetch(self, thread_id: str):
        if not self.token:
            raise ValueError("Token is required to fetch thread.")
        url = f"{self.base_url}/api/threads/{thread_id}"

        headers = {"Authorization": f"Bearer {self.token}"}

        payload = {"thread_id": thread_id}

        with requests.get(url, json=payload, stream=True, headers=headers) as response:
            if response.status_code != 200:
                raise Exception(
                    f"Request failed with status code {response.status_code}: {response.text}"
                )
            for update in response.iter_lines():
                if update:
                    # Decode the line and parse the JSON
                    decoded_update = update.decode("utf-8")
                    yield json.loads(decoded_update)

    def chat(
        self,
        query: str,
        user_persona: Optional[str] = None,
        ui_context: Optional[Dict] = None,
        ui_action_only: Optional[bool] = False,
        thread_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tags: Optional[list] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Send a chat request to the Zeno API and stream the responses.

        Args:
            query: The query to send
            user_persona: Optional user persona
            ui_context: Optional UI context
            thread_id: Optional thread ID
            metadata: Optional metadata
            session_id: Optional session ID
            user_id: Optional user ID
            tags: Optional tags
        Returns:
            An iterator of response messages
        """
        url = f"{self.base_url}/api/chat"

        payload = {
            "query": query,
            "ui_action_only": ui_action_only,
        }

        if ui_context:
            payload["ui_context"] = ui_context

        if user_persona:
            payload["user_persona"] = user_persona

        if thread_id:
            payload["thread_id"] = thread_id

        if metadata:
            payload["metadata"] = metadata

        if session_id:
            payload["session_id"] = session_id

        if user_id:
            payload["user_id"] = user_id

        if tags:
            payload["tags"] = tags

        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        with requests.post(url, json=payload, stream=True, headers=headers) as response:
            if response.status_code != 200:
                raise Exception(
                    f"Request failed with status code {response.status_code}: {response.text}"
                )
            for update in response.iter_lines():
                if update:
                    # Decode the line and parse the JSON
                    decoded_update = update.decode("utf-8")
                    yield json.loads(decoded_update)


def main():
    """
    Simple command-line interface to test the Zeno API.

    Usage:
        python client.py [query] [--persona PERSONA] [--thread-id THREAD_ID]
    """

    parser = argparse.ArgumentParser(description="Test the Zeno API")
    parser.add_argument("query", nargs="?", help="The query to send")
    parser.add_argument("--persona", "-p", help="User persona")
    parser.add_argument("--thread-id", "-t", help="Thread ID")
    parser.add_argument("--metadata", "-m", help="Metadata")
    parser.add_argument("--session-id", "-s", help="Session ID")
    parser.add_argument("--user-id", "-i", help="User ID")
    parser.add_argument("--tags", "-a", help="Tags")
    parser.add_argument(
        "--url", "-u", default="http://localhost:8000", help="API server URL"
    )
    parser.add_argument("--token", "-k", help="Bearer token for authentication")

    args = parser.parse_args()

    client = ZenoClient(base_url=args.url, token=args.token)

    query = args.query
    if args.thread_id and not query:
        if not client.token:
            raise ValueError("Thread ID provided but no token provided.")
        print(f"Fetching existing thread: {args.thread_id}")
        try:

            for stream in client.fetch(thread_id=args.thread_id):
                node = stream["node"]
                update = json.loads(stream["update"])

                for msg in update["messages"]:
                    content = msg["kwargs"]["content"]
                    print(f"Node: {node}")
                    if isinstance(content, list):
                        for msg in content:
                            print(f"Content: {msg}")
                    else:
                        print(f"Content: {content}")
                    print("---")
        except Exception as e:
            import traceback

            traceback.print_exc()
            print(f"Error fetching thread: {e}")

        return

    # If query wasn't provided as a positional argument, prompt for it
    if not query:
        query = input("Enter your query: ")

    print(f"Sending query: {query}")
    if args.persona:
        print(f"User persona: {args.persona}")
    if args.thread_id:
        print(f"Thread ID: {args.thread_id}")
    if args.metadata:
        metadata = json.loads(args.metadata)
    else:
        metadata = None
    if args.session_id:
        session_id = args.session_id
    else:
        session_id = uuid.uuid4().hex
    if args.user_id:
        user_id = args.user_id
    else:
        user_id = "zeno-default-user"
    if args.tags:
        tags = json.loads(args.tags)
    else:
        tags = ["zeno-default-tag"]
    print("Streaming response:")

    try:
        for stream in client.chat(
            query,
            user_persona=args.persona,
            thread_id=args.thread_id,
            metadata=metadata,
            session_id=session_id,
            user_id=user_id,
            tags=tags,
        ):
            node = stream["node"]
            update = json.loads(stream["update"])
            for msg in update["messages"]:
                content = msg["kwargs"]["content"]
                print(f"Node: {node}")
                if isinstance(content, list):
                    for msg in content:
                        print(f"Content: {msg}")
                else:
                    print(f"Content: {content}")
                print("---")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
