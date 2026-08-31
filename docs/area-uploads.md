# Area uploads: CSV & zipped shapefile

`POST /api/custom_areas/upload` creates custom areas from an uploaded CSV or
zipped shapefile, one area per feature. Uploaded areas are ordinary
`custom_areas` rows (`source='custom'`): they are owner-scoped in search,
work with the existing rename/delete endpoints, and are mirrored into `aois`
like drawn areas. Rows from one upload share a generated `upload_batch_id`
(null on drawn areas).

## Design

The AOI architecture plan originally sketched uploads as a new `upload`
source written directly into `aois`. Uploads were implemented as custom areas
instead:

- The existing custom-area CRUD endpoints and frontend list apply unchanged.
- Owner scoping in `search_aois` tests the literal `'custom'` in four places
  (`src/shared/geocoding_helpers.py`); a second user-owned source would have
  to update all four or leak uploaded areas across users.
- The agent, analytics, thumbnail and mosaic paths already handle
  `custom`/`custom-area` and need no new branches.

Costs: two nullable columns on `custom_areas` (migration `e7c1f4a92b58`:
`properties jsonb`, `upload_batch_id uuid`), and geometry stored twice
(GeoJSON in `custom_areas.geometries`, normalized MultiPolygon in the `aois`
mirror), as for drawn areas.

The write is a single transaction: parse and validate the file, insert n
`custom_areas` rows, mirror all n into `aois` with owner links in one
statement (`upsert_custom_aoi(session, area_ids=...)`), commit. The mirror
projects `custom_areas.properties` into `aois.properties`.

## Endpoint

Multipart form, single field `file`, authentication required. The filename
extension selects the parser: `.csv` or `.zip`; anything else returns 415.

```sh
curl -X POST https://…/api/custom_areas/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@my_areas.csv"     # or my_areas.zip
```

Response — no geometries; refetch the paginated list for full rows:

```json
{
  "upload_batch_id": "0d9c1f4e-…",
  "areas": [
    {"id": "7be2c1aa-…", "name": "Upland North"},
    {"id": "91d40f2b-…", "name": "Upland South"}
  ]
}
```

## File contracts

**CSV** — UTF-8 with a header row. Required columns, matched
case-insensitively:

- `name` — non-empty after trimming.
- `geom` — WKT `POLYGON` or `MULTIPOLYGON` in WGS84 lon/lat degrees.
  Coordinates outside ±180/±90 are rejected (catches projected coordinates).

All other columns are stored per row in `properties`, as strings.

```csv
name,geom,region
Upland North,"POLYGON ((30 10, 30 11, 31 11, 31 10, 30 10))",Kivu
```

**Zipped shapefile** — one zip containing the sidecar set (`.shp`, `.shx`,
`.dbf`, `.prj`). The `.prj` is required; without it the upload is rejected.
Any declared CRS is accepted and reprojected to WGS84 with a real coordinate
transform (not a SRID relabel). A `name` attribute is required, matched
case-insensitively (`NAME` works). Geometries must be `Polygon` or
`MultiPolygon`. All other attributes are stored in `properties`, coerced to
JSON: `NaN`/`NaT`/null → `null`, dates and timestamps → ISO-8601 strings,
numbers → numbers, everything else → its string form.

## Limits and errors

Constants in `src/api/services/area_upload.py`:

| Condition | Status | Body |
| --- | --- | --- |
| File over 10 MB (`MAX_UPLOAD_BYTES`) | 413 | `{"detail": "file too large; the limit is 10 MB"}` |
| Over 500 features (`MAX_FEATURES`) | 422 | `{"detail": {"errors": ["too many rows; the limit is 500"]}}` |
| Invalid content | 422 | `{"detail": {"errors": ["row 3: geom is empty", …]}}` |
| Extension not `.csv`/`.zip` | 415 | `{"detail": "unsupported file type; …"}` |
| Missing/invalid bearer token | 401 | standard auth error |

Validation is all-or-nothing: every problem in the file is collected and
returned as row-indexed errors (`row N` for CSV data rows, `feature N` for
shapefile features, counting from 1) and nothing is created.

## Frontend integration

Upload with a progress bar. Upload progress is reported by the browser
against the plain multipart POST; no chunked-upload protocol is involved.
Use axios or XHR — `fetch` cannot report upload progress. Do not set
`Content-Type`; the browser adds the multipart boundary.

```js
const fd = new FormData();
fd.append("file", fileInput.files[0]); // keep the .csv/.zip filename

await axios.post("/api/custom_areas/upload", fd, {
  headers: { Authorization: `Bearer ${token}` },
  onUploadProgress: (e) => setProgress(Math.round((100 * e.loaded) / e.total)),
});
```

Handle the outcomes. On 422, show every entry of `detail.errors` — the file
failed as a whole and nothing was created.

```js
try {
  const { data } = await upload(file);
  // refetch the list; select/zoom via data.areas ids
} catch (err) {
  const res = err.response;
  if (res?.status === 422) showErrors(res.data.detail.errors);
  else if (res?.status === 413 || res?.status === 415) showError(res.data.detail);
  else showError("Upload failed");
}
```

List with pagination. `GET /api/custom_areas` takes `limit` (1–100, default
50) and `offset`, ordered newest first. When another page exists, the
`X-Next-Offset` response header holds the next offset; it is exposed through
CORS. An unparameterized call returns only the first 50 rows — code that
assumed the list returns everything must follow the header.

```js
async function fetchAllAreas() {
  const areas = [];
  let offset = 0;
  while (offset != null) {
    const res = await axios.get("/api/custom_areas", {
      params: { limit: 100, offset },
      headers: { Authorization: `Bearer ${token}` },
    });
    areas.push(...res.data);
    const next = res.headers["x-next-offset"]; // absent on the last page
    offset = next != null ? Number(next) : null;
  }
  return areas;
}
```

Distinguish uploaded from drawn areas by `upload_batch_id`; `properties`
holds the file's extra columns/attributes.

```js
const uploaded = areas.filter((a) => a.upload_batch_id != null);
const byBatch = Map.groupBy(uploaded, (a) => a.upload_batch_id);
```

## Out of scope

- **Delete a whole upload** — straightforward now that the batch id exists;
  add an index on `upload_batch_id` in the same change.
- **GeoJSON / KML** — one more parser in `area_upload.py` returning the same
  `ParsedFeature` list; the write path is format-agnostic.
- **Larger files** — past these caps, switch to presigned-URL upload to
  S3/minio with an async processing job and a status endpoint, rather than
  raising the constants.
- **Owner-scoping registry refactor** — not needed for this design; required
  before any future non-`custom` user-owned source.
