"""Base classes and types for code executors."""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ExecutionResult:
    """Result from code execution."""

    text_output: List[str]
    code_blocks: List[str]
    execution_outputs: List[str]
    chart_data: Optional[List[Dict]]
    error: Optional[str] = None
