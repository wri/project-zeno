"""Custom areas CRUD endpoints and area naming.

``custom_areas`` holds the drawn GeoJSON list and stays the source of truth.
Every write here also projects the area into the unified ``aois`` and
``user_aois`` tables, in the same transaction, so search cannot fall behind
the CRUD. ``src/api/services/aoi_sync.py`` holds that mirror.
"""

import json
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.llms import SMALL_MODEL
from src.api.auth.dependencies import require_auth
from src.api.data_models import CustomAreaOrm
from src.api.schemas import (
    CustomAreaCreate,
    CustomAreaModel,
    CustomAreaNameRequest,
    CustomAreaNameResponse,
    CustomAreaUploadResponse,
    UploadedAreaSummary,
    UserModel,
)
from src.api.services.aoi_sync import delete_custom_aoi, upsert_custom_aoi
from src.api.services.area_upload import (
    MAX_UPLOAD_BYTES,
    UploadValidationError,
    parse_csv,
)
from src.shared.database import get_session_from_pool_dependency
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/api/custom_area_name", response_model=CustomAreaNameResponse)
async def custom_area_name(
    request: CustomAreaNameRequest, user: UserModel = Depends(require_auth)
):
    """
    Generate a neutral geographic name for a GeoJSON FeatureCollection of
    bounding boxes. Requires authentication.
    """
    try:
        prompt = """Name this GeoJSON Features from physical geography.
        Pick name in this order:
        1. Most salient intersecting natural feature (range/peak; desert/plateau/basin; river/lake/watershed; coast/gulf/strait; plain/valley)
        2. If none clear, use a broader natural unit (ecoregion/physiographic province/biome or climate/latitude bands)
        3. If still vague, add a directional qualifier (Northern/Upper/Coastal/etc)
        4. Only if needed, append "near [city/town]" for disambiguation (no countries/states)
        Exclude all geopolitical terms and demonyms; avoid disputed/historical polities and sovereignty language.
        Prefer widely used, neutral physical names; do not invent obscure terms.
        You may combine up to two natural units with a preposition.
        Return a name only, strictly ≤50 characters.

        Features: {features}
        """
        response = await SMALL_MODEL.with_structured_output(
            CustomAreaNameResponse
        ).ainvoke(prompt.format(features=request.features[0]))
        return {"name": response.name}
    except Exception as e:
        logger.exception("Error generating area name: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/custom_areas", response_model=CustomAreaModel)
