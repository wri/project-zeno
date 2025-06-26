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

- **GADM Location** (`eval_gadm.py`) - Exact match on location IDs
- **Investigator** (`eval_investi_gator.py`) - LLM-evaluated complex questions

## Adding Test Data

CSV format with examples (see `upload_dataset.py` for details).

Built-in parsers:
- `parse_gadm_location` - For location datasets
- `parse_tree_cover_qa` - For Q&A datasets

Template for custom parsers available in `upload_dataset.py`.

## Running on Different Environments

- **Local**: `LANGFUSE_HOST=http://localhost:3000`
- **Staging**: Update host URL to staging instance

## Understanding Results

- View scores in LangFuse UI
- Inspect traces for debugging failed evaluations
