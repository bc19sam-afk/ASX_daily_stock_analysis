# -*- coding: utf-8 -*-
"""Shared helpers for canonical FastAPI server entrypoints and legacy aliases."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence, Tuple


CANONICAL_API_APP_IMPORT = "api.app:app"


def apply_legacy_server_aliases(args: Any, *, webui_enabled: bool = False) -> Any:
    """Map deprecated WebUI flags onto the canonical serve flags in-place."""
    if getattr(args, "webui", False):
        args.serve = True
    if getattr(args, "webui_only", False):
        args.serve_only = True
    if webui_enabled and not (args.serve or args.serve_only):
        args.serve = True
    return args


def resolve_server_host_port(
    *,
    host: str,
    port: int,
    host_keys: Sequence[str],
    port_keys: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> Tuple[str, int]:
    """Resolve host/port from env only when the current values still match defaults."""
    source_env = env or os.environ
    resolved_host = host
    resolved_port = port

    for key in host_keys:
        candidate = str(source_env.get(key, "")).strip()
        if candidate:
            resolved_host = candidate
            break

    for key in port_keys:
        candidate = str(source_env.get(key, "")).strip()
        if not candidate:
            continue
        try:
            resolved_port = int(candidate)
        except ValueError:
            continue
        break

    return resolved_host, resolved_port


def resolve_main_server_host_port(args: Any, *, env: Mapping[str, str] | None = None) -> Tuple[str, int]:
    """Resolve canonical serve host/port, with API_* first and WEBUI_* kept as legacy fallback."""
    return resolve_server_host_port(
        host=args.host,
        port=args.port,
        host_keys=("API_HOST", "WEBUI_HOST") if args.host == "0.0.0.0" else (),
        port_keys=("API_PORT", "WEBUI_PORT") if args.port == 8000 else (),
        env=env,
    )


def resolve_legacy_webui_host_port(env: Mapping[str, str] | None = None) -> Tuple[str, int]:
    """Resolve the legacy webui.py bind target while preferring legacy variable names first."""
    return resolve_server_host_port(
        host="127.0.0.1",
        port=8000,
        host_keys=("WEBUI_HOST", "API_HOST"),
        port_keys=("WEBUI_PORT", "API_PORT"),
        env=env,
    )
