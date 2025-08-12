#!/bin/bash

# Default values for first query
QUERY="find threats to tigers in KBAs of Odisha - share insights on the matter"
PERSONA="researcher"
THREAD_ID="kba"
SESSION_ID="test-session"
USER_ID="srm"
TAGS='["kba-test", "2025-05-20"]'
METADATA='{"tools": "location-tool,kba-data-tool,kba-insights-tool",
           "location_tool_input": {"query": "Odisha"},
           "location_tool_output": "[\"Odisha\", \"State\", \"IND.26_1\", 1]"}'
URL="http://localhost:8000"

# Default values for follow-up query
FOLLOWUP_QUERY="show time series stats of how agriculture has changed in this area"
METADATA_FOLLOWUP='{"tools": "kba-timeseries-tool",
           "location_tool_input": {"query": "Odisha"},
           "location_tool_output": "[\"Odisha\", \"State\", \"IND.26_1\", 1]"}'
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
  METADATA="$4"
fi

if [ ! -z "$5" ]; then
  URL="$5"
fi

if [ ! -z "$6" ]; then
  FOLLOWUP_QUERY="$6"
fi

if [ ! -z "$7" ]; then
  RUN_FOLLOWUP=$7
fi

# Visual separator for first query
echo "=================================================================="
echo "==================== EXECUTING PRIMARY QUERY ===================="
echo "=================================================================="
echo "Running first query: $QUERY"
echo ""

# Run the first query
python client.py "$QUERY" -p "$PERSONA" -t "$THREAD_ID" -u "$URL" -m "$METADATA" -s "$SESSION_ID" -i "$USER_ID" -a "$TAGS"

# Run the follow-up query if enabled
if [ "$RUN_FOLLOWUP" = true ]; then
  # Visual separator for follow-up query
  echo -e "\n\n"
  echo "=================================================================="
  echo "=================== EXECUTING FOLLOW-UP QUERY ==================="
  echo "=================================================================="
  echo "Running follow-up query: $FOLLOWUP_QUERY"
  echo ""

  python client.py "$FOLLOWUP_QUERY" -p "$PERSONA" -t "$THREAD_ID" -u "$URL" -m "$METADATA_FOLLOWUP" -s "$SESSION_ID" -i "$USER_ID" -a "$TAGS"

  # Final separator
  echo -e "\n"
  echo "=================================================================="
  echo "======================= EXECUTION COMPLETE ======================"
  echo "=================================================================="
fi
