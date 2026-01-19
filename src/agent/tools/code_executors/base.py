"""Base classes and types for code executors."""

from base64 import b64encode
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel


class PartType(Enum):
    TEXT_OUTPUT = "text_output"
    CODE_BLOCK = "code_block"
    EXECUTION_OUTPUT = "execution_output"


class CodeActPart(BaseModel):
    type: PartType
    content: str


@dataclass
class ExecutionResult:
    """Result from code execution."""

    parts: List[CodeActPart]
    chart_data: Optional[List[Dict]]
    error: Optional[str] = None

    def get_encoded_parts(self) -> List[Dict]:
        return [
            {
                "type": part.type.value,
                "content": b64encode(part.content.encode("utf-8")).decode(
                    "utf-8"
                ),
            }
            for part in self.parts
        ]
