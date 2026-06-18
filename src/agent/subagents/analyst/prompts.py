"""Prompts for the analyst subagent behind `generate_insights`.

EXECUTOR_WORKFLOW is the step-by-step workflow the code executor follows to
turn pulled data into chart + insight JSON. WORDING_GUIDE is the neutral,
measurement-first language guide for user-facing text. Both are assembled
into the executor prompt by `build_analysis_prompt`.
"""

EXECUTOR_WORKFLOW = """### STEP-BY-STEP WORKFLOW (follow in order)

IMPORTANT: Write one code block for each step, so that you can use the actual data printed for the next steps.

**STEP 1: ANALYZE THE DATA**
- Load the relevant dataset(s) using pandas.
- Always use the pattern `df = pd.read_csv("input_file_{i}.csv")` to load the data, do not assign the file name to a variable first.
- If multiple files represent the same dataset with different parameters (shown in brackets in the file name, e.g. `[canopy_cover=50]`), treat each as a separate series and use the parameter value as the series label.
- Print which dataset(s) you are using (name, date range, and any filtering parameters)
- Explore the data structure, columns, and data types
- Calculate key statistics relevant to the user query
- Print your key findings clearly
- Do **NOT** create any plots or charts yet

**STEP 2: SUMMARIZE INSIGHTS**
- Summarize the data relevant to the user query
- Identify the most important patterns, trends, or comparisons
- Print a clear summary of what the data shows
- Include contextual layers or parameters used for analysis on the datasets

**STEP 3: GENERATE CHART DATA**
Now prepare the data for visualization in Recharts.js:

   a) **CHART TYPE SELECTION** - Choose the most appropriate chart type:
      - **line**: Time series data, trends over time (supports multi-series)
      - **bar**: Categorical comparisons, rankings (supports multi-series for grouped bars)
      - **stacked-bar**: Show composition within categories (use wide format with multiple metric columns)
      - **grouped-bar**: Compare multiple metrics side-by-side (use long format with group column)
      - **pie**: Part-to-whole relationships (limit to 6-8 categories max)
      - **area**: Cumulative trends, stacked time series (supports multi-series)
      - **scatter**: Show correlations between two variables
      - **table**: Detailed data when visualization isn't optimal

   b) **CREATE CHART DATA** following these requirements:
      1. **Structure**: Array of objects (rows) with simple field names as columns
      2. **Field names**: Use clear, lowercase names like 'date', 'value', 'category', 'year', 'count'
      3. **Numeric values**: Always numbers, never strings (e.g., 100 not "100")
      4. **Date ordering**: Chronological order for time series, not alphabetical
      5. **Grouping fields**: Group only by categorical, readable label columns such as names, dates, periods, classes, or metric labels. Do not group by numeric measure/value columns like 'value', 'count', 'area', 'sum', or continuous numeric readings unless the user explicitly asks for a distribution or histogram; aggregate those numeric columns instead.
      6. **Data format by chart type**:
         - **Single-series line/bar**: [{"date": "2020-01", "value": 100}]
           → One metric column, use y_axis="value" (REQUIRED — must not be empty)
         - **Multi-series line/bar/area**: [{"year": "2020", "metric1": 100, "metric2": 50}]
           → Multiple metric columns in WIDE format
           → Use series_fields=["metric1", "metric2"], leave y_axis="" (REQUIRED — series_fields must not be empty)
         - **Stacked-bar**: [{"category": "Region A", "forest": 100, "grassland": 50, "urban": 30}]
           → Use series_fields=["forest", "grassland", "urban"], leave y_axis="" (REQUIRED — series_fields must not be empty)
         - **Grouped-bar**: long format with group_field and y_axis="value" (REQUIRED — both must not be empty)
         - **Pie**: [{"name": "Category A", "value": 100}], max 6–8 slices
         - **IMPORTANT**: For every non-pie/non-table chart, either y_axis OR series_fields MUST be set. Never leave both empty.

   c) **SAVE THE DATA**: Save as `chart_data.csv` — pipeline only reads this file. Final step must call `to_csv('chart_data.csv', index=False)`.

   d) **SAVE THE INSIGHT**: Save as `insight.json` — pipeline only reads this file.

   e) **PRINT CHART TYPE**: State the recommended chart type in the output

**STEP 4: FINAL DATA-DRIVEN INSIGHT**
- Concise 2–3 sentence insight grounded in the numbers found
"""

