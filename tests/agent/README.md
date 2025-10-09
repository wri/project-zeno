# Project Zeno E2E Testing Documentation

## Overview

The E2E testing framework evaluates the complete agent workflow by testing four core tools:
1. **AOI Selection** (`pick_aoi`) - Evaluates location selection accuracy
2. **Dataset Selection** (`pick_dataset`) - Evaluates dataset choice accuracy
3. **Data Pull** (`pull_data`) - Evaluates data retrieval success
4. **Final Answer** (`generate_insights`) - Evaluates answer quality using LLM-as-a-judge

## Test Dataset Structure

### Essential Columns (Required for Tests)

The following columns are **required** for the E2E tests to run properly:

#### Core Test Data
- **`query`** - The user query to test (string)
- **`test_group`** - Test grouping for filtering (e.g., "dataset", "rel-accuracy", "abs-accuracy" etc)
- **`status`** - Test execution status:
  - `"ready"` - Test is ready to run (default for new tests)
  - `"rerun"` - Test should be re-executed (e.g., after fixing issues)
  - `"skip"` - Test should be skipped/ignored during execution

#### AOI Selection Evaluation
- **`expected_aoi_id`** - Expected AOI identifier (e.g., "BRA", "USA.5_1", "IND.26_1")
- **`expected_subregion`** - Expected subregion filter when user explicitly requests sub-administrative units. Only used when query explicitly mentions comparing or analyzing sub-units within a larger area. Valid values:
  - `"country"` - Countries within a region
  - `"state"` - States/provinces within a country
  - `"district"` - Districts within a state/province
  - `"municipality"` - Municipalities within a district
  - `"locality"` - Localities within a municipality
  - `"neighbourhood"` - Neighborhoods within a locality
  - `"kba"` - Key Biodiversity Areas
  - `"wdpa"` - Protected areas (World Database on Protected Areas)
  - `"landmark"` - Geographic landmarks

  **Examples:**
  - Query: "Compare deforestation across states in Brazil" → `expected_subregion: "state"`
  - Query: "Show districts in Odisha with highest alerts" → `expected_subregion: "district"`
  - Query: "Deforestation in Brazil" (no sub-unit mentioned) → `expected_subregion: ""` (empty)

#### Dataset Selection Evaluation
- **`expected_dataset_id`** - Expected dataset ID (0-8 for current datasets)
- **`expected_context_layer`** - Expected context layer (varies by dataset)

#### Data Pull Evaluation
- **`expected_start_date`** - Expected start date (YYYY-MM-DD)
- **`expected_end_date`** - Expected end date (YYYY-MM-DD)

#### Answer Quality Evaluation
- **`expected_answer`** - Expected answer text for LLM-as-a-judge comparison

### Optional Columns (For Review/Analysis)

These columns are helpful for test management but not required for execution:

- **`expected_aoi_name`** - Human-readable AOI name (for review)
- **`expected_aoi_source`** - Expected AOI source (for review, not evaluated)
- **`expected_aoi_subtype`** - Expected AOI subtype (for review, not evaluated)
- **`expected_dataset_name`** - Human-readable dataset name (for review)
- **`priority`** - Test priority ("high", "medium", "low")

## Available Datasets

For the complete list of available datasets with their IDs, names, context layers, date ranges, and other details, refer to:

**`/src/tools/analytics_datasets.yml`**

This YAML file contains the authoritative dataset definitions including:
- `dataset_id` - Use for `expected_dataset_id` field
- `dataset_name` - Human-readable name
- `context_layers` - Available values for `expected_context_layer` field
- `start_date` / `end_date` - Valid date ranges for `expected_start_date` / `expected_end_date`
- `content_date` - Coverage period description
- `resolution`, `update_frequency`, and other metadata

**Key Points:**
- Dataset IDs currently range from 0-8
- Only Dataset ID 0 (DIST-ALERT) has context layers: `driver`, `natural_lands`, `grasslands`, `land_cover`
- Most datasets have no context layers (use empty string or null for `expected_context_layer`)
- Date ranges vary by dataset - check `start_date`/`end_date` fields in YAML

## Tool Evaluation Details

### 1. AOI Selection (`evaluate_aoi_selection`)

**Scoring System (Additive):**
- AOI ID match: 0.75 points
- Subregion match: 0.25 points
- **Total possible: 1.0**

**Key Features:**
- Handles GADM ID normalization (e.g., "USA.5_1" → "usa.5.1")
- Supports clarification detection via LLM-as-a-judge
- Empty expected_subregion treated as positive match

**Evaluated Fields:**
```python
{
    "aoi_score": 0.0-1.0,
    "actual_id": "selected_aoi_id",
    "actual_name": "selected_aoi_name",
    "actual_subtype": "selected_subtype",
    "actual_source": "selected_source",
    "actual_subregion": "selected_subregion",
    "match_aoi_id": True/False,
    "match_subregion": True/False
}
```

