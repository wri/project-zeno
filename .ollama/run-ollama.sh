#!/usr/bin/env bash

# Start the Ollama server
ollama serve &

# Wait for the server to be ready
sleep 5

# Pull the required models
ollama pull nomic-embed-text
ollama pull llama3.2

# Keep the server running
#wollama serve
