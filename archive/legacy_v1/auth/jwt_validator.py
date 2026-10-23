"""
WSO2 API Manager JWT Validator Middleware

This module provides a decorator and functions to validate incoming JWTs
passed by the WSO2 API Manager (usually in the X-JWT-Assertion header or Authorization header).
"""

import jwt
from functools import wraps
from flask import request, jsonify
import logging
import os

logger = logging.getLogger(__name__)

# In a production environment with WSO2, you would dynamically fetch the public key (JWKS)
# from the WSO2 API Manager instance. For the purpose of this implementation, we will mock
# the validation if WSO2_MOCK_AUTH is set to true.

WSO2_MOCK_AUTH = os.getenv("WSO2_MOCK_AUTH", "true").lower() == "true"
WSO2_PUBLIC_KEY = os.getenv("WSO2_PUBLIC_KEY", "mock_key")

def require_wso2_jwt(f):
    """
    Flask decorator to enforce WSO2 JWT validation.
    Checks for the Authorization header or X-JWT-Assertion header.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if WSO2_MOCK_AUTH:
            # Bypass strict signature validation for local testing
            return f(*args, **kwargs)

        # In production WSO2 passes the JWT either as Bearer token or backend JWT
        auth_header = request.headers.get('Authorization', None)
        jwt_assertion = request.headers.get('X-JWT-Assertion', None)

        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        elif jwt_assertion:
            token = jwt_assertion

        if not token:
            logger.warning("Missing JWT token in request")
            return jsonify({"error": "Unauthorized", "message": "Missing JWT token"}), 401

        try:
            # Validate token against WSO2 public key (RS256)
            decoded = jwt.decode(token, WSO2_PUBLIC_KEY, algorithms=["RS256"])
            # You can inject the decoded user context into the Flask request here
            request.wso2_user = decoded
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Unauthorized", "message": "Token expired"}), 401
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid JWT: {e}")
            return jsonify({"error": "Unauthorized", "message": "Invalid token"}), 401

        return f(*args, **kwargs)

    return decorated_function
