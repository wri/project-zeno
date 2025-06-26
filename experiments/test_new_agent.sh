#!/bin/bash

# Default values for first query
QUERY="Find tree cover loss by forest fires in Odisha, India between 2020-2022."
PERSONA="researcher"
THREAD_ID="test-new-agent-2"
URL="http://localhost:8000"

# Display usage information if --help is provided
if [ "$1" = "--help" ]; then
  echo "Usage: ./test_new_agent.sh [query] [persona] [thread_id] [url]"
  echo "  If no arguments are provided, default values will be used."
  exit 0
fi

# Override defaults if provided
if [ ! -z "$1" ]; then
  QUERY="$1"
fi

if [ ! -z "$2" ]; then
  PERSONA="$2"
fi

if [ ! -z "$3" ]; then
  THREAD_ID="$3"
fi

if [ ! -z "$4" ]; then
  URL="$4"
fi

# Visual separator for first query
echo "=================================================================="
echo "==================== EXECUTING PRIMARY QUERY ===================="
echo "=================================================================="
echo "Running first query: $QUERY"
echo ""

# Run the first query
python client.py "$QUERY" -p "$PERSONA" -t "$THREAD_ID" -u "$URL"
