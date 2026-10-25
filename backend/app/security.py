from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException, status

from app.config import settings


@dataclass(frozen=True)
class VerifiedUser:
    id: str
    email: str | None = None


async def require_user(authorization: str | None = Header(default=None)) -> VerifiedUser:
    """Validate the bearer token with Supabase Auth; never trust a decoded client token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={
                    "apikey": settings.supabase_publishable_key,
                    "Authorization": f"Bearer {token.strip()}",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Authentication service is temporarily unavailable.") from exc

    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=401,
            detail="Your session is invalid or expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="Could not verify your session.")

    user_data = response.json()
    user_id = user_data.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="The verified session has no user ID.")
    return VerifiedUser(id=user_id, email=user_data.get("email"))
