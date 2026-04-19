# -*- coding: utf-8 -*-
"""Tests for canonical server runtime helpers and legacy aliases."""

from types import SimpleNamespace

from src.server_runtime import (
    apply_legacy_server_aliases,
    resolve_legacy_webui_host_port,
    resolve_main_server_host_port,
)


def test_apply_legacy_server_aliases_maps_webui_flags_to_serve_flags() -> None:
    args = SimpleNamespace(
        webui=True,
        webui_only=True,
        serve=False,
        serve_only=False,
    )

    apply_legacy_server_aliases(args, webui_enabled=False)

    assert args.serve is True
    assert args.serve_only is True


def test_apply_legacy_server_aliases_honors_webui_enabled_compat_flag() -> None:
    args = SimpleNamespace(
        webui=False,
        webui_only=False,
        serve=False,
        serve_only=False,
    )

    apply_legacy_server_aliases(args, webui_enabled=True)

    assert args.serve is True
    assert args.serve_only is False


def test_resolve_main_server_host_port_prefers_api_env_then_legacy_webui_env() -> None:
    args = SimpleNamespace(host="0.0.0.0", port=8000)

    host, port = resolve_main_server_host_port(
        args,
        env={
            "API_HOST": "127.0.0.1",
            "API_PORT": "9000",
            "WEBUI_HOST": "legacy-host",
            "WEBUI_PORT": "9100",
        },
    )

    assert host == "127.0.0.1"
    assert port == 9000


def test_resolve_main_server_host_port_keeps_explicit_cli_bind_values() -> None:
    args = SimpleNamespace(host="192.168.1.20", port=8123)

    host, port = resolve_main_server_host_port(
        args,
        env={
            "API_HOST": "127.0.0.1",
            "API_PORT": "9000",
        },
    )

    assert host == "192.168.1.20"
    assert port == 8123


def test_resolve_legacy_webui_host_port_prefers_legacy_env_names() -> None:
    host, port = resolve_legacy_webui_host_port(
        {
            "WEBUI_HOST": "127.0.0.2",
            "WEBUI_PORT": "8001",
            "API_HOST": "127.0.0.3",
            "API_PORT": "8002",
        }
    )

    assert host == "127.0.0.2"
    assert port == 8001
