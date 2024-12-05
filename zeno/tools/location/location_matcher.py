import json
from typing import List

import geopandas as gpd
from shapely import box

NAME_COLS = ["NAME_0", "NAME_1", "NAME_2", "NAME_3", "NAME_4", "NAME_5"]
NR_OF_RESULTS = 3


def fuzz_search(row: gpd.GeoSeries, query: str):
    return sum([dat in row["name"].lower() for dat in query.lower().split(" ")])
    # ratios = [fuzz.token_set_ratio(dat, query) for dat in row["name"].lower().split(" ")]
    # return sum([dat for dat in ratios if dat > 0.5])


class LocationMatcher:
    def __init__(self, csv_path: str) -> None:
        """
        Initialize the matcher with GADM CSV data
        """
        # self.df = pd.read_csv(csv_path)
        self.df = gpd.read_file(csv_path)

    def get_by_id(self, id: str) -> dict:
        return json.loads(self.df[self.df.gadmid == id].to_json())

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
        return list(self.df[matches].gadmid)
