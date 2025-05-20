# Project Zeno

Language Interface for Maps & WRI/LCL data APIs.

## Dependencies
- uv: https://docs.astral.sh/uv/getting-started/installation/
- ollama: https://ollama.com/
- docker: https://www.docker.com/products/docker-desktop/

## Getting Started

1. Clone the repository: `git clone git@github.com:wri/project-zeno.git'
2. Navigate into the project directory: `cd project-zeno`
3. Install dependencies: `uv sync`
4. Activate the virtual environment: `source .venv/bin/activate`
5. Create your environment file: `cp .env.example .env`. Then, open `.env` and update the placeholder values with your actual credentials and configurations.
6. Obtain the `data/` directory contents: This step requires fetching data from the team (e.g., from a shared drive or internal source) and placing it into the `data/` folder in your local project.

### Start the agent API

The following example shows how the streaming response can be obtained.

Run fastapi server

```bash
uv run uvicorn api:app --reload
```

Test the API

```python
import requests

msg = "How many users are using GFW and how long did it take to get there?"
response = requests.post("http://127.0.0.1:8000/stream", json=dict(query=msg), stream=True)
for line in response:
    if line:
        print(line.decode())
```

### Run Streamlit app

```bash
docker compose up -d
uv run streamlit run frontend/app.py
```


## Configure localhost Langfuse

1. `docker compose up langfuse-server` (or just spin up the whole backend with `docker-compuse up`)
2. create localhost Langfuse account via the UI http://localhost:3000
3. then create org and create a project
4. copy the API keys from the project
5. update Langfuse API keys (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY) in docker-compose.yml
