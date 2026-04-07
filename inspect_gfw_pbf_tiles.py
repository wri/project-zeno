#!/usr/bin/env python3
"""Download and inspect sample GFW vector PBF tiles.

Uses **static** vector tiles only: ``/{dataset}/{version}/default/{z}/{x}/{y}.pbf``
(see https://tiles.globalforestwatch.org/openapi.json — StaticVectorTileCacheDatasets).
No ``/dynamic/`` endpoints.

This script:
- fetches a sample tile per dataset (scans x/y until one succeeds, unless a seed is set)
- decodes vector tile layers/features
- prints a schema-on-tile summary of layer properties

Requires:
    uv add mapbox-vector-tile
or:
    pip install mapbox-vector-tile
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.error
import urllib.request
import zlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import mapbox_vector_tile
except ImportError:
    print(
        "Missing dependency: mapbox-vector-tile\n"
        "Install with: uv add mapbox-vector-tile",
        file=sys.stderr,
    )
    raise


BASE_URL = "https://tiles.globalforestwatch.org"
ZOOM_LEVEL = 2


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    version: str = "latest"
    implementation: str = "default"
    # Override global zoom when a dataset only has geometry at higher z on static CDN.
    zoom: Optional[int] = None
    # Optional (x, y) tried before full scan (avoids huge scans at high z).
    sample_xy: Optional[Tuple[int, int]] = None


TARGET_DATASETS: List[DatasetSpec] = [
    DatasetSpec("birdlife_key_biodiversity_areas", "v20240903"),
    # Combined GADM uses v4.1.85 on static; level splits use v4.1.
    DatasetSpec("gadm_administrative_boundaries", "v4.1.85"),
    DatasetSpec("gadm_administrative_boundaries_adm0", "v4.1"),
    DatasetSpec(
        "gadm_administrative_boundaries_adm0_adm1",
        "v4.1",
        zoom=3,
    ),
    DatasetSpec(
        "gadm_administrative_boundaries_adm0_adm1_adm2",
        "v4.1",
        zoom=6,
        sample_xy=(0, 16),
    ),
    DatasetSpec("landmark_indigenous_and_community_lands", "latest"),
    DatasetSpec("wdpa_protected_areas", "latest"),
]


def tile_url(spec: DatasetSpec, z: int, x: int, y: int) -> str:
    return f"{BASE_URL}/{spec.name}/{spec.version}/{spec.implementation}/{z}/{x}/{y}.pbf"


def fetch_tile(url: str, timeout_sec: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "project-zeno-next/inspect-gfw-pbf",
            "Accept": "application/x-protobuf,application/octet-stream,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as response:
        payload = response.read()
        content_encoding = (
            response.headers.get("Content-Encoding") or ""
        ).lower()

    # GFW tiles are sometimes returned as compressed payloads even for .pbf URLs.
    # Decode to raw protobuf bytes before passing into mapbox_vector_tile.decode.
    if content_encoding == "gzip":
        return gzip.decompress(payload)
    if content_encoding == "deflate":
        return zlib.decompress(payload)

    # Fallback for cases where content-encoding header is absent/misconfigured.
    if payload.startswith(b"\x1f\x8b"):
        return gzip.decompress(payload)
    return payload


def guess_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def print_dataset_header(spec: DatasetSpec) -> None:
    print("\n" + "=" * 100)
    print(f"DATASET: {spec.name}")
    print(f"VERSION: {spec.version}")
    print(f"IMPLEMENTATION: {spec.implementation}")
    print("=" * 100)


def inspect_decoded_tile(decoded: Dict[str, Any]) -> None:
    if not decoded:
        print("No layers decoded from tile.")
        return

    for layer_name, layer_data in decoded.items():
        features: List[Dict[str, Any]] = layer_data.get("features", [])
        extent: Any = layer_data.get("extent")
        version: Any = layer_data.get("version")

        print(f"\nLayer: {layer_name}")
        print(f"  Feature count: {len(features)}")
        if extent is not None:
            print(f"  Extent: {extent}")
        if version is not None:
            print(f"  Vector tile version: {version}")

        if not features:
            print("  (No features)")
            continue

        geom_types: Dict[str, int] = defaultdict(int)
        prop_types: Dict[str, set] = defaultdict(set)
        sample_values: Dict[str, Any] = {}

        for feature in features:
            geom_type = feature.get("geometry", {}).get("type", "Unknown")
            geom_types[geom_type] += 1

            props = feature.get("properties", {})
            for key, value in props.items():
                prop_types[key].add(guess_type(value))
                if key not in sample_values:
                    sample_values[key] = value

        print("  Geometry types:")
        for geom_type, count in sorted(geom_types.items(), key=lambda x: x[0]):
            print(f"    - {geom_type}: {count}")

        print(f"  Property keys ({len(prop_types)}):")
        for key in sorted(prop_types):
            types = ", ".join(sorted(prop_types[key]))
            sample = sample_values.get(key)
            sample_repr = repr(sample)
            if len(sample_repr) > 120:
                sample_repr = sample_repr[:117] + "..."
            print(f"    - {key}: [{types}] | sample={sample_repr}")


def find_first_available_tile(
    spec: DatasetSpec, default_z: int
) -> Tuple[str, bytes]:
    z = spec.zoom if spec.zoom is not None else default_z

    def try_xy(x: int, y: int) -> Tuple[str, bytes] | None:
        url = tile_url(spec, z, x, y)
        try:
            data = fetch_tile(url)
            if data:
                return url, data
        except urllib.error.HTTPError:
            pass
        except urllib.error.URLError:
            pass
        return None

    if spec.sample_xy is not None:
        sx, sy = spec.sample_xy
        hit = try_xy(sx, sy)
        if hit:
            return hit

    for x in range(0, 2**z):
        for y in range(0, 2**z):
            hit = try_xy(x, y)
            if hit:
                return hit

    raise RuntimeError(
        f"Could not download any z={z} tile for dataset {spec.name}"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect sample GFW static vector tiles (default implementation) "
            "for selected datasets."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print decoded tile JSON for each selected sample tile.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    print(
        "Inspecting GFW static vector tile samples "
        f"(default zoom z={ZOOM_LEVEL} unless overridden per dataset)..."
    )
    for spec in TARGET_DATASETS:
        print_dataset_header(spec)
        eff_z = spec.zoom if spec.zoom is not None else ZOOM_LEVEL
        print(f"Tile zoom for scan: z={eff_z}")
        try:
            url, raw = find_first_available_tile(spec, ZOOM_LEVEL)
            print(f"Sample tile URL: {url}")
            print(f"Raw size (bytes): {len(raw)}")
            decoded = mapbox_vector_tile.decode(raw)
            inspect_decoded_tile(decoded)

            if args.json:
                print("\nDecoded JSON:")
                print(json.dumps(decoded, indent=2, default=str)[:20000])
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to inspect {spec.name}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
