#!/bin/bash

# Default values for first query
QUERY="Find disturbance alerts over Lisbon, Portugal for the year 2023"
PERSONA="researcher"
THREAD_ID="alerts"
URL="http://localhost:8000"

# Default values for follow-up query
FOLLOWUP_QUERY="pull satellite imagery over the region for aug"
RUN_FOLLOWUP=true

# Display usage information if --help is provided
if [ "$1" = "--help" ]; then
  echo "Usage: ./test_kba.sh [query] [persona] [thread_id] [url] [followup_query] [run_followup]"
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

if [ ! -z "$5" ]; then
  FOLLOWUP_QUERY="$5"
fi

if [ ! -z "$6" ]; then
  RUN_FOLLOWUP=$6
fi

# Visual separator for first query
echo "=================================================================="
echo "==================== EXECUTING PRIMARY QUERY ===================="
echo "=================================================================="
echo "Running first query: $QUERY"
echo ""

# Run the first query
python client.py "$QUERY" -p "$PERSONA" -t "$THREAD_ID" -u "$URL"

# Run the follow-up query if enabled
if [ "$RUN_FOLLOWUP" = true ]; then
  # Visual separator for follow-up query
  echo -e "\n\n"
  echo "=================================================================="
  echo "=================== EXECUTING FOLLOW-UP QUERY ==================="
  echo "=================================================================="
  echo "Running follow-up query: $FOLLOWUP_QUERY"
  echo ""

  python client.py "$FOLLOWUP_QUERY" -p "$PERSONA" -t "$THREAD_ID" -u "$URL"

  # Final separator
  echo -e "\n"
  echo "=================================================================="
  echo "======================= EXECUTION COMPLETE ======================"
  echo "=================================================================="
fi
