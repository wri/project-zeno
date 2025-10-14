from typing import Any, Dict, List

import pandas as pd

from src.tools.data_handlers.base import DataPullResult, DataSourceHandler
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

GADM_LEVELS = {
    "country": "GID_0",
    "state-province": "GID_1",
    "district-county": "GID_2",
}

COMMODITIES_DATASET_ID = 9


class CommoditiesHandler(DataSourceHandler):
    def can_handle(self, dataset: Any) -> bool:
        return dataset.get("dataset_id") == COMMODITIES_DATASET_ID

    _commodities = None

    def _get_commodities_data(self):
        if self._commodities is None:
            self._commodities = pd.read_parquet(
                "data/all_commodities_adm2_ch4_nogeom.parquet"
            )
            print(self._commodities.head())
        return self._commodities

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
        if aoi["subtype"] not in GADM_LEVELS:
            msg = f"AOI subtype {aoi['subtype']} not supported for commodities data"
            return DataPullResult(
                success=False,
                data=None,
                message=msg,
                data_points_count=0,
            )
        aoi_name = aoi["name"]
        data = self._get_commodities_data()
        level = GADM_LEVELS[aoi["subtype"]]
        selected_rows = data[data[level] == aoi["gadm_id"]]

        result = selected_rows.to_dict(orient="list")

        count = len(next(iter(result.values())))

        return DataPullResult(
            success=True,
            data=result,
            message=f"Successfully pulled {count} data points from commodities data for {aoi_name}",
            data_points_count=count,
        )
