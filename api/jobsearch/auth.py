"""Auth for this service is a single static bearer key held by the Next.js
server — there's only one caller, so there's no ApiUser table to manage (that's
deckard's model, built for many API clients; we don't have that problem).
Per-end-user scoping happens one level down, via `client_identifier` on `User`."""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jobsearch.config import get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_service_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> None:
    settings = get_settings()
    if not settings.api_key:
        return  # ponytail: no key configured means auth is off, for local dev only
    if credentials is None or not hmac.compare_digest(credentials.credentials, settings.api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")


RequireServiceKey = Depends(require_service_key)
