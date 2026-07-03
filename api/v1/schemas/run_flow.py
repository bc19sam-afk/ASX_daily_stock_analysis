# -*- coding: utf-8 -*-
"""Low-sensitive read-only run-flow contract schemas."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RunFlowLane(BaseModel):
    """A compact run-flow lane for grouping diagnostic nodes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable low-sensitive lane identifier.")
    label: str = Field(..., description="Human-readable lane label.")
    status: str = Field("available", description="Compact lane status.")
    summary: str = Field("", description="Short low-sensitive lane summary.")
    node_ids: List[str] = Field(default_factory=list, description="Node ids in this lane.")


class RunFlowNode(BaseModel):
    """A compact diagnostic node with redacted metadata."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable low-sensitive node identifier.")
    lane_id: str = Field(..., description="Owning lane id.")
    label: str = Field(..., description="Human-readable node label.")
    status: str = Field("unknown", description="success, degraded, failed, or another compact status.")
    summary: str = Field("", description="Short low-sensitive node summary.")
    metadata: Dict[str, str] = Field(default_factory=dict, description="Redacted compact status metadata.")


class RunFlowEdge(BaseModel):
    """A compact relationship between run-flow nodes."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., description="Source node id.")
    target: str = Field(..., description="Target node id.")
    relation: str = Field("then", description="Low-sensitive relationship label.")
    status: str = Field("available", description="Compact edge status.")


class RunFlowEvent(BaseModel):
    """A compact run-flow event suitable for diagnostics display."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable low-sensitive event identifier.")
    node_id: Optional[str] = Field(None, description="Related node id when available.")
    status: str = Field("info", description="Compact event status.")
    message: str = Field("", description="Short redacted event message.")


class RunFlowSummary(BaseModel):
    """Aggregate read-only run-flow counts and boundaries."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., description="Overall compact run-flow status.")
    lane_count: int = Field(0, ge=0, description="Number of lanes.")
    node_count: int = Field(0, ge=0, description="Number of nodes.")
    edge_count: int = Field(0, ge=0, description="Number of edges.")
    event_count: int = Field(0, ge=0, description="Number of events.")
    degraded_node_count: int = Field(0, ge=0, description="Nodes with degraded/fallback status.")
    failed_node_count: int = Field(0, ge=0, description="Nodes with failed/error/block status.")
    read_only: bool = Field(True, description="The contract is read-only.")
    is_trade_instruction: bool = Field(False, description="Run-flow output is not a trade instruction.")
    manual_review_required: bool = Field(True, description="Human review remains required.")
    side_effects: List[str] = Field(default_factory=list, description="Allowed side effects; always empty here.")


class RunFlowSnapshot(BaseModel):
    """Read-only low-sensitive run-flow snapshot."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field("run_flow.v1", description="Run-flow schema version.")
    generated_at: Optional[str] = Field(None, description="UTC timestamp for snapshot construction.")
    summary: RunFlowSummary = Field(..., description="Aggregate summary.")
    lanes: List[RunFlowLane] = Field(default_factory=list, description="Run-flow lanes.")
    nodes: List[RunFlowNode] = Field(default_factory=list, description="Run-flow nodes.")
    edges: List[RunFlowEdge] = Field(default_factory=list, description="Run-flow edges.")
    events: List[RunFlowEvent] = Field(default_factory=list, description="Run-flow events.")
