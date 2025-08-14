# Data Source Handlers

This directory contains modular data source handlers for the `pull_data` system. The refactored architecture uses a strategy pattern to handle different data sources in a clean, extensible way.

## Architecture Overview

### Core Components

1. **DataSourceHandler (Abstract Base Class)**: Defines the interface that all handlers must implement
2. **DataPullResult**: Standardized result object returned by all handlers
3. **DataPullOrchestrator**: Manages and routes requests to appropriate handlers
4. **Built-in Handlers**:
   - `AnalyticsHandler`: Handles multiple analytics datasets (DIST-ALERT, natural lands, grasslands, tree cover loss) from GFW Analytics API endpoints
   - `GFWSQLHandler`: Handles standard GFW data sources with SQL queries

### Key Benefits

- **Modularity**: Each data source has its own focused handler
- **Extensibility**: Easy to add new data sources without modifying existing code
- **Maintainability**: Clear separation of concerns and single responsibility
- **Testability**: Each handler can be tested independently
- **Readability**: Complex conditional logic replaced with clear handler classes

## Adding a New Data Source

To add support for a new data source:

1. **Create a new handler class** that inherits from `DataSourceHandler`
2. **Implement the required methods**:
   - `can_handle(dataset)`: Return True if this handler should process the request
   - `pull_data(...)`: Implement the actual data pulling logic
3. **Register the handler** in `DataPullOrchestrator.__init__()`

### Example Handler Structure

```python
from src.tools.pull_data import DataSourceHandler, DataPullResult

class MyCustomHandler(DataSourceHandler):
    def can_handle(self, dataset: Any) -> bool:
        return dataset.source == "MY_API"

    def pull_data(self, query: str, aoi_name: str, dataset: Any, aoi: Dict,
                  subregion: str, subtype: str) -> DataPullResult:
        try:
            # Your custom data pulling logic here
            data = fetch_from_my_api(aoi, dataset)

            return DataPullResult(
                success=True,
                data=data,
                message=f"Successfully pulled data from My API",
                data_points_count=len(data)
            )
        except Exception as e:
            return DataPullResult(
                success=False,
                data={'data': []},
                message=f"Failed to pull data: {e}"
            )
```

## Handler Registration

Add your handler to the orchestrator in `pull_data.py`:

```python
class DataPullOrchestrator:
    def __init__(self):
        self.handlers = [
            AnalyticsHandler(),
            GFWSQLHandler(),
            MyCustomHandler(),  # Add your handler here
        ]
```

## Error Handling

All handlers should:
- Return `DataPullResult` objects with consistent structure
- Handle exceptions gracefully and return appropriate error messages
- Log errors using the project's logging system
- Maintain backward compatibility with existing data formats

## Testing

Each handler should have corresponding unit tests that verify:
- Correct identification of supported datasets (`can_handle`)
- Successful data pulling scenarios
- Error handling and edge cases
- Data format consistency
