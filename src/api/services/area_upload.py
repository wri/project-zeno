"""Parse uploaded area files into features for ``custom_areas`` rows.

An upload creates one custom area per feature, so this module's output is a
list of ``ParsedFeature``: a name, one GeoJSON geometry string ready for the
``custom_areas.geometries`` list, and the remaining attributes as properties.

Validation is all-or-nothing. Every invalid row is collected into one
``UploadValidationError``, indexed by data-row number, and nothing is created.
"""

import csv
import datetime
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Optional, Sequence

import shapely.wkt
from shapely.errors import ShapelyError
from shapely.geometry import mapping

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_FEATURES = 500
# A zip is read in full before the feature cap applies, so the compressed size
# alone does not bound the work. 20x the upload cap leaves room for the sidecar
# files, which compress well, without admitting a gigabyte expansion.
MAX_UNCOMPRESSED_BYTES = 20 * MAX_UPLOAD_BYTES

# csv defaults to a 131072-char field, which one WKT polygon of a few thousand
# vertices exceeds. Raise it to the upload cap, so file size is the only limit.
csv.field_size_limit(MAX_UPLOAD_BYTES)

_AREAL_TYPES = ("Polygon", "MultiPolygon")


@dataclass(frozen=True)
class ParsedFeature:
    name: str
    geometry: str  # GeoJSON string of one Polygon or MultiPolygon.
    properties: Optional[dict]


class UploadValidationError(ValueError):
    """Invalid upload content. ``errors`` holds row-indexed messages."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _require_column(fieldnames: Sequence[str], wanted: str) -> str:
    """Return the one header matching *wanted* case-insensitively."""
    matches = [
        f for f in fieldnames if f is not None and f.strip().lower() == wanted
    ]
    if not matches:
        raise UploadValidationError([f"missing required column: {wanted}"])
    if len(matches) > 1:
        raise UploadValidationError([f"duplicate column: {wanted}"])
    return matches[0]


def _validate_geometry(wkt_value: str):
    """Parse WKT into a non-empty areal WGS84 geometry, or raise ValueError."""
    try:
        geom = shapely.wkt.loads(wkt_value)
    except (ShapelyError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid WKT ({exc})")
    _check_geometry(geom)
    return geom


def _check_geometry(geom) -> None:
    """Require a non-empty areal WGS84 geometry, or raise ValueError."""
    if geom.geom_type not in _AREAL_TYPES:
        raise ValueError(
            f"geometry must be a Polygon or MultiPolygon, got {geom.geom_type}"
        )
    if geom.is_empty:
        raise ValueError("geometry is empty")
    minx, miny, maxx, maxy = geom.bounds
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        raise ValueError(
            "coordinates out of range; geom must be WGS84 lon/lat degrees"
        )


def parse_csv(data: bytes) -> list[ParsedFeature]:
    """Parse a CSV upload.

    Required columns (case-insensitive): ``name``, and ``geom`` holding WKT
    ``POLYGON``/``MULTIPOLYGON`` in WGS84 lon/lat. Every other column goes into
    the feature's properties as a string. Row numbers in errors count data rows
    from 1, excluding the header.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadValidationError(["file is not valid UTF-8"])

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise UploadValidationError(["file is empty"])
    name_col = _require_column(reader.fieldnames, "name")
    geom_col = _require_column(reader.fieldnames, "geom")

    features: list[ParsedFeature] = []
    errors: list[str] = []
    index = 0
    try:
        for index, row in enumerate(reader, start=1):
            if index > MAX_FEATURES:
                errors.append(f"too many rows; the limit is {MAX_FEATURES}")
                break
            name = (row.get(name_col) or "").strip()
            if not name:
                errors.append(f"row {index}: name is empty")
            geom = None
            wkt_value = (row.get(geom_col) or "").strip()
            if not wkt_value:
                errors.append(f"row {index}: geom is empty")
            else:
                try:
                    geom = _validate_geometry(wkt_value)
                except ValueError as exc:
                    errors.append(f"row {index}: {exc}")
            if errors or geom is None:
                continue
            properties = {
                k: v
                for k, v in row.items()
                if k is not None and k not in (name_col, geom_col)
            }
            features.append(
                ParsedFeature(
                    name=name,
                    geometry=json.dumps(mapping(geom)),
                    properties=properties or None,
                )
            )
    except csv.Error as exc:
        # csv.Error is not a ValueError, so an unhandled one would escape the
        # router's UploadValidationError handler as a 500.
        errors.append(f"row {index + 1}: could not read the row ({exc})")

    if errors:
        raise UploadValidationError(errors)
    if not features:
        raise UploadValidationError(["file has no data rows"])
    return features