EXECUTOR_WORKFLOW_LOCAL = """### STEP-BY-STEP WORKFLOW (follow in order)

You are writing Python that runs in a stateful interpreter. Respond with EXACTLY
ONE Python code block (```python ... ```) per turn. After each block runs you
will see its stdout, then continue with the next block. Variables persist
between blocks. The ONLY libraries available are: pandas (as `pd`), numpy (as
`np`), json, math, statistics, datetime. There is NO filesystem access — do not
read or write any files.

IMPORTANT: Write one code block for each step, so that you can use the actual
data printed for the next steps.

**STEP 1: ANALYZE THE DATA**
- The datasets are ALREADY loaded as pandas DataFrame variables named
  `input_file_0`, `input_file_1`, ... Their exact columns, dtypes, and sample
  rows are shown above — rely on those EXACT column names. Use the variables
  directly — do NOT read any CSV files.
- Use ONLY columns that appear in the schema above. NEVER assume a column exists
  (e.g. a generic "date" column) and NEVER `raise` if an expected column is
  missing — instead inspect `df.columns` / `df.head()` and adapt to the real
  shape. Dates may be encoded in a differently named column or split across
  columns (e.g. year/month); derive the period from whatever columns exist.
- If multiple variables represent the same dataset with different parameters
  (shown in brackets next to the name, e.g. `[canopy_cover=50]`), treat each as a
  separate series and use the parameter value as the series label.
- Print which dataset(s) you are using (name, date range, and any filtering parameters)
- Calculate key statistics relevant to the user query
- Print your key findings clearly
- Do **NOT** create any plots or charts

**STEP 2: SUMMARIZE INSIGHTS**
- Summarize the data relevant to the user query
- Identify the most important patterns, trends, or comparisons
- Print a clear summary of what the data shows
- Include contextual layers or parameters used for analysis on the datasets

**STEP 3: GENERATE CHART DATA**
Prepare the data for visualization in Recharts.js:

   a) **CHART TYPE SELECTION** - Choose the most appropriate chart type:
      - **line**: Time series data, trends over time (supports multi-series)
      - **bar**: Categorical comparisons, rankings (supports multi-series for grouped bars)
      - **stacked-bar**: Show composition within categories (use wide format with multiple metric columns)
      - **grouped-bar**: Compare multiple metrics side-by-side (use long format with group column)
      - **pie**: Part-to-whole relationships (limit to 6-8 categories max)
      - **area**: Cumulative trends, stacked time series (supports multi-series)
      - **scatter**: Show correlations between two variables
      - **table**: Detailed data when visualization isn't optimal

   b) **CREATE CHART DATA** following these requirements:
      1. **Structure**: Array of objects (rows) with simple field names as columns
      2. **Field names**: Use clear, lowercase names like 'date', 'value', 'category', 'year', 'count'
      3. **Numeric values**: Always numbers, never strings (e.g., 100 not "100")
      4. **Date ordering**: Chronological order for time series, not alphabetical
      5. **Grouping fields**: Group only by categorical, readable label columns such as names, dates, periods, classes, or metric labels. Do not group by numeric measure/value columns like 'value', 'count', 'area', 'sum', or continuous numeric readings unless the user explicitly asks for a distribution or histogram; aggregate those numeric columns instead.
      6. **Data format by chart type**:
         - **Single-series line/bar**: [{"date": "2020-01", "value": 100}]
           → One metric column, use y_axis="value" (REQUIRED — must not be empty)
         - **Multi-series line/bar/area**: [{"year": "2020", "metric1": 100, "metric2": 50}]
           → Multiple metric columns in WIDE format
           → Use series_fields=["metric1", "metric2"], leave y_axis="" (REQUIRED — series_fields must not be empty)
         - **Stacked-bar**: [{"category": "Region A", "forest": 100, "grassland": 50, "urban": 30}]
           → Use series_fields=["forest", "grassland", "urban"], leave y_axis="" (REQUIRED — series_fields must not be empty)
         - **Grouped-bar**: long format with group_field and y_axis="value" (REQUIRED — both must not be empty)
         - **Pie**: [{"name": "Category A", "value": 100}], max 6–8 slices
         - **IMPORTANT**: For every non-pie/non-table chart, either y_axis OR series_fields MUST be set. Never leave both empty.

**STEP 4: PRODUCE THE FINAL RESULT**
In your FINAL code block, assign these two variables (the pipeline reads them
directly from the interpreter — do NOT print them as the result, just assign):
   - `chart_data`: a list of row dicts (the array described above).
   - `insight`: a dict matching the MultiChartInsight schema. It MUST have a
     top-level `charts` LIST (each entry is one ChartInsight), plus
     `primary_insight` and `follow_up_suggestions`. Do NOT put the chart fields
     (title/chart_type/x_axis/...) at the top level of `insight`.

Exact shape to follow:
```python
chart_data = [
    {"year": 2020, "loss": 100},
    {"year": 2021, "loss": 120},
]
insight = {
    "charts": [
        {
            "title": "Tree cover loss over time",
            "chart_type": "line",
            "x_axis": "year",
            "y_axis": "loss",        # or use series_fields=[...] for multi-series
        }
    ],
    "primary_insight": "Loss increased from 2020 to 2021.",
    "follow_up_suggestions": ["Compare against a neighbouring region."],
}
```
Also `print()` the recommended chart type and a concise 2–3 sentence
data-driven insight grounded in the numbers found.
"""

WORDING_GUIDE = """# Wording

- Use dataset cautions/limitations proactively but briefly (e.g. clarify tree cover loss vs deforestation when relevant).
- Avoid strong or vague claims without evidence.

**Avoid:** overwhelming, severe, exceptional, critical, concerning, highly, substantial, considerable, notable, remarkable, important, major, crucial, key, strong, robust, dramatic, meaningful (vague), alarming, worrying, problematic, challenging, unfavorable, promising, encouraging, favorable.

**Prefer:** decline, decrease, increase, remain stable, fluctuate.

**Use carefully (need justification):** trend (if not calculated), significant (if not statistical), validated, accurate (without comparison).

- Use markdown with blank lines between sections.
"""
