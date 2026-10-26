import hmac
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from open_terminal.env import API_KEY, MULTI_USER
from open_terminal.utils.fs import UserFS

if MULTI_USER:
    from open_terminal.utils.user_isolation import resolve_user


bearer_scheme = HTTPBearer(auto_error=False)


def matches_api_key(token: object) -> bool:
    # compare_digest rejects non-ASCII strings; malformed network input is not an error.
    try:
        return isinstance(token, str) and hmac.compare_digest(token.encode("utf-8"), API_KEY.encode("utf-8"))
    except UnicodeEncodeError:
        return False


async def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    if not API_KEY:
        return
    if not credentials or not matches_api_key(credentials.credentials):
        raise HTTPException(status_code=401, detail="Invalid API key")


def get_filesystem(request: Request) -> UserFS:
    """Build a :class:`UserFS` scoped to the requesting user.

    Multi-user mode requires ``X-User-Id`` to select the user's workspace.
    Otherwise returns a plain ``UserFS`` using stdlib.
    """
    if not MULTI_USER:
        return UserFS()
    user_id = request.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-Id is required in multi-user mode")
    username, home = resolve_user(user_id)
    return UserFS(username=username, home=home)