async def create_custom_area(
    area: CustomAreaCreate,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Create a new custom area for the authenticated user.

    The response holds the drawn parts as sent. The area is also mirrored into
    ``aois`` with an ``owner`` link in ``user_aois``, which makes it findable
    through ``GET /api/aois``. An area whose parts give no areal geometry is
    stored, but it is not mirrored, so it does not appear in search.
    """
    custom_area = CustomAreaOrm(
        user_id=user.id,
        name=area.name,
        geometries=[i.model_dump_json() for i in area.geometries],
    )
    session.add(custom_area)
    # Flush so that the mirror can read the row, and its generated id, in this
    # same transaction. The custom_areas row and its aois projection then commit
    # together.
    await session.flush()
    await upsert_custom_aoi(session, area_id=custom_area.id)
    await session.commit()
    await session.refresh(custom_area)

    return CustomAreaModel(
        id=custom_area.id,
        user_id=custom_area.user_id,
        name=custom_area.name,
        created_at=custom_area.created_at,
        updated_at=custom_area.updated_at,
        geometries=[json.loads(i) for i in custom_area.geometries],
    )


@router.post(
    "/api/custom_areas/upload", response_model=CustomAreaUploadResponse
)
async def upload_custom_areas(
    file: UploadFile,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Create custom areas from an uploaded file, one per feature.

    Accepts a ``.csv`` file as the multipart field ``file``:

    - Required columns (case-insensitive): ``name``, and ``geom`` holding WKT
      ``POLYGON`` or ``MULTIPOLYGON`` in WGS84 lon/lat degrees.
    - Every other column is stored in the area's ``properties``.
    - Limits: 10 MB (413) and 500 features (422).
    - All-or-nothing: any invalid row fails the whole upload with a 422 whose
      ``detail.errors`` lists each problem by data-row number.

    The created areas share one ``upload_batch_id``. Each is a regular custom
    area: it appears in ``GET /api/custom_areas``, is mirrored into ``aois``,
    and is searchable by its owner through ``GET /api/aois``. The response is
    deliberately light; refetch the paginated list for the full rows.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=415,
            detail="unsupported file type; upload a .csv file",
        )

    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "file too large; the limit is "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
                ),
            )

    try:
        features = await run_in_threadpool(parse_csv, bytes(data))
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors})

    batch_id = uuid4()
    areas = [
        CustomAreaOrm(
            user_id=user.id,
            name=feature.name,
            geometries=[feature.geometry],
            properties=feature.properties,
            upload_batch_id=batch_id,
        )
        for feature in features
    ]
    session.add_all(areas)
    # Flush so that the mirror can read the rows, and their generated ids, in
    # this same transaction. The rows and their aois projection then commit
    # together.
    await session.flush()
    await upsert_custom_aoi(session, area_ids=[area.id for area in areas])
    await session.commit()

    return CustomAreaUploadResponse(
        upload_batch_id=batch_id,
        areas=[
            UploadedAreaSummary(id=area.id, name=area.name) for area in areas
        ],
    )


@router.get("/api/custom_areas", response_model=list[CustomAreaModel])
async def list_custom_areas(
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """List the custom areas belonging to the authenticated user, newest first.

    When more results are available, the next page offset is returned in the
    ``X-Next-Offset`` response header.

    This reads ``custom_areas`` and returns the drawn parts unchanged. It is
    not the search surface; use ``GET /api/aois?source=custom`` for that.
    """
    stmt = (
        select(CustomAreaOrm)
        .filter_by(user_id=user.id)
        .order_by(CustomAreaOrm.created_at.desc(), CustomAreaOrm.id)
        # Fetch one extra row to determine whether more pages exist.
        .limit(limit + 1)
        .offset(offset)
    )
    result = await session.execute(stmt)
    areas = list(result.scalars().all())
    if len(areas) > limit:
        areas = areas[:limit]
        response.headers["X-Next-Offset"] = str(offset + limit)
    results = []
    for area in areas:
        area.geometries = [json.loads(i) for i in area.geometries]
        results.append(area)
    return results


@router.get("/api/custom_areas/{area_id}", response_model=CustomAreaModel)
async def get_custom_area(
    area_id: UUID,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Get a specific custom area by ID.

    This reads ``custom_areas`` and returns the drawn parts unchanged.
    """
    stmt = select(CustomAreaOrm).filter_by(id=area_id, user_id=user.id)
    result = await session.execute(stmt)
    custom_area = result.scalars().first()

    if not custom_area:
        raise HTTPException(status_code=404, detail="Custom area not found")

    return CustomAreaModel(
        id=custom_area.id,
        user_id=custom_area.user_id,
        name=custom_area.name,
        created_at=custom_area.created_at,
        updated_at=custom_area.updated_at,
        geometries=[json.loads(i) for i in custom_area.geometries],
    )


@router.patch("/api/custom_areas/{area_id}", response_model=CustomAreaModel)
async def update_custom_area_name(
    area_id: UUID,
    payload: dict,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Update the name of a custom area.

    The request body is ``{"name": "<new name>"}``. The mirrored ``aois`` row
    is renamed in the same transaction.
    """
    stmt = select(CustomAreaOrm).filter_by(id=area_id, user_id=user.id)
    result = await session.execute(stmt)
    area = result.scalars().first()
    if not area:
        raise HTTPException(status_code=404, detail="Custom area not found")
    area.name = payload["name"]
    await session.flush()
    await upsert_custom_aoi(session, area_id=area.id)
    await session.commit()
    await session.refresh(area)

    return CustomAreaModel(
        id=area.id,
        user_id=area.user_id,
        name=area.name,
        created_at=area.created_at,
        updated_at=area.updated_at,
        geometries=[json.loads(i) for i in area.geometries],
    )


@router.delete("/api/custom_areas/{area_id}", status_code=204)
async def delete_custom_area(
    area_id: UUID,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Delete a custom area.

    The mirrored ``aois`` row is deleted in the same transaction, and the
    ``user_aois`` foreign key cascades, so no owner link survives the area.
    """
    stmt = select(CustomAreaOrm).filter_by(id=area_id, user_id=user.id)
    result = await session.execute(stmt)
    area = result.scalars().first()
    if not area:
        raise HTTPException(status_code=404, detail="Custom area not found")
    await delete_custom_aoi(session, area_id)
    await session.delete(area)
    await session.commit()
    return {"detail": f"Area {area_id} deleted successfully"}