def _to_jsonable(value):
    """Coerce a shapefile attribute value to a JSON-storable value."""
    import numpy
    import pandas

    if value is None or pandas.isna(value):
        return None
    if isinstance(value, numpy.generic):
        value = value.item()
    if isinstance(value, (pandas.Timestamp, datetime.date)):
        return value.isoformat()
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _check_uncompressed_size(data: bytes) -> None:
    """Reject a zip whose members expand past ``MAX_UNCOMPRESSED_BYTES``.

    This trusts the sizes in the zip's own headers, which a crafted archive can
    understate. GDAL does the real decompression, so bounding it exactly would
    mean decompressing twice; the header check stops an honest oversized file.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise UploadValidationError([f"could not read the zip file: {exc}"])
    if total > MAX_UNCOMPRESSED_BYTES:
        raise UploadValidationError(
            [
                f"zip contents expand to {total // (1024 * 1024)} MB; "
                f"the limit is {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB"
            ]
        )


def parse_shapefile_zip(data: bytes) -> list[ParsedFeature]:
    """Parse a zipped-shapefile upload.

    Required attribute (case-insensitive): ``name``. The zip must include the
    ``.prj``; geometries are reprojected to WGS84 and must be ``Polygon`` or
    ``MultiPolygon``. Every other attribute goes into the feature's
    properties, coerced to JSON. Row numbers in errors count features from 1.
    """
    import geopandas  # Deferred: keeps the API import path light.

    _check_uncompressed_size(data)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "upload.zip")
        with open(path, "wb") as handle:
            handle.write(data)
        try:
            gdf = geopandas.read_file(path)
        except Exception as exc:
            raise UploadValidationError(
                [f"could not read the shapefile: {exc}"]
            )

    if "geometry" not in gdf.columns:
        raise UploadValidationError(["shapefile has no geometry"])
    if gdf.crs is None:
        raise UploadValidationError(
            ["shapefile has no .prj, so the CRS is unknown; include the .prj"]
        )
    if len(gdf) == 0:
        raise UploadValidationError(["shapefile has no features"])
    if len(gdf) > MAX_FEATURES:
        raise UploadValidationError(
            [f"too many features; the limit is {MAX_FEATURES}"]
        )
    try:
        gdf = gdf.to_crs(4326)
    except Exception as exc:
        # A local or engineering CRS, or a transform needing a PROJ grid that
        # is not installed, raises out of pyproj rather than as a ValueError.
        raise UploadValidationError(
            [f"could not reproject the shapefile to WGS84: {exc}"]
        )
    name_col = _require_column(
        [c for c in gdf.columns if c != "geometry"], "name"
    )

    features: list[ParsedFeature] = []
    errors: list[str] = []
    for index, (_, row) in enumerate(gdf.iterrows(), start=1):
        name_value = _to_jsonable(row[name_col])
        name = str(name_value).strip() if name_value is not None else ""
        if not name:
            errors.append(f"feature {index}: name is empty")
        geom = row.geometry
        try:
            if geom is None:
                raise ValueError("geometry is missing")
            _check_geometry(geom)
        except ValueError as exc:
            errors.append(f"feature {index}: {exc}")
            continue
        if errors:
            continue
        properties = {
            col: _to_jsonable(row[col])
            for col in gdf.columns
            if col not in (name_col, "geometry")
        }
        features.append(
            ParsedFeature(
                name=name,
                geometry=json.dumps(mapping(geom)),
                properties=properties or None,
            )
        )

    if errors:
        raise UploadValidationError(errors)
    return features
