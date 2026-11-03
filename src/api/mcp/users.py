from fastmcp.exceptions import ToolError

from src.shared.request_context import current_user_id


def signed_in_user() -> str:
    user_id = current_user_id()
    if not user_id:
        raise ToolError("This is only available to signed in users.")
    return user_id
