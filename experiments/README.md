# Zeno Agent Evaluation Framework

## What is this?

This is an evaluation framework for the Zeno agent that uses LangFuse to track and measure the agent's performance across different types of queries. It runs test datasets through the agent and scores the responses for accuracy.

## Quick Start

### Prerequisites

Set the following environment variables:
- `LANGFUSE_HOST` - Your LangFuse instance URL
- `LANGFUSE_SECRET_KEY` - LangFuse secret key
- `LANGFUSE_PUBLIC_KEY` - LangFuse public key

### Two-step process:

1. **Upload test data**
   ```bash
   python experiments/upload_dataset.py
   ```

2. **Run evaluation**
   ```bash
   LANGFUSE_HOST=http://localhost:3000 \
   LANGFUSE_SECRET_KEY=<SECRET_KEY> \
   LANGFUSE_PUBLIC_KEY=<PUBLIC_KEY> \
   python experiments/eval_gadm.py
   ```

View results in your LangFuse UI.

## Available Evaluations

- **GADM Location** (`eval_gadm.py`) - Tests if the agent correctly identifies geographic locations and returns the right GADM IDs. This is an exact-match test critical for any forest monitoring queries that need specific location data.

- **Investigator** (`eval_investi_gator.py`) - Tests complex analytical questions like "What's the deforestation rate in the Amazon?" Uses LLM evaluation to compare agent responses against expert-verified answers, since these answers can vary in phrasing but need to be factually correct.

## Adding Test Data

Start with an interactive session:

```
python -i experiments/upload_dataset.py
```

Then upload your test data:

```
# Create dataset in LangFuse
create_langfuse_dataset("my_dataset_name")

# For GADM location tests
gadm_config = ColumnConfig(input_column="text", parser=parse_gadm_location)
upload_csv("my_dataset_name", "path/to/gadm_test.csv", gadm_config)

# For investigator Q&A tests
qa_config = ColumnConfig(input_column="Question", parser=parse_tree_cover_qa)
upload_csv("my_dataset_name", "path/to/qa_test.csv", qa_config)
```

Built-in parsers:

 • `parse_gadm_location` - For location datasets
 • `parse_tree_cover_qa` - For Q&A datasets

See parser template in `upload_dataset.py` for creating custom parsers.

## Running on Different Environments

- **Local**: `LANGFUSE_HOST=http://localhost:3000` (for development/debugging)
- **Staging**: Update host URL to staging instance (recommended for accurate performance metrics, latency measurements, and cost tracking)

## Understanding Results

- **Scores**: View in LangFuse UI - 1.0 means perfect match, 0.0 means complete failure
- **Traces**: Each evaluation run creates a trace showing:
  - User query and agent response
  - All intermediate tool calls (location lookups, data queries)
  - JSON output that can be inspected for debugging
- **Failed evaluations**: Click on low-scoring traces to see the expected vs actual output in the score comments
