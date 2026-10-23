"""
JWT Authentication Middleware for FastAPI.
Demo mode: local HS256 signing. Production: validates WSO2 IS tokens.
"""
import logging
from typing import Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.routers.auth import verify_token

logger = logging.getLogger(__name__)

# Paths that do not require authentication
PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/token",
}


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that validates JWT tokens on protected endpoints.

    In demo mode, unauthenticated requests are allowed with 'viewer' role.
    Set ENFORCE_AUTH=true in environment to require tokens on all endpoints.
    """

    def __init__(self, app, enforce: bool = False):
        super().__init__(app)
        self.enforce = enforce

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public paths and OPTIONS (CORS preflight)
        if path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for static files
        if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi"):
            return await call_next(request)

        # Extract Authorization header
        auth_header = request.headers.get("Authorization")

        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                payload = verify_token(parts[1])
                if payload:
                    # Attach user info to request state
                    request.state.user = payload
                    return await call_next(request)
                else:
                    if self.enforce:
                        return JSONResponse(
                            status_code=401,
                            content={"detail": "Invalid or expired token"},
                        )

        # No auth header
        if self.enforce:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required. Use /auth/token to get a JWT."},
            )

        # Demo mode: allow unauthenticated access with viewer role
        request.state.user = {"sub": "anonymous", "role": "viewer"}
        return await call_next(request)
