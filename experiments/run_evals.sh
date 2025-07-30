#!/bin/bash
set -uo pipefail

# This command tells the script to CATCH the interrupt signal (SIGINT),
# run a null command ':', and then continue. This allows Ctrl-C to
# terminate the running 'uv run' command without stopping this script.
trap ':' INT

# This script runs the suite of evaluation scripts.
#
# It requires the following environment variables to be set before execution:
# - LANGFUSE_HOST
# - LANGFUSE_SECRET_KEY
# - LANGFUSE_PUBLIC_KEY
# - LANGFUSE_TRACING_ENVIRONMENT

# Check that required environment variables are set and not empty.
: "${LANGFUSE_HOST?Error: LANGFUSE_HOST is not set.}"
: "${LANGFUSE_SECRET_KEY?Error: LANGFUSE_SECRET_KEY is not set.}"
: "${LANGFUSE_PUBLIC_KEY?Error: LANGFUSE_PUBLIC_KEY is not set.}"
: "${LANGFUSE_TRACING_ENVIRONMENT?Error: LANGFUSE_TRACING_ENVIRONMENT is not set.}"

echo "--- Running Data Interpretation Evaluation ---"
uv run python experiments/eval_data_interpretation.py

echo
echo "--- Running Dataset Identification Evaluation (S2 T1-02 TCL) ---"
uv run python experiments/eval_dataset_identification.py "S2 T1-02 TCL"

echo
echo "--- Running Dataset Identification Evaluation (S2 T1-07 DIST & LDACS) ---"
uv run python experiments/eval_dataset_identification.py "S2 T1-07 DIST & LDACS"

echo
echo "--- Running GADM Evaluation ---"
uv run python experiments/eval_gadm.py

echo
echo "--- All evaluations completed successfully. ---"
