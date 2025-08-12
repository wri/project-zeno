#!/bin/bash

# Default settings
PERSONA="researcher"
THREAD_ID="all"
URL="http://localhost:8000"

# Define list names
LIST_NAMES=("odisha" "lisbon")

# Define query lists for different experiment scenarios
QUERIES_ODISHA=(
  "find threats to elephants in Odisha"
  "show time series stats of how deforestation has changed in this area"
  "suggest datasets I can use to understand deforestation in this region"
  "find disturbance alerts over this region for the year 2023"
)

QUERIES_LISBON=(
  "suggest datasets for wildfires in Lisbon, Portugal"
  "find disturbance alerts over this region for the year 2023"
  "pull satellite imagery over the region for august 2023"
)

# Default list to use
SELECTED_LIST="odisha"

# Display usage information if --help is provided
if [ "$1" = "--help" ]; then
  echo "Usage: ./test_all.sh [list_name] [persona] [thread_id] [url]"
  echo "  Available lists: ${LIST_NAMES[@]}"
  echo "  If no list is specified, the default '$SELECTED_LIST' list will be used."
  exit 0
fi

# Show available lists if --lists is provided
if [ "$1" = "--lists" ]; then
  echo "Available query lists:"
  for list in "${LIST_NAMES[@]}"; do
    echo "  $list"
  done
  exit 0
fi

# Override defaults if provided
if [ ! -z "$1" ] && [ "$1" != "--help" ] && [ "$1" != "--lists" ]; then
  # Check if the provided list name is valid
  VALID_LIST=false
  for list in "${LIST_NAMES[@]}"; do
    if [ "$1" = "$list" ]; then
      VALID_LIST=true
      SELECTED_LIST="$1"
      break
    fi
  done

  if [ "$VALID_LIST" = false ]; then
    echo "Error: List '$1' not found. Available lists: ${LIST_NAMES[@]}"
    exit 1
  fi
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

# Set the queries based on the selected list
case "$SELECTED_LIST" in
  "odisha")
    QUERIES=("${QUERIES_ODISHA[@]}")
    ;;
  "lisbon")
    QUERIES=("${QUERIES_LISBON[@]}")
    ;;
  *)
    echo "Error: Unknown list '$SELECTED_LIST'"
    exit 1
    ;;
esac

echo "=================================================================="
echo "================ RUNNING EXPERIMENT: $SELECTED_LIST ================"
echo "=================================================================="
echo "Total queries to execute: ${#QUERIES[@]}"
echo "Using persona: $PERSONA"
echo "Thread ID: $THREAD_ID"
echo "URL: $URL"
echo ""

# Execute each query in the selected list
for (( i=0; i<${#QUERIES[@]}; i++ )); do
  CURRENT_QUERY="${QUERIES[$i]}"

  # Visual separator for query
  echo -e "\n"
  echo "=================================================================="
  echo "=================== EXECUTING QUERY #$((i+1)) ===================="
  echo "=================================================================="
  echo "Running query: $CURRENT_QUERY"
  echo ""

  python client.py "$CURRENT_QUERY" -p "$PERSONA" -t "$THREAD_ID" -u "$URL"
done

# Final separator
echo -e "\n"
echo "=================================================================="
echo "======================= EXECUTION COMPLETE ======================="
echo "=================================================================="
