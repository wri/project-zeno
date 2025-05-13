import requests
import json
import argparse
from typing import Dict, Optional, Iterator, Any


class ZenoClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize the Zeno API client.
        
        Args:
            base_url: The base URL of the Zeno API server
        """
        self.base_url = base_url
        
    def chat(
        self, 
        query: str, 
        user_persona: Optional[str] = None, 
        thread_id: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Send a chat request to the Zeno API and stream the responses.
        
        Args:
            query: The query to send
            user_persona: Optional user persona
            thread_id: Optional thread ID
            
        Returns:
            An iterator of response messages
        """
        url = f"{self.base_url}/api/chat"
        
        payload = {
            "query": query,
        }
        
        if user_persona:
            payload["user_persona"] = user_persona
            
        if thread_id:
            payload["thread_id"] = thread_id
        
        with requests.post(url, json=payload, stream=True) as response:
            if response.status_code != 200:
                raise Exception(f"Request failed with status code {response.status_code}: {response.text}")
            for update in response.iter_lines():
                if update:
                    # Decode the line and parse the JSON
                    decoded_update = update.decode('utf-8')
                    yield json.loads(decoded_update)


def main():
    """
    Simple command-line interface to test the Zeno API.
    
    Usage:
        python client.py [query] [--persona PERSONA] [--thread-id THREAD_ID]
    """
    
    parser = argparse.ArgumentParser(description='Test the Zeno API')
    parser.add_argument('query', nargs='?', help='The query to send')
    parser.add_argument('--persona', '-p', help='User persona')
    parser.add_argument('--thread-id', '-t', help='Thread ID')
    parser.add_argument('--url', '-u', default='http://localhost:8000', help='API server URL')
    
    args = parser.parse_args()
    
    # If query wasn't provided as a positional argument, prompt for it
    query = args.query
    if not query:
        query = input("Enter your query: ")
    
    client = ZenoClient(base_url=args.url)
    
    print(f"Sending query: {query}")
    if args.persona:
        print(f"User persona: {args.persona}")
    if args.thread_id:
        print(f"Thread ID: {args.thread_id}")
    print("Streaming response:")
    
    try:
        for update in client.chat(query, user_persona=args.persona, thread_id=args.thread_id):
            node = update['node']
            content = update['update']['kwargs']['content']
            
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