"""Analytics API dataset names as Zeno's catalog dataset ids, so catalog
instructions, cautions and colors still apply."""

from typing import Any, Optional


class UnknownDatasetError(LookupError):
    pass


class DatasetIds:
    """Finds the catalog dataset for an analytics API dataset name, so its
    catalog instructions, cautions and colors still apply.

    Several catalog datasets share one API dataset and differ only by the
    intersection requested, so those are looked up by name and intersection
    first. Aliases cover API datasets that are views of one catalog dataset.
    """

    def __init__(
        self,
        catalog: list[dict[str, Any]],
        intersection_ids: dict[tuple[str, str], int],
        alias_ids: dict[str, int],
    ):
        self.intersection_ids = intersection_ids
        self.alias_ids = alias_ids
        self.plain_ids = plain_dataset_ids(
            catalog, set(intersection_ids.values())
        )

    def dataset_id_for(
        self, dataset: str, intersections: Optional[list[str]]
    ) -> int:
        for intersection in intersections or []:
            dataset_id = self.intersection_ids.get((dataset, intersection))
            if dataset_id is not None:
                return dataset_id
        if dataset in self.alias_ids:
            return self.alias_ids[dataset]
        if dataset in self.plain_ids:
            return self.plain_ids[dataset]
        raise UnknownDatasetError(f"No catalog dataset for {dataset}")


def plain_dataset_ids(
    catalog: list[dict[str, Any]], intersection_ids: set[int]
) -> dict[str, int]:
    """Catalog dataset ids by the API dataset name in their endpoint, leaving
    out the datasets that are an intersection of another."""
    ids = {}
    for row in catalog:
        endpoint = row.get("analytics_api_endpoint")
        if endpoint and row["dataset_id"] not in intersection_ids:
            ids[api_dataset_name(endpoint)] = row["dataset_id"]
    return ids


def api_dataset_name(endpoint: str) -> str:
    """The API dataset name in an endpoint such as
    /v0/land_change/tree_cover_loss/analytics."""
    return endpoint.rstrip("/").removesuffix("/analytics").rsplit("/", 1)[-1]
