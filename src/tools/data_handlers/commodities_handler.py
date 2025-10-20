from typing import Any, Dict, List

import pandas as pd

from src.tools.data_handlers.base import DataPullResult, DataSourceHandler
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

GADM_LEVELS = {
    "country": 0,
    "state-province": 1,
    "district-county": 2,
}

COMMODITIES_DATASET_ID = 9


class CommoditiesHandler(DataSourceHandler):
    def can_handle(self, dataset: Any) -> bool:
        return dataset.get("dataset_id") == COMMODITIES_DATASET_ID

    _commodities = {}

    def _get_commodities_data(self, admin_level):
        if admin_level not in self._commodities:
            self._commodities[admin_level] = pd.read_parquet(
                f"data/emission_factors_CO2e_ADM{admin_level}_master.parquet"
            )
        return self._commodities[admin_level]

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
        admin_level = GADM_LEVELS[aoi["subtype"]]
        data = self._get_commodities_data(admin_level)
        selected_rows = data[data[f"GID_{admin_level}"] == aoi["gadm_id"]]

        if selected_rows.empty:
            return DataPullResult(
                success=False,
                data=None,
                message=f"No data found for {aoi['name']}",
                data_points_count=0,
            )

        result = selected_rows.to_dict(orient="list")

        count = len(next(iter(result.values())))

        return DataPullResult(
            success=True,
            data=result,
            message=f"Successfully pulled {count} data points from commodities data for {aoi['name']}",
            data_points_count=count,
        )
