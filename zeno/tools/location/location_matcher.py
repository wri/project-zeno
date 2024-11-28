import json
from typing import List

import geopandas as gpd
from shapely import box
from thefuzz import fuzz

NAME_COLS = ["NAME_1", "NAME_2", "NAME_3"]
NR_OF_RESULTS = 3


def fuzz_search(row: gpd.GeoSeries, query: str):
    return sum([fuzz.ratio(row[name].lower(), query) for name in NAME_COLS])


class LocationMatcher:
    def __init__(self, csv_path: str) -> None:
        """
        Initialize the matcher with GADM CSV data
        """
        # self.df = pd.read_csv(csv_path)
        self.df = gpd.read_file(csv_path, layer="ADM_ADM_3")
        self.df["full_name"] = self.df[NAME_COLS].agg(" ".join, axis=1)

    def get_by_id(self, id: str) -> dict:
        return json.loads(self.df[self.df.GID_3 == id].to_json())

    def find_matches(self, query: str) -> List[str]:
        """
        Find matching locations for a given query.
        Priority order: NAME_2 > NAME_1 > NAME_3
        Returns top 3 for NAME_2 matches, all matches for NAME_1 and NAME_3
        """
        query = query.lower().strip()
        self.df["score"] = self.df.apply(lambda x: fuzz_search(x, query), axis=1)
        return self.df.sort_values("score", ascending=False)[:NR_OF_RESULTS]

    def find_by_bbox(
        self, xmin: float, ymin: float, xmax: float, ymax: float
    ) -> List[str]:
        matches = self.df.intersects(box(xmin, ymin, xmax, ymax))
        return list(self.df[matches].GID_3)
