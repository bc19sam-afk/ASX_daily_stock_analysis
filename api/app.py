# -*- coding: utf-8 -*-
"""
===================================
FastAPI 应用工厂模块
===================================

职责：
1. 创建和配置 FastAPI 应用实例
2. 配置 CORS 中间件
3. 注册路由和异常处理器
4. 托管前端静态文件（生产模式）

使用方式：
    from api.app import create_app
    app = create_app()
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api.v1 import api_v1_router
from api.middlewares.error_handler import add_error_handlers
from api.v1.schemas.common import RootResponse, HealthResponse
from src.services.system_config_service import SystemConfigService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Initialize and release shared services for the app lifecycle."""
    app.state.system_config_service = SystemConfigService()
    try:
        yield
    finally:
        if hasattr(app.state, "system_config_service"):
            delattr(app.state, "system_config_service")


def create_app(static_dir: Optional[Path] = None) -> FastAPI:
    """
    创建并配置 FastAPI 应用实例
    
    Args:
        static_dir: 静态文件目录路径（可选，默认为项目根目录下的 static）
        
    Returns:
        配置完成的 FastAPI 应用实例
    """
    # 默认静态文件目录
    if static_dir is None:
        static_dir = Path(__file__).parent.parent / "static"
    
    # 创建 FastAPI 实例
    app = FastAPI(
        title="Daily Stock Analysis API",
        description=(
            "ASX-first 自选股分析系统 API（面向人工决策辅助，不做自动交易）\n\n"
            "## 功能模块\n"
            "- 股票分析：触发 AI 智能分析\n"
            "- 历史记录：查询历史分析报告\n"
            "- 股票数据：获取行情数据\n\n"
            "## 产品定位\n"
            "- 默认按 ASX/AU 交易日历与时区运行\n"
            "- 兼容 AU/US 标的统一报告流程\n"
            "- 重点保证报告口径一致、时间基准清楚、避免误导用户\n\n"
            "## 认证方式\n"
            "支持可选 Bearer Token 认证；生产或公网访问建议开启。"
        ),
        version="1.0.0",
        lifespan=app_lifespan,
    )
    
    # ============================================================
    # CORS 配置
    # ============================================================
    
    default_allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    allowed_origins = list(default_allowed_origins)
    
    # 从环境变量添加额外的允许来源
    extra_origins = os.environ.get("CORS_ORIGINS", "")
    extra_origin_values = []
    if extra_origins:
        extra_origin_values = [
            o.strip()
            for o in extra_origins.split(",")
            if o.strip() and o.strip() != "*"
        ]
        allowed_origins.extend(extra_origin_values)
    
    # 允许所有来源（开发/演示用）
    if os.environ.get("CORS_ALLOW_ALL", "").lower() == "true":
        allowed_origins = ["*"]

    allow_credentials = True
    if allow_credentials and allowed_origins == ["*"]:
        logger.warning(
            "CORS: wildcard origin with credentials is invalid per spec, "
            "falling back to localhost origins"
        )
        loopback_origins = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
        ]
        allowed_origins = list(dict.fromkeys(loopback_origins + extra_origin_values))
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # ============================================================
    # 注册路由
    # ============================================================
    
    app.include_router(api_v1_router)
    add_error_handlers(app)
    
    # ============================================================
    # 根路由和健康检查
    # ============================================================
    
    has_frontend = static_dir.exists() and (static_dir / "index.html").exists()
    
    if has_frontend:
        @app.get("/", include_in_schema=False)
        async def root():
            """根路由 - 返回前端页面"""
            return FileResponse(static_dir / "index.html")
    else:
        @app.get(
            "/",
            response_model=RootResponse,
            tags=["Health"],
            summary="API 根路由",
            description="返回 API 运行状态信息"
        )
        async def root() -> RootResponse:
            """根路由 - API 状态信息"""
            return RootResponse(
                message="Daily Stock Analysis API is running",
                version="1.0.0"
            )
    
    @app.get(
        "/api/health",
        response_model=HealthResponse,
        tags=["Health"],
        summary="健康检查",
        description="用于负载均衡器或监控系统检查服务状态"
    )
    async def health_check() -> HealthResponse:
        """健康检查接口"""
        return HealthResponse(
            status="ok",
            timestamp=datetime.now().isoformat()
        )
    
    # ============================================================
    # 静态文件托管（前端 SPA）
    # ============================================================
    
    if has_frontend:
        # 挂载静态资源目录
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
        
        # SPA 路由回退
        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(request: Request, full_path: str):
            """SPA 路由回退 - 非 API 路由返回 index.html"""
            if full_path.startswith("api/"):
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": "not_found",
                        "message": "API endpoint not found",
                        "detail": None,
                    },
                )
            
            file_path = static_dir / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            
            return FileResponse(static_dir / "index.html")
    
    return app


# 默认应用实例（供 uvicorn 直接使用）
app = create_app()
