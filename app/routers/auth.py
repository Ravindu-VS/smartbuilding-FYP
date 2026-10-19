"""
Auth Router — JWT token generation for demo mode.
No WSO2 Identity Server required — uses local HS256 JWT signing.
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# JWT configuration (loaded from settings at startup)
_jwt_secret = "smart-building-secret-key-change-in-production"
_jwt_algorithm = "HS256"
_jwt_expiration_minutes = 60

# Demo users (in production, this would be WSO2 IS)
DEMO_USERS = {
    "admin": {"password": "admin123", "role": "admin", "name": "Building Admin"},
    "operator": {"password": "operator123", "role": "operator", "name": "Building Operator"},
    "viewer": {"password": "viewer123", "role": "viewer", "name": "Dashboard Viewer"},
}


def configure_auth(secret_key: str, algorithm: str = "HS256", expiration: int = 60):
    """Configure JWT settings from application config."""
    global _jwt_secret, _jwt_algorithm, _jwt_expiration_minutes
    _jwt_secret = secret_key
    _jwt_algorithm = algorithm
    _jwt_expiration_minutes = expiration


def create_token(username: str, role: str) -> dict:
    """Create a JWT token."""
    try:
        from jose import jwt
    except ImportError:
        # Fallback for environments without python-jose
        import json, base64, hashlib, hmac

        payload = {
            "sub": username,
            "role": role,
            "exp": (datetime.utcnow() + timedelta(minutes=_jwt_expiration_minutes)).isoformat(),
            "iat": datetime.utcnow().isoformat(),
        }
        # Simple base64 encoding (NOT cryptographically secure — demo only)
        token_data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        return {
            "access_token": f"demo.{token_data}",
            "token_type": "bearer",
            "expires_in": _jwt_expiration_minutes * 60,
        }

    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=_jwt_expiration_minutes),
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, _jwt_secret, algorithm=_jwt_algorithm)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": _jwt_expiration_minutes * 60,
    }


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token. Returns payload or None."""
    if not token:
        return None

    # Handle demo tokens
    if token.startswith("demo."):
        return {"sub": "demo_user", "role": "admin"}

    try:
        from jose import jwt, JWTError
        payload = jwt.decode(token, _jwt_secret, algorithms=[_jwt_algorithm])
        return payload
    except ImportError:
        logger.debug("python-jose not installed, accepting token without verification")
        return {"sub": "unverified", "role": "viewer"}
    except Exception:
        return None


async def get_current_user(authorization: Optional[str] = Header(default=None)):
    """
    Dependency to extract and verify the current user from Authorization header.
    For demo mode, allows unauthenticated access.
    """
    if authorization is None:
        # Demo mode: allow unauthenticated access
        return {"sub": "anonymous", "role": "viewer"}

    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    payload = verify_token(parts[1])
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


@router.post("/token",
             summary="Generate JWT token",
             description="Generate a JWT access token for API authentication (demo mode)")
async def generate_token(username: str, password: str):
    """
    Generate a JWT token for the specified user.
    Demo users: admin/admin123, operator/operator123, viewer/viewer123
    """
    user = DEMO_USERS.get(username)
    if user is None or user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token_data = create_token(username, user["role"])
    return token_data


@router.get("/me",
            summary="Get current user",
            description="Get information about the currently authenticated user")
async def get_me(user: dict = Depends(get_current_user)):
    """Get the current authenticated user's information."""
    return {
        "username": user.get("sub", "anonymous"),
        "role": user.get("role", "viewer"),
    }
