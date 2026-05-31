# -*- coding: utf-8 -*-
"""Read-only portfolio event facade endpoint."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from api.deps import get_database_manager
from src.services.portfolio_event_service import PortfolioEventFilters, PortfolioEventService
from src.storage import DatabaseManager

router = APIRouter()


@router.get(
    "",
    summary="List portfolio events",
    description="Read-only unified event view for portfolio, import, and paper portfolio activity.",
)
def list_portfolio_events(
    source: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    code: Optional[str] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    filters = PortfolioEventFilters(
        source=source,
        event_type=event_type,
        code=code,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return PortfolioEventService(db_manager).list_events(filters)
