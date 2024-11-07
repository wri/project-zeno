# Self-host Langfuse

Run a self-hosted langfuse instance using this [self hosted guide](https://langfuse.com/docs/deployment/self-host).

## Dependencies
- Docker: https://www.docker.com/get-started/
- Python: https://www.python.org/downloads/

## Getting Started
- Run `cp .env.example .env` and replace values appropriately in the .env file
- Run `docker compose up -d` to get the langfuse instance running.
- Navigate to `http://localhost:3000`
- Click `Sign up` to create your account

## Dashboard
- Create a new project
- Go to settings and click `Create new API keys`
- Copy the Secret Key and Public Key 
- Store keys in the `.env` file in the root
    
```
LANGFUSE_SECRET_KEY="sk-your-key"
LANGFUSE_PUBLIC_KEY="pk-your-key"
LANGFUSE_HOST="http://localhost:3000"
```