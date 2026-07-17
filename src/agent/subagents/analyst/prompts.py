"""Prompts for the analyst subagent behind `generate_insights`.

EXECUTOR_WORKFLOW is the step-by-step workflow the code executor follows to
turn pulled data into chart JSON. WORDING_GUIDE is the neutral,
measurement-first language guide for user-facing text, used by the separate
text stage (`InsightTextGenerator`).
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
- Include contextual layers or parameters used for analysis on the datasets
- Use this summary to ground the chart(s) you generate in the next step

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
      6. **Query-aligned labels**: Chart category labels must use the concepts from the user's query, not raw data column values — if the query describes a category in its own words while the data encodes it under a different label, relabel the category to match the query's language. If the query asks for a percentage, compute and include percentage values so a reader can verify the answer directly from the chart.
      7. **Data format by chart type**:
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

   d) **SAVE THE CHART SPEC**: Save the chart spec(s) as `insight.json` — the
      pipeline only reads this file. A separate stage generates the narrative,
      so do not write any insight text here.

   e) **PRINT CHART TYPE**: State the recommended chart type in the output
"""

WORDING_GUIDE = """# Wording

- Use dataset cautions/limitations proactively but briefly (e.g. clarify tree cover loss vs deforestation when relevant).
- Avoid strong or vague claims without evidence.

**Avoid:** overwhelming, severe, exceptional, critical, concerning, highly, substantial, considerable, notable, remarkable, important, major, crucial, key, strong, robust, dramatic, meaningful (vague), alarming, worrying, problematic, challenging, unfavorable, promising, encouraging, favorable.

**Prefer:** decline, decrease, increase, remain stable, fluctuate.

**Use carefully (need justification):** trend (if not calculated), significant (if not statistical), validated, accurate (without comparison).

- Use markdown with blank lines between sections.
"""
