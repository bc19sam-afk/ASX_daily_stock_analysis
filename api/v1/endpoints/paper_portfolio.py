# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_database_manager
from src.storage import DatabaseManager
from src.services.paper_portfolio_service import PaperPortfolioService


router = APIRouter()


class PaperInitRequest(BaseModel):
    force: bool = Field(False, description="是否强制覆盖已有模拟盘")


class PaperApplyRequest(BaseModel):
    results: List[Dict[str, Any]] = Field(default_factory=list, description="AnalysisResult 列表（最小字段即可）")


@router.post("/init-from-current", summary="从当前真实持仓初始化模拟盘")
def init_from_current(
    payload: PaperInitRequest,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    service = PaperPortfolioService(db_manager)
    try:
        return service.init_from_current(force=payload.force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/apply", summary="按分析建议执行模拟盘")
def apply_simulation(
    payload: PaperApplyRequest,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    service = PaperPortfolioService(db_manager)
    try:
        return service.apply_analysis_results(payload.results)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/overview", summary="获取模拟盘概览")
def get_overview(
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    return db_manager.get_paper_portfolio_overview()
