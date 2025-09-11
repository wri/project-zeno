import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Dict, Optional
from uuid import UUID

import cachetools
import httpx
import pandas as pd
import structlog
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer
from itsdangerous import TimestampSigner
from langchain_core.load import dumps
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.agents import (
    close_checkpointer_pool,
    fetch_checkpointer,
    fetch_zeno,
    fetch_zeno_anonymous,
    get_checkpointer_pool,
)
from src.api.auth import MACHINE_USER_PREFIX, validate_machine_user_token
from src.api.data_models import (
    CustomAreaOrm,
    DailyUsageOrm,
    RatingOrm,
    ThreadOrm,
    UserOrm,
    UserType,
    WhitelistedUserOrm,
)
from src.api.schemas import (
    ChatRequest,
    CustomAreaCreate,
    CustomAreaModel,
    CustomAreaNameRequest,
    CustomAreaNameResponse,
    GeometryResponse,
    ProfileConfigResponse,
    QuotaModel,
    RatingCreateRequest,
    RatingModel,
    ThreadModel,
    ThreadNameOutput,
    ThreadStateResponse,
    UserModel,
    UserProfileUpdateRequest,
    UserWithQuotaModel,
)
from src.user_profile_configs.sectors import SECTOR_ROLES, SECTORS
from src.utils.config import APISettings
from src.utils.database import (
    close_global_pool,
    get_session_from_pool_dependency,
    initialize_global_pool,
)
from src.utils.env_loader import load_environment_variables
from src.utils.geocoding_helpers import (
    GADM_SUBTYPE_MAP,
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
    get_geometry_data,
)
from src.utils.llms import SMALL_MODEL, get_model, get_small_model
from src.utils.logging_config import bind_request_logging_context, get_logger

# Load environment variables using shared utility
load_environment_variables()

logger = get_logger(__name__)

# Constants for NextJS frontend integration
NEXTJS_API_KEY_HEADER = "X-API-KEY"
NEXTJS_IP_HEADER = "X-ZENO-FORWARDED-FOR"
ANONYMOUS_USER_PREFIX = "noauth"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize global database connection pool for API and tools
    await initialize_global_pool()

    # Initialize separate checkpointer connection pool
    # (Required due to asyncpg vs psycopg driver compatibility)
    await get_checkpointer_pool()

    yield

    # Cleanup on shutdown
    await close_global_pool()

    # Close checkpointer pool
    await close_checkpointer_pool()


