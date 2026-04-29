#!/usr/bin/env python3
"""JWT authentication middleware for Solar Heating application."""

from __future__ import annotations

import os
import jwt
import json
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional

try:
    from bokeh.server.auth_provider import AuthProvider
    from tornado import web
    from tornado.httputil import HTTPServerRequest
except ImportError as exc:
    raise ImportError(
        "Bokeh and tornado are required for JWT authentication. "
        "Install with: pip install bokeh tornado"
    ) from exc


class JWTConfig:
    JWT_SECRET: str = os.environ.get("JWT_SECRET", "ferry")
    JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
    TRUSTED_PROXY: bool = os.environ.get("TRUSTED_PROXY", "true").lower() == "true"
    BYPASS_AUTH: bool = os.environ.get("BYPASS_AUTH", "false").lower() == "true"
    ALLOWED_ROLES: list[str] = json.loads(
        os.environ.get("ALLOWED_ROLES", '["admin", "solar_admin"]')
    )


def decode_jwt_token(token: str) -> Optional[dict[str, Any]]:
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        
        payload = jwt.decode(
            token,
            JWTConfig.JWT_SECRET,
            algorithms=[JWTConfig.JWT_ALGORITHM],
            options={"verify_exp": True}
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def extract_user_info(request: HTTPServerRequest) -> dict[str, Any]:
    user_info = {
        "authenticated": False,
        "user_id": None,
        "username": None,
        "role": None,
        "permissions": [],
    }
    
    if JWTConfig.BYPASS_AUTH:
        user_info.update({
            "authenticated": True,
            "user_id": "bypass",
            "username": "bypass_user",
            "role": "admin",
            "permissions": ["*"],
        })
        return user_info
    
    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        payload = decode_jwt_token(auth_header)
        if payload:
            user_info.update({
                "authenticated": True,
                "user_id": payload.get("userId") or payload.get("sub"),
                "username": payload.get("username") or payload.get("user"),
                "role": payload.get("rolekey") or payload.get("role"),
                "permissions": payload.get("permissions", []),
            })
            return user_info
    
    user_id = request.headers.get("X-User-Id")
    username = request.headers.get("X-Username")
    role = request.headers.get("X-Role-Name")
    
    if user_id or username or role:
        user_info.update({
            "authenticated": True,
            "user_id": user_id,
            "username": username,
            "role": role,
        })
    
    return user_info


def check_role_permission(role: Optional[str]) -> bool:
    if JWTConfig.BYPASS_AUTH:
        return True
    
    if not role:
        return False
    
    if "*" in JWTConfig.ALLOWED_ROLES:
        return True
    
    return role in JWTConfig.ALLOWED_ROLES


class JWTAuthProvider(AuthProvider):
    def __init__(self):
        self._login_url = os.environ.get("FERRY_LOGIN_URL", "/login")
        super().__init__()
    
    def get_user(self, request: HTTPServerRequest) -> Optional[dict[str, Any]]:
        if JWTConfig.BYPASS_AUTH:
            return {"authenticated": True, "user_id": "bypass"}
        
        user_info = extract_user_info(request)
        
        if not user_info.get("authenticated"):
            return None
        
        if not check_role_permission(user_info.get("role")):
            return None
        
        return user_info
    
    @property
    def login_url(self) -> str:
        return self._login_url
    
    def get_user_info(self, user: dict[str, Any]) -> dict[str, Any]:
        return user


def require_auth(f: Callable) -> Callable:
    @wraps(f)
    def decorated_function(*args, **kwargs):
        request = None
        for arg in args:
            if hasattr(arg, 'request'):
                request = arg.request
                break
        
        if request is None:
            raise ValueError("Could not find request object")
        
        user_info = extract_user_info(request)
        
        if not user_info.get("authenticated"):
            raise web.HTTPError(401, "Authentication required")
        
        if not check_role_permission(user_info.get("role")):
            raise web.HTTPError(403, "Insufficient permissions")
        
        return f(*args, user_info=user_info, **kwargs)
    
    return decorated_function


def create_auth_middleware():
    def auth_middleware(request: HTTPServerRequest, next_handler: Callable):
        if JWTConfig.BYPASS_AUTH:
            return next_handler()
        
        user_info = extract_user_info(request)
        
        if not user_info.get("authenticated"):
            if request.path.startswith("/static"):
                return next_handler()
            raise web.HTTPError(401, "Authentication required")
        
        if not check_role_permission(user_info.get("role")):
            raise web.HTTPError(403, "Insufficient permissions")
        
        return next_handler()
    
    return auth_middleware


def get_user_from_request(request: HTTPServerRequest) -> dict[str, Any]:
    return extract_user_info(request)


def configure_jwt_auth(
    jwt_secret: str = "ferry",
    jwt_algorithm: str = "HS256",
    trusted_proxy: bool = True,
    bypass_auth: bool = False,
    allowed_roles: Optional[list[str]] = None,
):
    JWTConfig.JWT_SECRET = jwt_secret
    JWTConfig.JWT_ALGORITHM = jwt_algorithm
    JWTConfig.TRUSTED_PROXY = trusted_proxy
    JWTConfig.BYPASS_AUTH = bypass_auth
    if allowed_roles is not None:
        JWTConfig.ALLOWED_ROLES = allowed_roles


if __name__ == "__main__":
    print("JWT Authentication Module for Solar Heating")
    print(f"JWT Secret: {JWTConfig.JWT_SECRET}")
    print(f"JWT Algorithm: {JWTConfig.JWT_ALGORITHM}")
    print(f"Trusted Proxy: {JWTConfig.TRUSTED_PROXY}")
    print(f"Bypass Auth: {JWTConfig.BYPASS_AUTH}")
    print(f"Allowed Roles: {JWTConfig.ALLOWED_ROLES}")
