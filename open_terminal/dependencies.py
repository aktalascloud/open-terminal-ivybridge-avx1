import hmac
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from open_terminal.env import API_KEY, MULTI_USER
from open_terminal.utils.fs import UserFS

if MULTI_USER:
    from open_terminal.utils.user_isolation import resolve_user


bearer_scheme = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    if not API_KEY:
        return
    if not credentials or not hmac.compare_digest(credentials.credentials, API_KEY):
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
