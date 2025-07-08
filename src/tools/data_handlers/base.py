"""
Base classes and shared components for data handlers.

This module contains the abstract base classes and shared utilities
that are used by both the orchestrator and individual handlers,
preventing circular imports.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from pydantic import BaseModel

# GADM LEVELS
gadm_levels = {
    "country": {"col_name": "GID_0", "name": "iso"},
    "state-province": {"col_name": "GID_1", "name": "adm1"},
    "district-county": {"col_name": "GID_2", "name": "adm2"},
    "municipality": {"col_name": "GID_3", "name": "adm3"},
    "locality": {"col_name": "GID_4", "name": "adm4"},
    "neighbourhood": {"col_name": "GID_5", "name": "adm5"},
}

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
    def pull_data(
        self,
        query: str,
        aoi_name: str,
        dataset: Any,
        aoi: Dict,
        subregion: str,
        subtype: str,
    ) -> DataPullResult:
        """Pull data from the source"""
        pass
