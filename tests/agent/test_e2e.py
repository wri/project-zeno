"""
Simple end-to-end agent test runner with support for both local and API testing.

USAGE:
    # CSV-based testing
    python tests/agent/test_e2e.py
    TEST_MODE=api API_TOKEN=your_token python tests/agent/test_e2e.py
    SAMPLE_SIZE=5 python tests/agent/test_e2e.py

    # Filter by test group
    TEST_GROUP_FILTER=rel-accuracy python tests/agent/test_e2e.py
    TEST_GROUP_FILTER=dataset SAMPLE_SIZE=10 python tests/agent/test_e2e.py

    # Custom output filename (timestamp always appended)
    OUTPUT_FILENAME=my_test_run python tests/agent/test_e2e.py
    OUTPUT_FILENAME=alerts_test TEST_GROUP_FILTER=alerts python tests/agent/test_e2e.py

    # Parallel execution
    NUM_WORKERS=10 SAMPLE_SIZE=20 python tests/agent/test_e2e.py
    NUM_WORKERS=5 TEST_MODE=api API_TOKEN=your_token python tests/agent/test_e2e.py

    # Langfuse dataset integration
    LANGFUSE_DATASET="Your Dataset Name" python tests/agent/test_e2e.py
    LANGFUSE_DATASET="Your Dataset Name" TEST_MODE=api API_TOKEN=your_token python tests/agent/test_e2e.py

ENVIRONMENT VARIABLES:
    LANGFUSE_DATASET: Dataset name in Langfuse (enables Langfuse mode)
    TEST_MODE: "local" (default) or "api"
    API_BASE_URL: API endpoint URL (default: http://localhost:8000)
    API_TOKEN: Bearer token for API authentication (required for API mode)

    # CSV mode only:
    SAMPLE_SIZE: Number of test cases to run (default: 1, use -1 for all rows)
    TEST_FILE: Path to CSV test file (default: experiments/e2e_test_dataset.csv)
    TEST_GROUP_FILTER: Filter tests by test_group column (optional)
    OUTPUT_FILENAME: Custom filename for results (timestamp will be appended)
    NUM_WORKERS: Number of parallel workers (default: 1, set to 10 for parallel execution)

OUTPUT:
    # CSV mode: Creates two CSV files in data/tests/
    - *_summary.csv: Query and scores only
    - *_detailed.csv: Expected vs actual values side-by-side

    # Langfuse mode: Uploads results directly to Langfuse with detailed scoring
    - overall_score: Combined score across all evaluation criteria
    - aoi_selection_score: AOI selection accuracy
    - dataset_selection_score: Dataset selection accuracy
    - data_pull_score: Data retrieval success
    - answer_quality_score: Final answer evaluation
"""

import asyncio

# Import the modular implementation
from tests.agent.e2e import test_e2e

if __name__ == "__main__":
    asyncio.run(test_e2e())