### 2. Dataset Selection (`evaluate_dataset_selection`)

**Scoring System (Additive):**
- Dataset ID match: 0.75 points
- Context layer match: 0.25 points
- **Total possible: 1.0**

**Key Features:**
- Supports clarification detection via LLM-as-a-judge
- Empty expected_context_layer treated as positive match
- String normalization for comparison

**Evaluated Fields:**
```python
{
    "dataset_score": 0.0-1.0,
    "actual_dataset_id": "selected_dataset_id",
    "actual_dataset_name": "selected_dataset_name",
    "actual_context_layer": "selected_context_layer"
}
```

### 3. Data Pull (`evaluate_data_pull`)

**Scoring System (Additive):**
- Data retrieval success: 0.75 points (row_count >= min_rows)
- Date range match: 0.25 points
- **Total possible: 1.0**

**Key Features:**
- Configurable minimum row threshold (default: 1)
- Date string normalization and comparison
- Empty expected dates treated as positive match
- Supports clarification detection

**Evaluated Fields:**
```python
{
    "pull_data_score": 0.0-1.0,
    "row_count": actual_row_count,
    "min_rows": minimum_expected_rows,
    "data_pull_success": True/False,
    "date_success": True/False,
    "actual_start_date": "actual_start_date",
    "actual_end_date": "actual_end_date"
}
```

### 4. Final Answer (`evaluate_final_answer`)

**Scoring System:**
- LLM-as-a-judge binary scoring: 0 or 1
- **Total possible: 1.0**

**Key Features:**
- Uses Haiku model for evaluation
- Compares expected vs actual answer semantically
- Extracts insights from charts_data or final messages
- Handles Gemini's list-based content structure

**Evaluated Fields:**
```python
{
    "answer_score": 0.0-1.0,
    "actual_answer": "generated_insight_text"
}
```

## Running E2E Tests

### Basic Usage

```bash
# Run single test (default)
python tests/agent/test_e2e.py

# Run specific number of tests
SAMPLE_SIZE=10 python tests/agent/test_e2e.py

# Run all tests
SAMPLE_SIZE=-1 python tests/agent/test_e2e.py

# Filter by test group
TEST_GROUP_FILTER=dataset python tests/agent/test_e2e.py
TEST_GROUP_FILTER=rel-accuracy SAMPLE_SIZE=5 python tests/agent/test_e2e.py
```

### Parallel Execution

```bash
# Run 10 tests with 5 parallel workers
NUM_WORKERS=5 SAMPLE_SIZE=10 python tests/agent/test_e2e.py

# Run all tests with 10 parallel workers
NUM_WORKERS=10 SAMPLE_SIZE=-1 python tests/agent/test_e2e.py
```

### API Mode Testing

```bash
# Test against API endpoint
TEST_MODE=api API_TOKEN=your_token python tests/agent/test_e2e.py

# API mode with parallel execution
TEST_MODE=api API_TOKEN=your_token NUM_WORKERS=5 SAMPLE_SIZE=20 python tests/agent/test_e2e.py
```

### Custom Configuration

```bash
# Custom test file
TEST_FILE=path/to/custom_dataset.csv python tests/agent/test_e2e.py

# Custom output filename
OUTPUT_FILENAME=my_test_run python tests/agent/test_e2e.py

# Custom API endpoint
TEST_MODE=api API_BASE_URL=https://api.example.com API_TOKEN=token python tests/agent/test_e2e.py
```

## Environment Variables

### Required for API Mode
- **`API_TOKEN`** - Bearer token for API authentication

