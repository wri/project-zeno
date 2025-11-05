# Gemini Code Executor

Simple code executor for `generate_insights` using Gemini's native code execution.

## Overview

- **`GeminiCodeExecutor`**: Executes code with Gemini using inline data
- **`ExecutionResult`**: Simple dataclass for results

### Key Methods

1. **`prepare_dataframes(dataframes: List[tuple[DataFrame, str]]) -> List[Dict]`**
   - Convert DataFrames to inline_data format
   - No file I/O needed

2. **`execute(prompt: str, inline_data_parts: List[Dict]) -> ExecutionResult`**
   - Execute code with Gemini
   - Returns text output, code blocks, and chart data

## Usage

```python
from src.tools.code_executors import GeminiCodeExecutor
import pandas as pd

# Prepare DataFrames
dataframes = [
    (df1, "Odisha tree cover loss"),
    (df2, "Assam tree cover loss")
]

# Execute analysis
executor = GeminiCodeExecutor()

# Prepare inline data
inline_data = await executor.prepare_dataframes(dataframes)

# Run analysis
result = await executor.execute(
    prompt="Compare deforestation trends",
    inline_data_parts=inline_data
)

# Access results
print(result.text_output)  # Analysis text
print(result.chart_data)   # List of dicts for charting
```

## How It Works

1. **DataFrames → inline_data**: Convert DataFrames directly to CSV bytes
2. **Send to Gemini**: Pass as inline_data in request (no file upload)
3. **Code execution**: Gemini runs Python code in sandbox
4. **Parse response**: Extract text, code, and chart_data.csv

**Benefits:**
- No file I/O or temp directories
- No upload/delete lifecycle
- Stateless and simple
- Fast execution

## Implementation Details

### Inline Data Format

```python
inline_part = {
    "inline_data": {
        "mime_type": "text/csv",
        "data": df.to_csv(index=False).encode("utf-8")
    }
}
```

### Response Parsing

Gemini returns:
- `part.text`: Analysis text
- `part.executable_code`: Python code executed
- `part.code_execution_result`: Execution output
- `part.inline_data`: chart_data.csv (base64 encoded)

### ExecutionResult

```python
@dataclass
class ExecutionResult:
    text_output: str              # Combined analysis text
    code_blocks: List[str]        # Code that was executed
    execution_outputs: List[str]  # Print outputs
    chart_data: Optional[List[Dict]]  # Parsed chart_data.csv
    error: Optional[str] = None   # Error if failed
```

## Best Practices

1. **Handle errors**: Check `result.error` field before using results
2. **Validate chart_data**: Ensure it's not None before using
3. **Keep DataFrames clean**: Drop constant columns before passing
4. **Reuse executor**: Create once and reuse for multiple analyses if needed

## Troubleshooting

- **No chart_data**: Check if Gemini code saved `chart_data.csv`
- **API errors**: Check Gemini API key and quota
- **Large DataFrames**: Consider sampling or chunking data
- **Parse errors**: Ensure DataFrames have valid column names
