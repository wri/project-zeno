# Project Zeno

Language Interface for Maps & WRI/LCL data APIs.

## Dependencies
- uv: https://docs.astral.sh/uv/getting-started/installation/
- ollama: https://ollama.com/

## Getting Started

1. Clone the repository: `git clone git@github.com:wri/project-zeno.git'
2. Change into the project directory: `cd project-zeno`
3. Install dependencies: `uv sync`
4. Activate the environment: `source .venv/bin/activate`
5. Run `cp .env.example .env` and replace values appropriately in the .env file

## Fastapi testing

The following example shows how the streaming response can be obtained.

```python
import requests

msg = "How many users are using GFW and how long did it take to get there?"
response = requests.post("http://127.0.0.1:8000/stream", json=dict(query=msg), stream=True)
for line in response:
    if line:
        print(line.decode())
```