app = FastAPI(
    lifespan=lifespan,
    title="Zeno API",
    description="API for Zeno LangGraph-based agent workflow",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add HTTP Bearer security scheme
security = HTTPBearer(auto_error=False)


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    """Middleware to log requests and bind request ID to context."""
    req_id = uuid.uuid4().hex

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=req_id,
    )

    # Log request start
    logger.info(
        "Request started",
        method=request.method,
        url=str(request.url),
        request_id=req_id,
    )
    response_code = None

    response = None

    # Call the next middleware or endpoint
    try:
        response: Response = await call_next(request)
        response_code = response.status_code
    except Exception as e:
        logger.exception(
            "Request failed with error",
            method=request.method,
            url=str(request.url),
            error=str(e),
            request_id=req_id,
        )

        response_code = 500
        raise e

    finally:
        if not response:
            response = Response(
                content="Internal Server Error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Log request end
        logger.info(
            "Response sent",
            method=request.method,
            url=str(request.url),
            status_code=response_code,
            request_id=req_id,
        )
    return response


os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = os.getenv("STAGE", "production")

langfuse = Langfuse()
langfuse_handler = CallbackHandler(update_trace=True)
langfuse_client = Langfuse()

# HTTP Middleware to asign/verify anonymous session IDs
signer = TimestampSigner(os.environ["COOKIE_SIGNER_SECRET_KEY"])


def pack(data):
    return json.dumps(data) + "\n"


async def replay_chat(thread_id):
    """
    Fetches an existing thread from Zeno checkpointer (persistent
    memory), and streams the content from each checkpoint, in a
    way that is as close as possible to how the /chat endpoint
    streams updates. Each checkpoint represents a transition from
    one node to the next in the graph's execution, so for each
    checkpoint we will track which elements have already been
    rendered, so as to only include new or updated elements in
    the stream response. Additional, each streamed update will
    contain a thread_id and a checkpoint_id.

    Args:
        thread_id (str): The ID of the thread to replay.
    Returns:
        AsyncGenerator[str, None]: A stream of updates for the specified
        thread. Each update includes the following keys:
            - node : the type of node (e.g. user, system)
            - timestamp : the time at which the update was created
            - update : the actual update content
            - checkpoint_id : the ID of the checkpoint
            - thread_id : the ID of the thread
    """

    config = {"configurable": {"thread_id": thread_id}}

    try:
        zeno_async = await fetch_zeno()

        # Fetch checkpoints for conversation/thread
        # consume checkpoints and sort them by step to process from
        # oldest to newest. Skip step -1 which is the initial empty state
        checkpoints = [
            c async for c in zeno_async.aget_state_history(config=config)
        ]
        checkpoints = sorted(
            list(checkpoints), key=lambda x: x.metadata["step"]
        )
        checkpoints = [c for c in checkpoints if c.metadata["step"] >= 0]

        # Track rendered state elements and messages.
        # We want to just render the diff of the state from one checkpoint to
        # the next (in order to maintain the correct ordering of messages and
        # state updates)
        rendered_state_elements = {"messages": []}

        for checkpoint in checkpoints:
            update = {"messages": []}

            for message in checkpoint.values.get("messages", []):
                # Assert that message has content, and hasn't already been rendered
                if (
                    message.id in rendered_state_elements["messages"]
                    or not message.content
                ):
                    continue
                rendered_state_elements["messages"].append(message.id)

                # TODO: add checkpoint timestamp to message?
                update["messages"].append(message)

            # Render the rest of the state updates
            for key, value in checkpoint.values.items():
                if key == "messages":
                    continue  # Skip messages, already handled above

                # Skip if this state element has already been rendered
                if value in rendered_state_elements.setdefault(key, []):
                    continue
                rendered_state_elements[key].append(value)

                update[key] = value

            mtypes = set(m.type for m in update["messages"])

            node_type = (
                "agent"
                if mtypes == {"ai"} or len(mtypes) > 1
                else "tools"
                if mtypes == {"tool"}
                else "human"
            )

            update = {
                "node": node_type,
                "timestamp": checkpoint.created_at,
                "update": dumps(update),
                "checkpoint_id": checkpoint.config["configurable"][
                    "checkpoint_id"
                ],
                "thread_id": checkpoint.config["configurable"]["thread_id"],
            }

            yield pack(update)

    except Exception as e:
        # TODO: yield a stream event with the error?
        logger.exception("Error during chat replay: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


async def stream_chat(
    query: str,
    user_persona: Optional[str] = None,
    ui_context: Optional[dict] = None,
    ui_action_only: Optional[bool] = False,
    thread_id: Optional[str] = None,
    langfuse_metadata: Optional[Dict] = {},
    user: Optional[dict] = None,
):
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [langfuse_handler],
        "metadata": langfuse_metadata,
    }

    if not thread_id:
        zeno_async = await fetch_zeno_anonymous(user)
    else:
        zeno_async = await fetch_zeno(user)

    messages = []
    ui_action_message = []
    state_updates = {}

    if ui_context:
        for action_type, action_data in ui_context.items():
            match action_type:
                case "aoi_selected":
                    content = f"User selected AOI in UI: {action_data['aoi_name']}\n\n"
                    state_updates["aoi"] = action_data["aoi"]
                    state_updates["aoi_name"] = action_data["aoi_name"]
                    state_updates["subregion_aois"] = action_data[
                        "subregion_aois"
                    ]
                    state_updates["subregion"] = action_data["subregion"]
                    state_updates["subtype"] = action_data["subtype"]
                case "dataset_selected":
                    content = f"User selected dataset in UI: {action_data['dataset']['dataset_name']}\n\n"
                    state_updates["dataset"] = action_data["dataset"]
                case "daterange_selected":
                    content = f"User selected daterange in UI: start_date: {action_data['start_date']}, end_date: {action_data['end_date']}"
                    state_updates["start_date"] = action_data["start_date"]
                    state_updates["end_date"] = action_data["end_date"]
                case _:
                    content = f"User performed action in UI: {action_type}\n\n"
            ui_action_message.append(content)

    ui_message = HumanMessage(content="\n".join(ui_action_message))
    messages.append(ui_message)

    if not ui_action_only and query:
        messages.append(HumanMessage(content=query))
    else:
        # UI action only, no query, agent should acknowledge the UI updates & ask what's next
        messages.append(
            HumanMessage(
                content="User performed UI action only. Acknowledge the updates and ask what they would like to do next with their selections."
            )
        )

    state_updates["messages"] = messages
    state_updates["user_persona"] = user_persona

    try:
        stream = zeno_async.astream(
            state_updates,
            config=config,
            stream_mode="updates",
            subgraphs=False,
        )

        async for update in stream:
            try:
                node = next(iter(update.keys()))

                yield pack(
                    {
                        "node": node,
                        "update": dumps(update[node]),
                    }
                )
            except Exception as e:
                logger.exception(
                    "Error processing stream update",
                    error=str(e),
                    update=update,
                )
                # Send error as a stream event instead of raising
                yield pack(
                    {
                        "node": "error",
                        "update": dumps(
                            {
                                "error": True,
                                "message": str(
                                    e
                                ),  # String representation of the error
                                "error_type": type(
                                    e
                                ).__name__,  # Exception class name
                                "type": "stream_processing_error",
                            }
                        ),
                    }
                )
                # Continue processing other updates if possible
                continue

        # Send trace ID after stream completes
        trace_id = getattr(langfuse_handler, "last_trace_id", None)
        if trace_id:
            yield pack(
                {
                    "node": "trace_info",
                    "update": dumps({"trace_id": trace_id}),
                }
            )

    except Exception as e:
        logger.exception("Error during chat streaming: %s", e)
        # Initial stream setup error - send as error event
        yield pack(
            {
                "node": "error",
                "update": dumps(
                    {
                        "error": True,
                        "message": str(
                            e
                        ),  # String representation of the error
                        "error_type": type(e).__name__,  # Exception class name
                        "type": "stream_initialization_error",
                        "fatal": True,  # Indicates stream cannot continue
                    }
                ),
            }
        )


# LRU cache for user info, keyed by token
_user_info_cache = cachetools.TTLCache(maxsize=1024, ttl=60 * 60 * 24)  # 1 day


async def is_user_whitelisted(user_email: str, session: AsyncSession) -> bool:
    """
    Check if user is whitelisted via email or domain.
    Returns True if user is in email whitelist or domain whitelist.
    """
    user_email_lower = user_email.lower()
    user_domain = user_email_lower.split("@")[-1]

    # Check email whitelist first
    stmt = select(WhitelistedUserOrm).filter_by(email=user_email_lower)
    result = await session.execute(stmt)
    if result.scalars().first():
        return True

    # Check domain whitelist
    domains_allowlist = APISettings.domains_allowlist
    normalized_domains = [domain.lower() for domain in domains_allowlist]
    return user_domain in normalized_domains


async def is_public_signup_open(session: AsyncSession) -> bool:
    """
    Check if public signups are currently open.
    Returns True if public signups are enabled and under user limit.
    """
    # Check if public signups are disabled
    if not APISettings.allow_public_signups:
        return False

    # Check signup limits
    max_signups = APISettings.max_user_signups
    if max_signups < 0:  # Unlimited
        return True

    # Count existing users
    stmt = select(func.count(UserOrm.id))
    result = await session.execute(stmt)
    current_user_count = result.scalar()

    return current_user_count < max_signups


async def check_signup_limit_allows_new_user(
    user_email: str, session: AsyncSession
) -> bool:
    """
    Check if signup limits allow a new user to be created.
    Only applies to non-whitelisted users when public signups are enabled.
    Returns True if user can sign up, False if blocked by limits.
    """
    # Whitelisted users always bypass limits
    if await is_user_whitelisted(user_email, session):
        return True

    # For non-whitelisted users, check if public signups are open
    return await is_public_signup_open(session)


async def fetch_user_from_rw_api(
    request: Request,
    authorization: Optional[str] = Depends(security),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> UserModel:
    if not authorization:
        return None

    token = authorization.credentials

    # Handle machine user tokens with zeno-key prefix
    if token and token.startswith(f"{MACHINE_USER_PREFIX}:"):
        return await validate_machine_user_token(token, session)

    # Handle anonymous users with noauth prefix
    if token and token.startswith(f"{ANONYMOUS_USER_PREFIX}:"):
        # Validate anonymous user requirements early
        # Check for required NextJS headers
        if request.headers.get(NEXTJS_API_KEY_HEADER) is None or (
            request.headers[NEXTJS_API_KEY_HEADER]
            != APISettings.nextjs_api_key
        ):
            raise HTTPException(
                status_code=403,
                detail="Invalid API key from NextJS for anonymous user",
            )

        # Check for required IP forwarding header
        anonymous_user_ip = request.headers.get(NEXTJS_IP_HEADER)
        if anonymous_user_ip is None or anonymous_user_ip.strip() == "":
            raise HTTPException(
                status_code=403,
                detail=f"Missing {NEXTJS_IP_HEADER} header for anonymous user",
            )

        return None  # Anonymous users should not be authenticated

    # Check if this looks like a malformed anonymous token
    if token and ":" in token:
        [scheme, _] = token.split(":", 1)
        if scheme.lower() != ANONYMOUS_USER_PREFIX:
            raise HTTPException(
                status_code=401,
                detail=f"Unauthorized, anonymous users should use '{ANONYMOUS_USER_PREFIX}' scheme",
            )

    # return cached user info if available
    if token and token in _user_info_cache:
        return _user_info_cache[token]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.resourcewatch.org/auth/user/me",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=10,
            )
    except Exception as e:
        logger.exception(f"Error contacting Resource Watch: {e}")
        raise HTTPException(
            status_code=502, detail=f"Error contacting Resource Watch: {e}"
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    user_info = resp.json()

    if "name" not in user_info:
        logger.warning(
            "User info does not contain the 'name' field, using email account name as fallback",
            email=user_info.get("email", None),
        )
        user_info["name"] = user_info["email"].split("@")[0]

    user_email = user_info["email"]

    if (
        not await is_user_whitelisted(user_email, session)
        and not APISettings.allow_public_signups
    ):
        # Only block if user is NOT whitelisted AND public signups are disabled
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not allowed to access this API",
        )

    # Allow access (either whitelisted or public signups enabled)
    user_model = UserModel.model_validate(user_info)
    _user_info_cache[token] = user_model
    return user_model


async def require_auth(
    user_info: UserModel = Depends(fetch_user_from_rw_api),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> UserModel:
    """
    Requires Authorization - raises HTTPException if not authenticated
    """
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token in Authorization header",
        )

    stmt = select(UserOrm).filter_by(id=user_info.id)
    result = await session.execute(stmt)
    user = result.scalars().first()
    if not user:
        # Check signup limits for new users
        if not await check_signup_limit_allows_new_user(
            user_info.email, session
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User signups are currently closed",
            )
        user = UserOrm(**user_info.model_dump())
        session.add(user)
        await session.commit()
    # Bind user info to request context for logging
    bind_request_logging_context(user_id=user.id)
    return UserModel(
        id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at,
        updated_at=user.updated_at,
        user_type=user.user_type,
        # Profile fields
        first_name=user.first_name,
        last_name=user.last_name,
        profile_description=user.profile_description,
        sector_code=user.sector_code,
        role_code=user.role_code,
        job_title=user.job_title,
        company_organization=user.company_organization,
        country_code=user.country_code,
        preferred_language_code=user.preferred_language_code,
        gis_expertise_level=user.gis_expertise_level,
        areas_of_interest=user.areas_of_interest,
        has_profile=user.has_profile,
    )


async def optional_auth(
    user_info: UserModel = Depends(fetch_user_from_rw_api),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> Optional[UserModel]:
    """
    Optional Authorization - returns None if not authenticated,
    or UserModel if authenticated.
    """
    if not user_info:
        return None

    stmt = select(UserOrm).filter_by(id=user_info.id)
    result = await session.execute(stmt)
    user = result.scalars().first()
    if not user:
        # Check signup limits for new users
        if not await check_signup_limit_allows_new_user(
            user_info.email, session
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User signups are currently closed",
            )
        user = UserOrm(**user_info.model_dump())
        session.add(user)
        await session.commit()
        await session.refresh(user)
    # Bind user info to request context for logging
    bind_request_logging_context(user_id=user.id)
    return UserModel(
        id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at,
        updated_at=user.updated_at,
        user_type=user.user_type,
        # Profile fields
        first_name=user.first_name,
        last_name=user.last_name,
        profile_description=user.profile_description,
        sector_code=user.sector_code,
        role_code=user.role_code,
        job_title=user.job_title,
        company_organization=user.company_organization,
        country_code=user.country_code,
        preferred_language_code=user.preferred_language_code,
        gis_expertise_level=user.gis_expertise_level,
        areas_of_interest=user.areas_of_interest,
        has_profile=user.has_profile,
    )


# Keep the old function for backward compatibility during transition
async def fetch_user(
    user_info: UserModel = Depends(fetch_user_from_rw_api),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Deprecated: Use require_auth() or optional_auth() instead
    """
    return await optional_auth(user_info, session)


async def extract_anonymous_session_cookie(request: Request) -> Optional[str]:
    """
    Extract the anonymous session cookie from the request headers.

    Args:
        request (Request): The incoming HTTP request object.

    Returns:
        Optional[str]: The anonymous session ID if found, otherwise None.
    """

    # Extract anonymous session ID from auth header (validation already done in fetch_user_from_rw_api)
    auth_header = request.headers["Authorization"]
    credentials = auth_header.strip("Bearer ")
    [scheme, anonymous_id] = credentials.split(":", 1)
    return f"{ANONYMOUS_USER_PREFIX}:{anonymous_id}"


async def get_user_identity_and_daily_quota(
    request: Request,
    user: Optional[UserModel],
):
    """
    Determine the user's identity string and their daily prompt quota.

    Args:
        request (Request): The incoming HTTP request object.
        user (Optional[UserModel]): The authenticated user model, or None for anonymous.

    Returns:
        Dict: Dictionary containing:
            - "identity": str, user identifier string ("user:<id>" or "anon:<id>")
            - "prompt_quota": int, the daily prompt quota for the user

    Raises:
        HTTPException: If anonymous user is missing or has invalid API key or authorization scheme.
    """
    # 1. Get calling user and set quota
    if not user:
        daily_quota = APISettings.anonymous_user_daily_quota
        identity = await extract_anonymous_session_cookie(request)

    else:
        if user.user_type == UserType.ADMIN:
            daily_quota = APISettings.admin_user_daily_quota
        elif user.user_type == UserType.MACHINE:
            daily_quota = APISettings.machine_user_daily_quota
        else:
            daily_quota = APISettings.regular_user_daily_quota
        identity = f"user:{user.id}"
    return {"identity": identity, "prompt_quota": daily_quota}


async def check_quota(
    request: Request,
    user: Optional[UserModel],
    session: AsyncSession,
):
    """
    Check the current daily usage quota for a user.

    Args:
        request (Request): The incoming HTTP request object.
        user (Optional[UserModel]): The authenticated user model, or None for anonymous.
        session (AsyncSession): Async SQLAlchemy session for database operations.

    Returns:
        Dict: Dictionary including user identity, prompt quota, and prompts used count.

    Notes:
        - If quota checking is disabled in settings, returns an empty dictionary.
        - Does not increment usage count; only retrieves current usage.
    """
    if not APISettings.enable_quota_checking:
        return {}

    # Get user identity and quota
    identity_and_quota = await get_user_identity_and_daily_quota(request, user)

    today = date.today()

    stmt = select(DailyUsageOrm).filter_by(
        id=identity_and_quota["identity"], date=today
    )
    result = await session.execute(stmt)
    daily_usage = result.scalars().first()

    identity_and_quota["prompts_used"] = (
        daily_usage.usage_count if daily_usage else 0
    )
    return identity_and_quota


async def enforce_quota(
    request: Request,
    user: Optional[UserModel],
    session: AsyncSession,
):
    """
    Enforce daily usage quota for users and anonymous clients.

    Args:
        request (Request): The incoming HTTP request object.
        user (Optional[UserModel]): The authenticated user model, or None for anonymous.
        session (AsyncSession): Async SQLAlchemy session for database operations.

    Returns:
        Dict: Updated identity_and_quota dictionary including "prompts_used" count.

    Raises:
        HTTPException: If quota is exceeded or required headers are missing/invalid.
    """
    if not APISettings.enable_quota_checking:
        return {}

    # Get user identity and quota
    identity_and_quota = await get_user_identity_and_daily_quota(request, user)

    anonymous_user_ip = None
    user_is_anonymous = (
        identity_and_quota["identity"].split(":")[0] == ANONYMOUS_USER_PREFIX
    )
    if user_is_anonymous:
        # Extract IP address (validation already done in fetch_user_from_rw_api)
        anonymous_user_ip = request.headers.get(NEXTJS_IP_HEADER)

    today = date.today()

    # Atomically insert or increment usage count for the user for today
    stmt = (
        insert(DailyUsageOrm)
        .values(
            id=identity_and_quota["identity"],
            date=today,
            usage_count=1,
            ip_address=anonymous_user_ip,
        )
        .on_conflict_do_update(
            index_elements=["id", "date"],
            set_={"usage_count": DailyUsageOrm.usage_count + 1},
        )
        .returning(DailyUsageOrm.usage_count)
    )
    result = await session.execute(stmt)
    count = result.scalars().first()
    await session.commit()

    # Enforce the user's daily prompt quota
    if count > identity_and_quota["prompt_quota"]:
        raise HTTPException(
            status_code=429,
            detail=f"Daily free limit of {identity_and_quota['prompt_quota']} exceeded; please try again tomorrow.",
        )

    identity_and_quota["prompts_used"] = count

    # Additional IP-based quota enforcement for anonymous users
    if user_is_anonymous:
        stmt = select(func.sum(DailyUsageOrm.usage_count)).filter_by(
            date=today, ip_address=anonymous_user_ip
        )
        result = await session.execute(stmt)
        ip_count = result.scalar() or 0

        if ip_count > APISettings.ip_address_daily_quota:
            raise HTTPException(
                status_code=429,
                detail=f"Daily free limit of {APISettings.ip_address_daily_quota} exceeded for IP address",
            )

    return identity_and_quota


async def generate_thread_name(query: str) -> str:
    """
    Generate a descriptive name for a chat thread based on the user's query.

    Args:
        query: The user's initial query in the thread

    Returns:
        A concise, descriptive name for the thread
    """
    try:
        prompt = f"Generate a concise, descriptive title (max 50 chars) for a chat conversation that starts with this query:\n{query}\nReturn strictly the title only, no quotes or explanation. Dist usually stands for disturbance."
        response = await SMALL_MODEL.with_structured_output(
            ThreadNameOutput
        ).ainvoke(prompt)
        return response.name
    except Exception as e:
        logger.exception("Error generating thread name: %s", e)
        return "Unnamed Thread"  # Fallback to default name


@app.get("/api/quota", response_model=QuotaModel)
async def get_quota(
    request: Request,
    user: Optional[UserModel] = Depends(optional_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    quota_info = await check_quota(request, user, session)
    return quota_info


@app.post("/api/chat")
async def chat(
    request: Request,
    chat_request: ChatRequest,
    user: Optional[UserModel] = Depends(optional_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Chat endpoint for Zeno with quota tracking.

    Accepts a chat query and returns a streamed response. Tracks quota usage
    and includes quota information in response headers when quota checking is enabled.

    Args:
        request: The chat request containing query, thread_id, etc.
        user (dependency injection): The user, authenticated against the WRI
            API (optional for anonymous users)
        quota_info (dependency injection): The user's quota information, including
            identity, current usage and limits
        session (dependency injection): The database session for the request

    Returns:
        Streamed chat response in NDJSON format

    Response Headers (when quota checking enabled):
        X-Prompts-Used: Current number of prompts used today
        X-Prompts-Quota: Daily prompt limit for this user/session

    Quota Limits:
        - Anonymous users: Lower daily limit
        - Regular users: Standard daily limit
        - Admin users: Higher daily limit

    Errors:
        429: Daily quota exceeded - user must wait until tomorrow

    Note:
        - Each successful call increments the daily quota usage
        - Anonymous users are tracked by session/IP
        - Quota headers are only present when quota checking is enabled
    """

    # Check if anonymous chat is allowed
    if not user and not APISettings.allow_anonymous_chat:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Anonymous chat access is disabled. Please log in to continue.",
        )

    thread_id = None
    thread = None

    if user:
        # For authenticated users, persist threads in database
        bind_request_logging_context(
            thread_id=chat_request.thread_id,
            session_id=chat_request.session_id,
            query=chat_request.query,
        )
        stmt = select(ThreadOrm).filter_by(
            id=chat_request.thread_id, user_id=user.id
        )
        result = await session.execute(stmt)
        thread = result.scalars().first()
        if not thread:
            # Generate thread name from the first query
            thread_name = await generate_thread_name(chat_request.query)
            thread = ThreadOrm(
                id=chat_request.thread_id,
                user_id=user.id,
                agent_id="UniGuana",
                name=thread_name,
            )
            session.add(thread)
            await session.commit()
            await session.refresh(thread)
        thread_id = thread.id
    else:
        # For anonymous users, use the thread_id from request but don't persist
        # This allows conversation continuity within the same session
        thread_id = chat_request.thread_id

    # Populate langfuse metadata
    langfuse_metadata = {}

    identity = None

    if user:
        identity = user.id
    else:
        identity = await extract_anonymous_session_cookie(request)

    # Note: should this be user.email or user.id?
    langfuse_metadata["langfuse_user_id"] = identity

    langfuse_metadata["langfuse_session_id"] = thread_id

    # if we want to store any additional user metadata (
    # if user is logged in) we can add any other key/value
    # pairs (as long as the keys don't begin with `langfuse_*`)
    # eg: langfuse_metadata["job_title"] = user.job_title

    try:
        # Enforce quota and get quota info using the authenticated user
        quota_info = await enforce_quota(request, user, session)

        headers = {}
        if APISettings.enable_quota_checking and quota_info:
            headers["X-Prompts-Used"] = str(quota_info["prompts_used"])
            headers["X-Prompts-Quota"] = str(quota_info["prompt_quota"])

        # Convert user model to dict for prompt context if user is authenticated
        user_dict = None
        if user:
            user_dict = {
                "country_code": user.country_code,
                "preferred_language_code": user.preferred_language_code,
                "areas_of_interest": user.areas_of_interest,
            }
            # Add sector and role information if available
            if user.sector_code and user.sector_code in SECTORS:
                user_dict["sector_code"] = SECTORS[user.sector_code]
                if user.role_code and user.role_code in SECTOR_ROLES.get(
                    user.sector_code, {}
                ):
                    user_dict["role_code"] = SECTOR_ROLES[user.sector_code][
                        user.role_code
                    ]

        return StreamingResponse(
            stream_chat(
                query=chat_request.query,
                user_persona=chat_request.user_persona,
                thread_id=thread_id,
                ui_context=chat_request.ui_context,
                ui_action_only=chat_request.ui_action_only,
                langfuse_metadata=langfuse_metadata,
                user=user_dict,
            ),
            media_type="application/x-ndjson",
            headers=headers if headers else None,
        )
    except HTTPException:
        # Re-raise HTTPExceptions (like 429 quota exceeded) without converting to 500
        raise
    except Exception as e:
        logger.exception(
            "Chat request failed",
            error=str(e),
            error_type=type(e).__name__,
            thread_id=chat_request.thread_id,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/threads", response_model=list[ThreadModel])
async def list_threads(
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    List all threads belonging to the authenticated user.

    **Authentication:** Required - returns only threads owned by the authenticated user

    **Response:** Array of thread objects, each containing:
    - `id`: Thread identifier
    - `name`: Thread display name
    - `is_public`: Boolean indicating if thread is publicly accessible
    - `created_at`, `updated_at`: Timestamps
    - `user_id`, `agent_id`: Associated user and agent
    """
    stmt = select(ThreadOrm).filter_by(user_id=user.id)
    result = await session.execute(stmt)
    threads = result.scalars().all()
    return [ThreadModel.model_validate(thread) for thread in threads]


@app.get("/api/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    user: Optional[UserModel] = Depends(optional_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get thread conversation history - supports both public and private access.

    **Access Control:**
    - **Public threads** (is_public=True): Can be accessed by anyone, no authentication required
    - **Private threads** (is_public=False): Require authentication and ownership

    **Authentication:** Optional - provide Bearer token for private threads

    **Response:** Streaming NDJSON format containing conversation history

    **Error Codes:**
    - 401: Private thread accessed without authentication
    - 404: Thread not found or access denied (private thread accessed by non-owner)
    """

    # First, try to get the thread to check if it exists and if it's public
    stmt = select(ThreadOrm).filter_by(id=thread_id)
    result = await session.execute(stmt)
    thread = result.scalars().first()

    if not thread:
        logger.warning("Thread not found", thread_id=thread_id)
        raise HTTPException(status_code=404, detail="Thread not found")

    # If thread is public, allow access regardless of authentication
    if thread.is_public:
        logger.debug("Accessing public thread", thread_id=thread_id)
    else:
        # For private threads, require authentication and ownership
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Bearer token",
            )

        if thread.user_id != user.id:
            logger.warning(
                "Unauthorized access to private thread",
                thread_id=thread_id,
                user_id=user.id,
                owner_id=thread.user_id,
            )
            raise HTTPException(status_code=404, detail="Thread not found")

        logger.debug(
            "Accessing private thread", thread_id=thread_id, user_id=user.id
        )
    try:
        logger.debug("Replaying thread", thread_id=thread_id)
        return StreamingResponse(
            replay_chat(thread_id=thread_id), media_type="application/x-ndjson"
        )
    except Exception as e:
        logger.exception("Replay failed", thread_id=thread_id)
        raise HTTPException(status_code=500, detail=str(e))


class ThreadUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="The name of the thread")
    is_public: Optional[bool] = Field(
        None,
        description="Whether the thread is publicly accessible. True = anyone can view without auth, False = owner only",
    )


@app.patch("/api/threads/{thread_id}", response_model=ThreadModel)
async def update_thread(
    thread_id: str,
    request: ThreadUpdateRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Update thread properties including name and sharing settings.

    **Authentication:** Required - must be thread owner

    **Request Body:** JSON object with optional fields:
    - `name` (string, optional): Update the thread's display name
    - `is_public` (boolean, optional): Set thread visibility
      - `true`: Makes thread publicly accessible without authentication
      - `false`: Makes thread private (owner access only)

    **Examples:**
    ```javascript
    // Make thread public
    PATCH /api/threads/{thread_id}
    { "is_public": true }

    // Make thread private
    PATCH /api/threads/{thread_id}
    { "is_public": false }

    // Update both name and sharing
    PATCH /api/threads/{thread_id}
    { "name": "My Public Thread", "is_public": true }
    ```

    **Response:** Updated thread object with current `is_public` status

    **Error Codes:**
    - 401: Missing or invalid authentication
    - 404: Thread not found or access denied (not thread owner)
    - 422: Invalid field values (e.g., non-boolean for is_public)
    """
    stmt = select(ThreadOrm).filter_by(user_id=user.id, id=thread_id)
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Only set fields that are provided (not None) to avoid overwriting with NULL
    for key, value in request.model_dump(exclude_none=True).items():
        if value is not None:
            setattr(thread, key, value)
    await session.commit()
    await session.refresh(thread)
    return ThreadModel.model_validate(thread)


@app.get("/api/threads/{thread_id}/state", response_model=ThreadStateResponse)
async def get_thread_state(
    thread_id: str,
    user: Optional[UserModel] = Depends(optional_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get the current agent state for a thread.

    **Access Control:**
    - **Public threads** (is_public=True): Can be accessed by anyone, no authentication required
    - **Private threads** (is_public=False): Require authentication and ownership

    **Authentication:** Optional - provide Bearer token for private threads

    **Response:** JSON object containing:
    - `thread_id`: The thread identifier
    - `state`: Current agent state (AOI, dataset, raw_data, etc.)
    - `next_actions`: Available next actions (if any)
    - `created_at`: State timestamp

    **Error Codes:**
    - 401: Private thread accessed without authentication
    - 404: Thread not found or access denied
    - 500: Error retrieving thread state
    """

    # First, try to get the thread to check if it exists and if it's public
    stmt = select(ThreadOrm).filter_by(id=thread_id)
    result = await session.execute(stmt)
    thread = result.scalars().first()

    if not thread:
        logger.warning("Thread not found", thread_id=thread_id)
        raise HTTPException(status_code=404, detail="Thread not found")

    # If thread is public, allow access regardless of authentication
    if thread.is_public:
        logger.debug("Accessing public thread state", thread_id=thread_id)
    else:
        # For private threads, require authentication and ownership
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Bearer token",
            )

        if thread.user_id != user.id:
            logger.warning(
                "Unauthorized access to private thread state",
                thread_id=thread_id,
                user_id=user.id,
                owner_id=thread.user_id,
            )
            raise HTTPException(status_code=404, detail="Thread not found")

        logger.debug(
            "Accessing private thread state",
            thread_id=thread_id,
            user_id=user.id,
        )

    try:
        # Get the agent and retrieve current state
        zeno_async = await fetch_zeno()
        config = {"configurable": {"thread_id": thread_id}}

        # Get current state
        state = await zeno_async.aget_state(config=config)

        return ThreadStateResponse(
            thread_id=thread_id,
            state=dumps(state.values),
        )

    except Exception as e:
        logger.exception("Error retrieving thread state", thread_id=thread_id)
        raise HTTPException(
            status_code=500, detail=f"Error retrieving thread state: {str(e)}"
        )


@app.post("/api/custom_area_name", response_model=CustomAreaNameResponse)
async def custom_area_name(
    request: CustomAreaNameRequest, user: UserModel = Depends(require_auth)
):
    """
    Generate a neutral geographic name for a GeoJSON FeatureCollection of
    bounding boxes.
    Requires Authorization.
    """
    try:
        prompt = """Name this GeoJSON Features from physical geography.
        Pick name in this order:
        1. Most salient intersecting natural feature (range/peak; desert/plateau/basin; river/lake/watershed; coast/gulf/strait; plain/valley)
        2. If none clear, use a broader natural unit (ecoregion/physiographic province/biome or climate/latitude bands)
        3. If still vague, add a directional qualifier (Northern/Upper/Coastal/etc)
        4. Only if needed, append “near [city/town]” for disambiguation (no countries/states)
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


@app.delete("/api/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    user: UserModel = Depends(require_auth),
    checkpointer: AsyncPostgresSaver = Depends(fetch_checkpointer),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Delete thread permanently.

    **Authentication:** Required - must be thread owner

    **Behavior:**
    - Removes thread from database and conversation history
    - Public threads become inaccessible after deletion
    - Operation cannot be undone

    **Response:** 204 No Content on success

    **Error Codes:**
    - 401: Missing or invalid authentication
    - 404: Thread not found or access denied (not thread owner)
    """

    await checkpointer.adelete_thread(thread_id)
    stmt = select(ThreadOrm).filter_by(user_id=user.id, id=thread_id)
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    await session.delete(thread)
    await session.commit()
    return {"detail": "Thread deleted successfully"}


@app.get("/api/geometry/{source}/{src_id}", response_model=GeometryResponse)
async def get_geometry(
    source: str,
    src_id: str,
    user: UserModel = Depends(require_auth),
):
    """
    Get geometry data by source and source ID.

    Args:
        source: Source type (gadm, kba, landmark, wdpa, custom)
        src_id: Source-specific ID (GID_X for GADM, sitrecid for KBA, UUID for custom areas, etc.)
        user: Authenticated user (required)

    Returns:
        Geometry data with name, subtype, and GeoJSON geometry

    Example:
        GET /api/geometry/gadm/IND.26.2_1
        GET /api/geometry/kba/16595
        GET /api/geometry/custom/123e4567-e89b-12d3-a456-426614174000
    """
    try:
        result = await get_geometry_data(source, src_id)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Geometry not found for source '{source}' with ID {src_id}",
            )

        return GeometryResponse(**result)

    except ValueError as e:
        logger.exception(f"Error fetching geometry for {source}:{src_id}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error fetching geometry for {source}:{src_id}")
        raise HTTPException(status_code=500, detail=str(e))


async def send_rating_to_langfuse(
    trace_id: str, rating: int, comment: str, user_id: str
):
    """
    Send user rating feedback to Langfuse as a score.

    Args:
        trace_id: Langfuse trace ID
        rating: User rating (1 or -1)
        comment: Optional user comment
        user_id: User ID for context
    """
    try:
        langfuse_client.score(
            trace_id=trace_id,
            name="user-feedback",
            value=rating,
            comment=comment,
            data_type="NUMERIC",
        )
        logger.info(
            "Rating sent to Langfuse",
            trace_id=trace_id,
            rating=rating,
            user_id=user_id,
        )
    except Exception as e:
        # Don't fail the rating operation if Langfuse is unavailable
        logger.warning(
            "Failed to send rating to Langfuse",
            trace_id=trace_id,
            rating=rating,
            user_id=user_id,
            error=str(e),
        )


@app.post("/api/threads/{thread_id}/rating", response_model=RatingModel)
async def create_or_update_rating(
    thread_id: str,
    request: RatingCreateRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Create or update a rating for a trace in a thread.

    This endpoint allows authenticated users to provide feedback on AI agent responses
    by rating specific traces within their conversation threads.

    **Authentication**: Requires Bearer token in Authorization header.

    **Path Parameters**:
    - thread_id (str): The unique identifier of the thread containing the trace

    **Request Body**:
    - trace_id (str): The Langfuse trace ID to rate
    - rating (int): Either 1 (thumbs up) or -1 (thumbs down)
    - comment (str, optional): Additional feedback text

    **Behavior**:
    - If a rating already exists for the same user/thread/trace combination, it will be updated
    - If no rating exists, a new one will be created
    - The thread must exist and belong to the authenticated user

    **Response**: Returns the created or updated rating with metadata

    **Error Responses**:
    - 401: Missing or invalid authentication
    - 404: Thread not found or access denied
    - 422: Invalid rating value (must be 1 or -1)
    """
    # Verify if the thread exists and belongs to the user
    stmt = select(ThreadOrm).filter_by(id=thread_id, user_id=user.id)
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        raise HTTPException(
            status_code=404, detail="Thread not found or access denied"
        )

    # Check if the rating already exists (upsert logic)
    stmt = select(RatingOrm).filter_by(
        user_id=user.id, thread_id=thread_id, trace_id=request.trace_id
    )
    result = await session.execute(stmt)
    existing_rating = result.scalars().first()

    if existing_rating:
        # Update existing rating
        existing_rating.rating = request.rating
        existing_rating.comment = request.comment
        existing_rating.updated_at = datetime.now()
        await session.commit()
        await session.refresh(existing_rating)

        logger.info(
            "Rating updated",
            user_id=user.id,
            thread_id=thread_id,
            trace_id=request.trace_id,
            rating=request.rating,
            comment=request.comment,
        )

        # Send rating to Langfuse
        await send_rating_to_langfuse(
            request.trace_id, request.rating, request.comment, user.id
        )

        return RatingModel.model_validate(existing_rating)
    else:
        # Create new rating
        new_rating = RatingOrm(
            id=str(uuid.uuid4()),
            user_id=user.id,
            thread_id=thread_id,
            trace_id=request.trace_id,
            rating=request.rating,
            comment=request.comment,
        )
        session.add(new_rating)
        await session.commit()
        await session.refresh(new_rating)

        logger.info(
            "Rating created",
            user_id=user.id,
            thread_id=thread_id,
            trace_id=request.trace_id,
            rating=request.rating,
            comment=request.comment,
        )

        # Send rating to Langfuse
        await send_rating_to_langfuse(
            request.trace_id, request.rating, request.comment, user.id
        )

        return RatingModel.model_validate(new_rating)


@app.get("/api/threads/{thread_id}/rating", response_model=list[RatingModel])
async def get_thread_ratings(
    thread_id: str,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get all ratings for traces in a thread.

    This endpoint allows authenticated users to retrieve all ratings they have
    provided for traces within a specific conversation thread.

    **Authentication**: Requires Bearer token in Authorization header.

    **Path Parameters**:
    - thread_id (str): The unique identifier of the thread

    **Behavior**:
    - Returns all ratings created by the authenticated user for the specified thread
    - Returns empty array if no ratings exist for the thread
    - The thread must exist and belong to the authenticated user

    **Response**: Returns an array of ratings with metadata

    **Error Responses**:
    - 401: Missing or invalid authentication
    - 404: Thread not found or access denied
    """
    # Verify if the thread exists and belongs to the user
    stmt = select(ThreadOrm).filter_by(id=thread_id, user_id=user.id)
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        raise HTTPException(
            status_code=404, detail="Thread not found or access denied"
        )

    # Get all ratings for this thread by the user
    stmt = (
        select(RatingOrm)
        .filter_by(user_id=user.id, thread_id=thread_id)
        .order_by(RatingOrm.created_at)
    )
    result = await session.execute(stmt)
    ratings = result.scalars().all()

    logger.info(
        "Thread ratings retrieved",
        user_id=user.id,
        thread_id=thread_id,
        count=len(ratings),
    )

    return [RatingModel.model_validate(rating) for rating in ratings]


@app.get("/api/auth/me", response_model=UserWithQuotaModel)
async def auth_me(
    request: Request,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get current user information with quota usage.

    Requires Authorization: Bearer <JWT>
    Forwards the JWT to Resource Watch API and returns user info
    with current quota usage information.

    Returns:
        UserWithQuotaModel containing:

        **Core User Fields:**
        - id: Unique user identifier
        - name: User's display name (from OAuth, non-editable)
        - email: User's email address (from OAuth, non-editable)
        - userType: User type ("regular" or "admin")
        - createdAt/updatedAt: Timestamps

        **Profile Fields (editable via PATCH /api/auth/profile):**
        - firstName: User's first name (optional)
        - lastName: User's last name (optional, required in registration flow)
        - profileDescription: What they're looking for with Zeno (optional)
        - sectorCode: Work sector code (optional, see /api/profile/config)
        - roleCode: Job role code (optional, depends on sector)
        - jobTitle: Free text job title (optional)
        - companyOrganization: Company/organization name (optional)
        - countryCode: ISO country code (optional, see /api/profile/config)
        - preferredLanguageCode: ISO language code (optional, see /api/profile/config)
        - gisExpertiseLevel: GIS expertise level (optional, see /api/profile/config)
        - areasOfInterest: Free text areas of interest (optional)
        - topics: Selected interest topics (array of strings, see /api/profile/config)
        - receiveNewsEmails: Whether user wants news emails (boolean, defaults to false)
        - helpTestFeatures: Whether user wants to help test features (boolean, defaults to false)
        - hasProfile: Whether the user has completed their profile (boolean, set by frontend)

        **Quota Information:**
        - promptsUsed: Number of prompts used today (null if quota disabled)
        - promptQuota: Daily prompt limit for this user (null if quota disabled)

    Note:
        - Admin users have higher quotas than regular users
        - When quota checking is disabled, quota fields return null
        - Calling this endpoint increments the user's daily quota usage
        - Use GET /api/profile/config to get valid values for dropdown fields
    """
    if not APISettings.enable_quota_checking:
        return {
            **user.model_dump(),
            "prompts_used": None,
            "prompt_quota": None,
        }

    # Get quota info using the authenticated user (not from WRI API)
    quota_info = await check_quota(request, user, session)
    return {**user.model_dump(), **quota_info}


@app.patch("/api/auth/profile", response_model=UserModel)
async def update_user_profile(
    profile_update: UserProfileUpdateRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Update user profile fields.

    Requires Authorization: Bearer <JWT>
    Updates the user's profile information with the provided fields.
    Only provided fields will be updated (partial update).

    **Updatable Fields:**

    **Basic Profile:**
    - firstName: User's first name (string, optional)
    - lastName: User's last name (string, optional, required for registration flow)
    - profileDescription: What they're looking for with Zeno (string, optional)

    **Detailed Profile:**
    - sectorCode: Work sector (string, optional)
      - Valid values: GET /api/profile/config → sectors
      - Examples: "gov", "ngo", "research", "private"
    - roleCode: Job role (string, optional)
      - Valid values depend on selected sector: GET /api/profile/config → sectorRoles[sectorCode]
      - Must be valid for the specified sector
    - jobTitle: Free text job title (string, optional)
    - companyOrganization: Company/organization name (string, optional)
    - countryCode: ISO 3166-1 alpha-2 country code (string, optional)
      - Valid values: GET /api/profile/config → countries
      - Examples: "US", "GB", "CA", "BR"
    - preferredLanguageCode: ISO 639-1 language code (string, optional)
      - Valid values: GET /api/profile/config → languages
      - Examples: "en", "es", "fr", "de"
    - gisExpertiseLevel: GIS expertise level (string, optional)
      - Valid values: GET /api/profile/config → gisExpertiseLevels
      - Examples: "beginner", "intermediate", "advanced", "expert"
    - areasOfInterest: Free text areas of interest (string, optional)
    - topics: Selected interest topics (array of strings, optional)
      - Valid values: GET /api/profile/config → topics
      - Examples: ["restoring_degraded_landscapes", "combating_deforestation"]
    - receiveNewsEmails: Whether user wants to receive news emails (boolean, optional, defaults to false)
    - helpTestFeatures: Whether user wants to help test new features (boolean, optional, defaults to false)
    - hasProfile: Whether the user has completed their profile (boolean, optional, set by frontend)

    **Request Body Example:**
    ```json
    {
      "firstName": "Jane",
      "lastName": "Smith",
      "profileDescription": "I work on forest conservation projects",
      "sectorCode": "ngo",
      "roleCode": "program",
      "jobTitle": "Program Manager",
      "companyOrganization": "Forest Conservation International",
      "countryCode": "US",
      "preferredLanguageCode": "en",
      "gisExpertiseLevel": "intermediate",
      "areasOfInterest": "Deforestation monitoring, Biodiversity conservation",
      "topics": ["combating_deforestation", "protecting_ecosystems"],
      "receiveNewsEmails": true,
      "helpTestFeatures": false,
      "hasProfile": true
    }
    ```

    **Validation:**
    - All dropdown fields are validated against configuration values
    - roleCode must be valid for the specified sectorCode
    - topics must be an array of valid topic codes (see /api/profile/config → topics)
    - Empty/null values are allowed for all fields
    - Invalid codes return 422 Unprocessable Entity

    **Returns:**
        UserModel: Complete updated user information (all fields, not just updated ones)

    **Notes:**
    - Partial updates supported - only send fields you want to change
    - Original core fields (id, name, email) are never modified
    - Use GET /api/profile/config to get all valid dropdown values
    - Users are auto-created on first authenticated request if they don't exist
    - Profile fields are also returned by GET /api/auth/me (no separate GET needed)
    """
    # Get the user from database
    result = await session.execute(
        select(UserOrm).where(UserOrm.id == user.id)
    )
    db_user = result.scalar_one_or_none()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update only provided fields
    update_data = profile_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        # Convert topics list to JSON string for database storage
        if field == "topics" and value is not None:
            value = json.dumps(value)
        setattr(db_user, field, value)

    await session.commit()
    await session.refresh(db_user)

    # Create response data without loading relationships to avoid lazy loading issues
    response_data = {
        "id": db_user.id,
        "name": db_user.name,
        "email": db_user.email,
        "created_at": db_user.created_at,
        "updated_at": db_user.updated_at,
        "user_type": db_user.user_type,
        "threads": [],  # Empty threads list to avoid lazy loading
        "first_name": db_user.first_name,
        "last_name": db_user.last_name,
        "profile_description": db_user.profile_description,
        "sector_code": db_user.sector_code,
        "role_code": db_user.role_code,
        "job_title": db_user.job_title,
        "company_organization": db_user.company_organization,
        "country_code": db_user.country_code,
        "preferred_language_code": db_user.preferred_language_code,
        "gis_expertise_level": db_user.gis_expertise_level,
        "areas_of_interest": db_user.areas_of_interest,
        "topics": json.loads(db_user.topics) if db_user.topics else None,
        "receive_news_emails": db_user.receive_news_emails,
        "help_test_features": db_user.help_test_features,
        "has_profile": db_user.has_profile,
    }

    return UserModel(**response_data)


@app.get("/api/profile/config", response_model=ProfileConfigResponse)
async def get_profile_config():
    """
    Get configuration options for profile dropdowns.

    **No authentication required** - Public endpoint for form configuration.

    Returns all available options for profile dropdown fields to populate
    frontend form dropdowns and validate user input.

    **Response Structure:**
    ```json
    {
      "sectors": {
        "gov": "Government",
        "ngo": "NGO/Non-Profit",
        "research": "Research/Academia",
        "private": "Private Sector",
        ...
      },
      "sectorRoles": {
        "gov": {
          "policy": "Policy Maker",
          "analyst": "Government Analyst",
          ...
        },
        "ngo": {
          "program": "Program Officer",
          "research": "Research Coordinator",
          ...
        },
        ...
      },
      "countries": {
        "US": "United States",
        "GB": "United Kingdom",
        "CA": "Canada",
        ...
      },
      "languages": {
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        ...
      },
      "gisExpertiseLevels": {
        "beginner": "Beginner - New to GIS and Global Forest Watch",
        "intermediate": "Intermediate - Some experience with GIS or Global Forest Watch",
        "advanced": "Advanced - Experienced with GIS and Global Forest Watch tools",
        "expert": "Expert - Extensive experience with GIS analysis and Global Forest Watch"
      },
      "topics": {
        "restoring_degraded_landscapes": "Restoring Degraded Landscapes",
        "combating_deforestation": "Combating Deforestation",
        "responsible_supply_chains": "Responsible Supply Chains",
        ...
      }
    }
    ```

    **Usage:**
    - Use `sectors` keys as valid values for `sectorCode` in profile updates
    - Use `sectorRoles[selectedSectorCode]` keys as valid values for `roleCode`
    - Use `countries` keys (ISO 3166-1 alpha-2) as valid values for `countryCode`
    - Use `languages` keys (ISO 639-1) as valid values for `preferredLanguageCode`
    - Use `gisExpertiseLevels` keys as valid values for `gisExpertiseLevel`
    - Use `topics` keys as valid values in `topics` array for multi-select interests
    - Display values are the human-readable strings for UI

    **Implementation Notes:**
    - Role options are dependent on sector selection
    - Country codes follow ISO 3166-1 alpha-2 standard
    - Language codes follow ISO 639-1 standard
    - All configurations are static and change infrequently
    - Consider caching this response on the frontend

    Returns:
        ProfileConfigResponse: All configuration options for profile forms
    """
    return ProfileConfigResponse()


@app.get("/api/metadata")
async def api_metadata(
    session: AsyncSession = Depends(get_session_from_pool_dependency),
) -> dict:
    """
    Returns API metadata that's helpful for instantiating the frontend.

    Note:
    For `layer_id_mapping`, the keys are the source names (e.g., `gadm`, `kba`,
    etc.) and the values are the corresponding ID columns used in the database.

    The frontend can get these IDs from the vector tile layer and use the
    `/api/geometry/{source}/{src_id}` endpoint to fetch the geometry data.

    The GADM layer needs some special handling:

    The gadm layer uses a composite ID format like `IND.26.2_1` that's derived
    from the GADM hierarchy, so the ID column is just `gadm_id` in the
    database, but on the frontend it will be displayed as `GID_X` where X is
    the GADM level (1-5).

    The frontend will have to check the level of the selected GADM geometry
    and use the corresponding `GID_X` field to get the correct ID for the
    API call.

    For example, if the user selects a GADM level 2 geometry,
    the ID will look something like `IND.26.2_1` and should be available in
    the gid_2 field on the vector tile layer.

    For `is_signup_open`, this indicates whether new public user signups are
    currently allowed. This is based on the ALLOW_PUBLIC_SIGNUPS setting and
    whether the current user count is below the MAX_USER_SIGNUPS limit.
    Whitelisted users (email and domain) can always sign up regardless of this status.

    For `allow_anonymous_chat`, this indicates whether anonymous users can access
    the /api/chat endpoint without authentication. When false, all users must
    authenticate to use the chat functionality.
    """
    # Check if public signups are open
    is_signup_open = await is_public_signup_open(session)

    # Get current model information
    current_model = get_model()
    current_model_name = APISettings.model.lower()
    small_model = get_small_model()
    small_model_name = APISettings.small_model.lower()

    return {
        "version": "0.1.0",
        "layer_id_mapping": {
            key: value["id_column"] for key, value in SOURCE_ID_MAPPING.items()
        },
        "subregion_to_subtype_mapping": SUBREGION_TO_SUBTYPE_MAPPING,
        "gadm_subtype_mapping": GADM_SUBTYPE_MAP,
        "is_signup_open": is_signup_open,
        "allow_anonymous_chat": APISettings.allow_anonymous_chat,
        "model": {
            "current": current_model_name,
            "model_class": current_model.__class__.__name__,
            "small": small_model_name,
            "small_model_class": small_model.__class__.__name__,
        },
    }


@app.post("/api/custom_areas", response_model=CustomAreaModel)
async def create_custom_area(
    area: CustomAreaCreate,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Create a new custom area for the authenticated user."""
    custom_area = CustomAreaOrm(
        user_id=user.id,
        name=area.name,
        geometries=[i.model_dump_json() for i in area.geometries],
    )
    session.add(custom_area)
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


@app.get("/api/custom_areas", response_model=list[CustomAreaModel])
async def list_custom_areas(
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """List all custom areas belonging to the authenticated user."""
    stmt = select(CustomAreaOrm).filter_by(user_id=user.id)
    result = await session.execute(stmt)
    areas = result.scalars().all()
    results = []
    for area in areas:
        area.geometries = [json.loads(i) for i in area.geometries]
        results.append(area)
    return results


@app.get("/api/custom_areas/{area_id}", response_model=CustomAreaModel)
async def get_custom_area(
    area_id: UUID,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Get a specific custom area by ID."""
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


@app.patch("/api/custom_areas/{area_id}", response_model=CustomAreaModel)
async def update_custom_area_name(
    area_id: UUID,
    payload: dict,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Update the name of a custom area."""
    stmt = select(CustomAreaOrm).filter_by(id=area_id, user_id=user.id)
    result = await session.execute(stmt)
    area = result.scalars().first()
    if not area:
        raise HTTPException(status_code=404, detail="Custom area not found")
    area.name = payload["name"]
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


@app.delete("/api/custom_areas/{area_id}", status_code=204)
async def delete_custom_area(
    area_id: UUID,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Delete a custom area."""
    stmt = select(CustomAreaOrm).filter_by(id=area_id, user_id=user.id)
    result = await session.execute(stmt)
    area = result.scalars().first()
    if not area:
        raise HTTPException(status_code=404, detail="Custom area not found")
    await session.delete(area)
    await session.commit()
    return {"detail": f"Area {area_id} deleted successfully"}


@app.get("/api/threads/{thread_id}/{checkpoint_id}/raw_data")
async def get_raw_data(
    thread_id: str,
    checkpoint_id: str,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
    content_type: str = Header(default="text/csv", alias="Content-Type"),
):
    """
    Get insights data for a specific thread and checkpoint. The data returned
    will reflect the state of the `raw_data` key at that point in time,
    meaning that users can download the data for generated insights at
    any point during a multi-turn conversation. The thread_id and
    checkpoint_id will be included in the updates streamed from the
    fetch thread endpoint.

    Note: should we make the checkpoint_id optional? (in this case we would
    return the latest state of the `raw_data` insights when the checkpoint_id
    is not provided).

    **Authentication**: Requires Bearer token in Authorization header.
    **Content-Type**: Accepts an OPTIONAL Content-Type header to specify
        whether the data should be returned as a CSV file response or a
        JSON object.

    **Path Parameters**:
    - thread_id (str): The unique identifier of the thread for which to gather
        insights data

    **Behavior**:
    - Returns insights data in requested format
    - Returns empty CSV/JSON if no insights data exists for the thread
    - The thread must exist and belong to the authenticated user

    **Response**: Returns a CSV file or JSON object with insights data

    **Error Responses**:
    - 401: Missing or invalid authentication
    - 404: Thread not found or access denied
    """

    # Fetch raw data for the specified thread
    stmt = select(ThreadOrm).filter_by(id=thread_id, user_id=user.id)
    result = await session.execute(stmt)
    thread = result.scalars().first()

    if not thread:
        raise HTTPException(
            status_code=404, detail=f"Thread id: {thread_id} not found"
        )

    zeno_async = await fetch_zeno()

    config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
        }
    }

    state = await zeno_async.aget_state(config=config)

    raw_data = state.values.get("raw_data", {})

    # raw data is formatted as:
    # {col1: [year 1, year 2, ...], col2: [year 1, year 2, ...]}

    df = pd.DataFrame(raw_data)

    if "id" in df.columns:
        cols = ["id"] + [c for c in df.columns if c != "id"]
        df = df[cols]

    if content_type == "application/json":
        return df.to_dict()

    if content_type == "text/csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        csv_data = buf.getvalue()
        filename = (
            f"thread_{thread_id}_checkpoint_{checkpoint_id}_raw_data.csv"
        )
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return Response(
            content=csv_data, media_type="text/csv", headers=headers
        )
    else:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported Media Type: {content_type}, must be one of [application/json, text/csv]",
        )