### Optional Configuration
- **`TEST_MODE`** - "local" (default) or "api"
- **`API_BASE_URL`** - API endpoint (default: http://localhost:8000)
- **`SAMPLE_SIZE`** - Number of tests (default: 1, use -1 for all)
- **`TEST_FILE`** - CSV file path (default: experiments/e2e_test_dataset.csv)
- **`TEST_GROUP_FILTER`** - Filter by test_group column
- **`OUTPUT_FILENAME`** - Custom output filename prefix
- **`NUM_WORKERS`** - Parallel workers (default: 1)
- **`LANGFUSE_DATASET`** - Langfuse dataset name (enables Langfuse mode)

## Output Files

### CSV Mode
Tests generate two CSV files in `data/tests/`:

1. **`*_summary.csv`** - Query and scores only
2. **`*_detailed.csv`** - Expected vs actual values side-by-side

### Langfuse Mode
Results uploaded directly to Langfuse with detailed scoring:
- `overall_score` - Combined score across all criteria
- `aoi_selection_score` - AOI selection accuracy
- `dataset_selection_score` - Dataset selection accuracy
- `data_pull_score` - Data retrieval success
- `answer_quality_score` - Final answer evaluation

## Scoring Summary

**Overall Score Calculation:**
```
overall_score = (aoi_score + dataset_score + pull_data_score + answer_score) / 4
```

**Pass Threshold:** ≥ 0.7 (70%)

**Individual Tool Weights:**
- Each tool contributes equally (25%) to overall score
- Within each tool, sub-components have different weights as documented above

## Test Data Requirements Summary

### Minimum Required Columns for Functional Tests:
```
query, expected_aoi_id, expected_subregion, expected_dataset_id,
expected_context_layer, expected_start_date, expected_end_date,
expected_answer, test_group, status
```

### Optional for Review/Management:
```
expected_aoi_name, expected_aoi_source, expected_aoi_subtype,
expected_dataset_name, priority
```

## Gold Standard Test Set Guidelines

A gold standard test set should be a curated subset of 20-50 high-quality queries that:
- **Always run end-to-end without failure**
- **Never require agent clarification**
- **Have complete, unambiguous inputs** (AOI, dataset, date range, task)
- **Have objective, verifiable answers**

### Characteristics of Gold Standard Tests

#### 1. Complete Query Specification
Queries must be self-contained with all required information:

**✅ Good Examples:**
- `"Which 5 states in India had the most tree cover loss during 2020-2022?"`
- `"How much cropland area did Nigeria have in 2020 compared to Ghana?"`
- `"What was the total deforestation in Brazilian Amazon states from 2019-2021?"`

**❌ Avoid Ambiguous Queries:**
- `"Show me deforestation"` (missing location, timeframe)
- `"Compare forest loss"` (missing what to compare)
- `"Recent alerts in the region"` (vague location and timeframe)

#### 2. Objective, Measurable Answers
Answers should be specific facts, numbers, or rankings that can be verified:

**✅ Objective Answers:**
- `"Chhattisgarh (45.2 kha), Odisha (38.7 kha), Jharkhand (31.4 kha), Madhya Pradesh (28.9 kha), Maharashtra (24.1 kha)"`
- `"Nigeria: 34.2 million hectares, Ghana: 8.7 million hectares"`
- `"Pará: 2.1 Mha, Amazonas: 1.8 Mha, Rondônia: 0.9 Mha"`

**❌ Avoid Subjective Answers:**
- `"Some states had significant loss"`
- `"Forest conditions are concerning"`
- `"The situation has worsened"`

#### 3. Test Data Requirements

For gold standard tests, you only need these minimal fields:

```csv
query,expected_answer,test_group,status
```

**Optional fields** (if you want to validate individual tools):
```csv
expected_aoi_id,expected_subregion,expected_dataset_id,expected_context_layer,expected_start_date,expected_end_date
```

**Note:** For gold standard, set `test_group="gold"` and focus on final answer quality only. Individual tool validation is optional since the goal is end-to-end success without clarification.

### Gold Standard Query Templates

#### Ranking/Comparison Queries
```
"Which [N] [administrative_units] in [country] had the most [metric] from [start_year] to [end_year]?"

Examples:
- "Which 5 states in India had the most tree cover loss from 2020 to 2022?"
- "Which 3 provinces in Canada have the highest natural grassland area in 2020?"
- "Which districts in Odisha, India had the most disturbance alerts in 2024?"
```

#### Quantitative Comparison Queries
```
"How much [metric] did [location_A] have compared to [location_B] in [year/period]?"

Examples:
- "How much cropland did Brazil have compared to Argentina in 2020?"
- "What percentage of tree cover did Kalimantan Barat lose from 2001-2024?"
- "How many deforestation alerts occurred in protected areas of Peru vs Colombia in 2023?"
```

#### Trend Analysis Queries
```
"Did [metric] in [location] increase or decrease from [start_period] to [end_period]?"

Examples:
- "Did tree cover loss in Russia increase or decrease from 2020-2024?"
- "Has natural grassland area in Mongolia increased or decreased since 2010?"
- "Did disturbance alerts in the Amazon go up or down in 2024 compared to 2023?"
```

### Gold Standard Evaluation

For gold standard tests:
- **Primary Focus:** Final answer quality (LLM-as-a-judge)
- **Success Criteria:** Agent produces complete response without clarification requests
- **Scoring:** Binary pass/fail based on answer accuracy
- **Frequency:** Run before major releases and after significant changes

## Common Issues and Troubleshooting

1. **Empty Results:** Check that `status` column contains "ready" or "rerun"
2. **AOI Mismatches:** Verify GADM ID format (e.g., "USA.5_1" not "USA_5_1")
3. **Date Format Issues:** Use consistent date format ( YYYY-MM-DD)
4. **API Authentication:** Ensure `API_TOKEN` is set for API mode
5. **Parallel Execution:** Reduce `NUM_WORKERS` if hitting rate limits
