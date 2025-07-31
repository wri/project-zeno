"""
Base classes and shared components for data handlers.

This module contains the abstract base classes and shared utilities
that are used by both the orchestrator and individual handlers,
preventing circular imports.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from pydantic import BaseModel

from src.utils.geocoding_helpers import GADM_LEVELS as gadm_levels


# DATASET NAME MAPPINGS
dataset_names = {
    "Tree cover loss": "tcl",
    "Tree cover loss due to fires": "tcl",
    "DIST-ALERT": "DIST-ALERT",
}


class DataPullResult(BaseModel):
    """Result of a data pull operation"""

    success: bool
    data: Any
    message: str
    data_points_count: int = 0


class DataSourceHandler(ABC):
    """Abstract base class for data source handlers"""

    @abstractmethod
    def can_handle(self, dataset: Any, table_name: str) -> bool:
        """Check if this handler can process the given dataset and table"""
        pass

    @abstractmethod
    async def pull_data(
        self,
        query: str,
        aoi: Dict,
        subregion_aois: List[Dict],
        subregion: str,
        subtype: str,
        dataset: Dict,
        start_date: str,
        end_date: str,
    ) -> DataPullResult:
        """Pull data from the source"""
        pass
