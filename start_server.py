#!/usr/bin/env python3
"""Start Solar Heating application with JWT authentication support."""

from __future__ import annotations

import os
import sys
import argparse
import signal
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import panel as pn
except ImportError as exc:
    raise ImportError(
        "Panel is required. Install with: pip install panel"
    ) from exc

from jwt_auth import JWTAuthProvider, configure_jwt_auth


def parse_args():
    parser = argparse.ArgumentParser(
        description="Start Solar Heating application with JWT authentication"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SOLAR_PORT", 8003)),
        help="Port to run the server on (default: 8003)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("SOLAR_HOST", "0.0.0.0"),
        help="Host to bind the server to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--jwt-secret",
        type=str,
        default=os.environ.get("JWT_SECRET", "ferry"),
        help="JWT secret key (default: ferry)"
    )
    parser.add_argument(
        "--bypass-auth",
        action="store_true",
        default=os.environ.get("BYPASS_AUTH", "false").lower() == "true",
        help="Bypass authentication for development"
    )
    parser.add_argument(
        "--allowed-roles",
        type=str,
        default=os.environ.get("ALLOWED_ROLES", '["admin", "solar_admin"]'),
        help="JSON list of allowed roles (default: admin, solar_admin)"
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Open browser automatically"
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run in development mode (bypass auth, auto-reload)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("PANEL_WORKERS", 1)),
        help="Number of worker processes (default: 1)"
    )
    return parser.parse_args()


def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    args = parse_args()
    
    import json
    
    try:
        allowed_roles = json.loads(args.allowed_roles)
    except json.JSONDecodeError:
        allowed_roles = ["admin", "solar_admin"]
    
    configure_jwt_auth(
        jwt_secret=args.jwt_secret,
        bypass_auth=args.bypass_auth or args.dev,
        allowed_roles=allowed_roles,
    )
    
    logger.info(f"Starting Solar Heating application...")
    logger.info(f"  Host: {args.host}")
    logger.info(f"  Port: {args.port}")
    logger.info(f"  JWT Secret: {'***' if args.jwt_secret else 'Not set'}")
    logger.info(f"  Bypass Auth: {args.bypass_auth or args.dev}")
    logger.info(f"  Allowed Roles: {allowed_roles}")
    logger.info(f"  Workers: {args.workers}")
    
    from thermal_storage_gui import build_dashboard
    
    dashboard = build_dashboard()
    
    if args.dev:
        logger.info("Development mode: Authentication bypassed")
        logger.info(f"Access the application at: http://localhost:{args.port}")
        pn.serve(
            dashboard,
            port=args.port,
            address=args.host,
            show=args.show,
            autoreload=True,
        )
    else:
        logger.info("Production mode: JWT authentication enabled")
        logger.info(f"Access the application through ferry at: /api/v1/solar/")
        
        server_kwargs = dict(
            port=args.port,
            address=args.host,
            show=args.show,
            timeout=300,
            keep_alive=60000,
            check_unused_sessions=30000,
            unused_session_lifetime=30000,
            num_procs=args.workers,
            websocket_max_message_size=20 * 1024 * 1024,
            session_token_expiration=3600,
            autoreload=False,
            title="Solar Heating",
        )
        
        allowed_ws_origins = os.environ.get("ALLOWED_WEBSOCKET_ORIGINS", "") or os.environ.get("BOKEH_ALLOW_WS_ORIGIN", "")
        if allowed_ws_origins:
            origins = [o.strip() for o in allowed_ws_origins.split(",") if o.strip()]
            server_kwargs["allow_websocket_origin"] = origins
            server_kwargs["websocket_origin"] = origins
            logger.info(f"  Allowed WebSocket Origins: {origins}")
        else:
            server_kwargs["allow_websocket_origin"] = ["*"]
            server_kwargs["websocket_origin"] = ["*"]
            logger.info("  Allowed WebSocket Origins: * (all origins)")
        
        pn.serve(dashboard, **server_kwargs)


if __name__ == "__main__":
    main()
