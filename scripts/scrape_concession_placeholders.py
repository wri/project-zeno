"""Scrape placeholder concession polygons from the public GFW tile caches.

Exploratory. The official concession files (and the Data API query endpoint)
need credentials this project does not have yet, so this reads what the
public map reads: the static vector tile cache of each dataset, sampled
around a few producer regions. Replace with the official shapefiles.

Two modes::

    # Every concession of one dataset seen in the sampled tiles, with the
    # tile geometry (simplified at zoom 8). Feeds src/ingest/ingest_oil_palm.py.
    uv run --with mapbox-vector-tile python scripts/scrape_concession_placeholders.py \\
        all gfw_oil_palm data/oil_palm_placeholder.geojson

    # A few concessions of each of the five datasets, at full resolution from
    # the public geostore, plus every attribute row seen (for profiling).
    uv run --with mapbox-vector-tile python scripts/scrape_concession_placeholders.py \\
        sample data/concessions_sample.geojson

Every feature keeps all its source attributes and gets a ``dataset`` property.
"""

import gzip
import json
import math
import sys
import urllib.request
from collections import defaultdict

import mapbox_vector_tile
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

VERSION = "v2025"
DATASETS = {
    "gfw_managed_forests": "logging",
    "gfw_mining_concessions": "mining",
    "gfw_oil_palm": "oil-palm",
    "rspo_oil_palm": "rspo-oil-palm",
    "gfw_wood_fiber": "wood-fiber",
}
# (lon, lat) centres of the sampled producer regions. Each is read as a 3x3
# block of tiles at ZOOM.
HOTSPOTS = [
    (113.5, -1.5),  # Central Kalimantan
    (101.5, 0.5),  # Riau, Sumatra
    (140.0, -7.0),  # South Papua
    (22.0, 1.0),  # DRC
    (11.5, 1.0),  # Cameroon / Gabon
    (-1.5, 6.5),  # Ghana
    (-75.0, -8.5),  # Peru
    (-54.0, -6.0),  # Para, Brazil
    (-9.5, 6.5),  # Liberia
]
ZOOM = 8
PER_DATASET = 8
MAX_PER_COUNTRY = 3


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def tile_transform(x: int, y: int, z: int, extent: int):
    """Tile pixel coordinates to lon/lat. mapbox_vector_tile flips y up."""
    n = 2**z

    def to_lonlat(px, py, pz=None):
        lon = (x + px / extent) / n * 360 - 180
        ty = y + 1 - py / extent
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
        return lon, lat

    return to_lonlat


def fetch_tile(dataset: str, z: int, x: int, y: int) -> dict:
    url = (
        f"https://tiles.globalforestwatch.org/{dataset}/{VERSION}/default/"
        f"{z}/{x}/{y}.pbf"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "zeno-sample"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
    except Exception:
        return {}
    # The tile cache serves gzipped protobuf.
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return mapbox_vector_tile.decode(body)


def fetch_geostore(geostore_id: str | None) -> dict | None:
    """The full-resolution geometry, from the public geostore endpoint."""
    if not geostore_id:
        return None
    url = f"https://data-api.globalforestwatch.org/geostore/{geostore_id}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)["data"]["gfw_geojson"]
    except Exception:
        return None


def collect(dataset: str) -> tuple[dict, dict]:
    """Tile pieces and attributes of every concession in the hot spots,
    keyed by ``gfw_fid``. A concession across tile edges has several pieces."""
    parts: dict = defaultdict(list)
    props: dict = {}
    for lon, lat in HOTSPOTS:
        cx, cy = lonlat_to_tile(lon, lat, ZOOM)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                x, y = cx + dx, cy + dy
                for layer in fetch_tile(dataset, ZOOM, x, y).values():
                    tf = tile_transform(x, y, ZOOM, layer.get("extent", 4096))
                    for feat in layer["features"]:
                        p = feat["properties"]
                        fid = p.get("gfw_fid") or feat.get("id")
                        parts[fid].append(
                            transform(tf, shape(feat["geometry"]))
                        )
                        props[fid] = p
    return parts, props


def feature(dataset: str, props: dict, geometry: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {"dataset": dataset, **props},
        "geometry": geometry,
    }


def scrape_all(dataset: str, out: str) -> None:
    parts, props = collect(dataset)
    features = []
    for fid, geoms in parts.items():
        geom = unary_union(geoms).buffer(0)
        if not geom.is_empty:
            features.append(feature(dataset, props[fid], mapping(geom)))
    with open(out, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)
    print(f"{dataset}: {len(features)} features → {out}", file=sys.stderr)


def scrape_sample(out: str) -> None:
    features = []
    for dataset in DATASETS:
        parts, props = collect(dataset)
        # Named concessions first, at most a few per country.
        ranked = sorted(
            parts,
            key=lambda f: (
                not props[f].get("conc_name"),
                props[f].get("iso3", ""),
            ),
        )
        per_country: dict = defaultdict(int)
        picked = []
        for fid in ranked:
            iso = props[fid].get("iso3")
            if per_country[iso] >= MAX_PER_COUNTRY:
                continue
            per_country[iso] += 1
            picked.append(fid)
            if len(picked) == PER_DATASET:
                break
        for fid in picked:
            geom = fetch_geostore(props[fid].get("gfw_geostore_id"))
            if geom is None:
                geom = mapping(unary_union(parts[fid]).buffer(0))
            features.append(feature(dataset, props[fid], geom))
        attrs_out = out.replace(".geojson", f"_{dataset}_attrs.json")
        with open(attrs_out, "w") as fh:
            json.dump(list(props.values()), fh)
        print(
            f"{dataset}: {len(parts)} seen, {len(picked)} kept",
            file=sys.stderr,
        )
    with open(out, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "all":
        scrape_all(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3 and sys.argv[1] == "sample":
        scrape_sample(sys.argv[2])
    else:
        sys.exit(__doc__)
