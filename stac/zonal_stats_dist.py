from typing import List, Optional

import pandas as pd
import rioxarray  # noqa: F401
import xarray as xr
from pystac import Item
from pystac_client import Client
from shapely.geometry.base import BaseGeometry
from stackstac import stack

STAC_API_URL = "https://eoapi.zeno-staging.ds.io/stac"
DIST_BASE_DATE = pd.Timestamp("2015-01-01")


def reduce_to_first_non_nan(
    da: xr.DataArray, dim: str = "time"
) -> xr.DataArray:
    """
    Reduce an already concatenated DataArray to first non-NaN values along a dimension.
    """
    first_valid_mask = (~da.isnull()).cumsum(dim=dim) == 1
    result = da.where(first_valid_mask).ffill(dim=dim).isel({dim: 0})
    if dim in result.dims and result.sizes[dim] == 1:
        result = result.squeeze(dim)

    return result


def integer_check(items: List[Item]) -> None:
    """Check that context items have integer data type."""
    integer_types = [
        "int8",
        "uint8",
        "int16",
        "uint16",
        "int32",
        "uint32",
        "int64",
        "uint64",
    ]
    for item in items:
        for asset in item.assets.values():
            data_type = asset.extra_fields.get("raster:bands", [{}])[0].get(
                "data_type", ""
            )
            if data_type not in integer_types:
                raise ValueError(
                    f"Context layer must have integer data type, got {data_type}"
                )


def get_pixels(
    area_geom: BaseGeometry, context_layer: str = ""
) -> Optional[xr.DataArray]:
    stac = Client.open(STAC_API_URL)

    collections = ["dist-alerts"]
    if context_layer:
        collections.append(context_layer)

    search = stac.search(
        collections=collections,
        intersects=area_geom,
    )

    dist_alert_items = [
        item for item in search.get_items() if item.id == "dist-alerts-default"
    ]
    context_items = [
        item
        for item in search.get_items()
        if not item.id.startswith("dist-alerts-")
    ]

    if not len(dist_alert_items):
        return None

    dist_alert_pixels = stack(
        dist_alert_items,
        bounds_latlon=area_geom.bounds,
        epsg=4326,
    ).compute()

    result = reduce_to_first_non_nan(dist_alert_pixels)

    if len(context_items):
        integer_check(context_items)

        context_pixels = stack(
            context_items,
            bounds_latlon=area_geom.bounds,
            epsg=4326,
        ).compute()

        context_pixels = reduce_to_first_non_nan(context_pixels)

        result = xr.concat([result, context_pixels], dim="band")

    return result.rio.clip([area_geom])


def compute_data_statistics(data: xr.DataArray) -> pd.DataFrame:
    """Compute comprehensive cross-tabulation of class, date, and threshold."""

    days_since_2015 = data[0] % 10000
    dates = DIST_BASE_DATE + pd.to_timedelta(
        days_since_2015.values.flatten(), unit="D"
    )

    confidence = (data[0] // 10000).values.flatten()

    if data.shape[0] > 1:
        vars = [confidence, data[1].values.flatten()]
        colnames = ["alerts", "context"]
        id_vars = ["date", "context"]
    else:
        vars = [confidence]
        colnames = ["alerts"]
        id_vars = ["date"]

    data = (
        pd.crosstab(
            dates.date,
            vars,
            rownames=["date"],
            colnames=colnames,
        )
        .stack()
        .fillna(0)
    )

    if len(id_vars) > 1:
        data = pd.melt(
            data.reset_index(),
            id_vars=id_vars,
            var_name="alerts",
            value_name="count",
        )
    else:
        data = data.reset_index()
        data.columns = ["date", "alerts", "count"]

    data = data[data["count"] != 0]

    return data


def compute_dist_alert_stats_for_area(
    area_geom: BaseGeometry, context_layer: str = ""
) -> Optional[pd.DataFrame]:
    """Compute DIST alerts statistics for a geometry and an optional context layer."""

    data = get_pixels(area_geom, context_layer)
    if data is None:
        return None

    stats = compute_data_statistics(data)

    return stats
