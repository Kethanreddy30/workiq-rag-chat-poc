"""
Mock JWT auth for the POC.

HS256 with a shared secret from the environment. This proves the auth
*gate* behavior (missing/invalid/expired token -> 401) works end to end.

It does NOT model a real identity provider. The eventual Work IQ
integration is expected to use delegated, user-context tokens from a real
IdP (e.g. Entra ID), verified via RS256 + JWKS rotation - a different,
later piece of work. Building that here would mock an auth style that
won't match what actually gets integrated, so we're not doing it yet.
"""

import os
import time

import jwt
from fastapi import HTTPException, Request, status

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# Gates the /dev/token endpoint. Sourced from the environment rather than
# hardcoded so a non-dev deployment (accidental or otherwise) can disable
# token minting by simply not setting MOCK_ENV=dev.
MOCK_ENV = os.environ.get("MOCK_ENV", "dev")

if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. Copy .env.example to .env and set a "
        "real secret (see README for the generation command)."
    )


def create_mock_token(subject: str = "mock-user") -> str:
    """Mint a short-lived HS256 token signed with the shared secret.
    Only meant for local/dev testing of this POC's auth gate."""
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + JWT_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected: Bearer <token>",
        )
    return header[len("Bearer "):].strip()


async def require_auth(request: Request) -> dict:
    """FastAPI dependency. Verifies the bearer token and returns its
    claims. Raise 401 on anything wrong - missing header, bad signature,
    expired token - rather than distinguishing reasons in the response
    body (don't leak which check failed to an unauthenticated caller)."""
    token = _extract_bearer_token(request)
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
