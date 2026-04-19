# -*- coding: utf-8 -*-
"""
===================================
Legacy WebUI 启动脚本
===================================

兼容旧版 `python webui.py` 调用方式。
当前 canonical FastAPI 启动路径仍是 `api.app:app`。

等效命令：
    python main.py --webui-only

Usage:
  python webui.py
  WEBUI_HOST=0.0.0.0 WEBUI_PORT=8000 python webui.py
"""

from __future__ import annotations

import os
import logging

from src.server_runtime import CANONICAL_API_APP_IMPORT, resolve_legacy_webui_host_port

logger = logging.getLogger(__name__)


def main() -> int:
    """
    启动 legacy WebUI 兼容入口
    """
    host, port = resolve_legacy_webui_host_port(os.environ)

    print(f"正在启动 Web 服务: http://{host}:{port}")
    print(f"API 文档: http://{host}:{port}/docs")
    print()

    try:
        import uvicorn
        from src.config import setup_env
        from src.logging_config import setup_logging

        setup_env()
        setup_logging(log_prefix="web_server")

        uvicorn.run(
            CANONICAL_API_APP_IMPORT,
            host=host,
            port=port,
            log_level="info",
        )
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
