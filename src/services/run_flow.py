# -*- coding: utf-8 -*-
"""Read-only run-flow contract builder and redaction helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from importlib import import_module
from typing import Any, Dict, List, Optional

RUN_FLOW_SCHEMA_VERSION = "run_flow.v1"
RUN_FLOW_DIAGNOSTICS_ANCHOR = "/api/v1/workbench/diagnostics#run_flow_contract"

FORBIDDEN_SIDE_EFFECTS = [
    "db_write",
    "background_worker",
    "notification",
    "ledger_write",
    "portfolio_write",
    "broker_execution",
    "execution_state_write",
    "external_provider_call",
    "raw_payload_storage",
]

_SAFE_METADATA_KEYS = {
    "status",
    "state",
    "reason",
    "message",
    "summary",
    "source",
    "count",
    "total",
    "observed_rows",
    "method",
    "endpoint",
    "mode",
    "phase",
    "result",
    "validation_status",
    "data_quality_flag",
}
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(authorization|bearer|token|api[_-]?key|apikey|secret|password|passwd|cookie|"
    r"webhook|raw[_-]?prompt|raw[_-]?response|prompt|headers|proxy)"
)
_LOCAL_PATH_RE = re.compile(r"/Users/[^\s,;:'\"<>)]*")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_SENSITIVE_URL_MARKER_RE = re.compile(
    r"(?i)(?:[/?#&]|^)(?:webhook|token|access_token|api[_-]?key|apikey|keys?|secret)(?:[=/?:#&]|$)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^,;{}\[\]\r\n|]+")
_AUTH_ASSIGNMENT_RE = re.compile(r"(?i)\bAuthorization\s*[:=]\s*[^,;{}\[\]\r\n|]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|secret|password|passwd|api[_-]?key|cookie)\s*[:=]\s*[^,;}\]\r\n|]+"
)
_SENSITIVE_FIELD_VALUE_RE = re.compile(
    r"(?i)(['\"]?)"
    r"(authorization|bearer|token|api[_-]?key|apikey|secret|password|passwd|cookie|"
    r"webhook|raw[_-]?prompt|raw[_-]?response|prompt|headers|proxy)"
    r"\1\s*[:=]\s*(?:(['\"])[^'\"]*\3|[^,;{}\[\]\r\n|]+)"
)
_SECRET_WORD_VALUE_RE = re.compile(
    r"(?i)\b(secret|token|password|passwd|api[_-]?key|api\s+key|cookie)"
    r"(?:[-_:\s=]+)[A-Za-z0-9._~+/=-]{4,}"
)


def build_workbench_run_flow_contract() -> Dict[str, Any]:
    """Return the static read-only run-flow contract exposed by diagnostics."""
    return build_run_flow_contract(
        lanes=[
            {
                "id": "diagnostics",
                "label": "Diagnostics contract",
                "status": "available",
                "summary": "Low-sensitive Workbench diagnostics shape.",
            },
            {
                "id": "review",
                "label": "Manual review",
                "status": "manual_review_required",
                "summary": "Operator review remains required before decisions.",
            },
        ],
        nodes=[
            {
                "id": "diagnostics-hub",
                "lane_id": "diagnostics",
                "label": "Workbench diagnostics hub",
                "status": "success",
                "summary": "GET diagnostics composes low-sensitive links and schema metadata.",
                "metadata": {"status": "available", "method": "GET"},
            },
            {
                "id": "run-flow-redaction",
                "lane_id": "diagnostics",
                "label": "Run-flow redaction",
                "status": "success",
                "summary": "Sensitive prompts, headers, tokens, webhooks, and local paths are redacted.",
                "metadata": {"status": "enabled", "mode": "compact"},
            },
            {
                "id": "operator-review",
                "lane_id": "review",
                "label": "Operator review boundary",
                "status": "degraded",
                "summary": "Run-flow output is review context only, not a trade instruction.",
                "metadata": {"status": "manual_review_required"},
            },
        ],
        edges=[
            {
                "source": "diagnostics-hub",
                "target": "run-flow-redaction",
                "relation": "uses",
            },
            {
                "source": "run-flow-redaction",
                "target": "operator-review",
                "relation": "requires_review",
            },
        ],
        events=[
            {
                "id": "contract-attached",
                "node_id": "diagnostics-hub",
                "status": "success",
                "message": "run_flow_contract attached to diagnostics hub",
            }
        ],
    )


def build_run_flow_contract(
    *,
    lanes: Optional[Sequence[Mapping[str, Any]]] = None,
    nodes: Optional[Sequence[Mapping[str, Any]]] = None,
    edges: Optional[Sequence[Mapping[str, Any]]] = None,
    events: Optional[Sequence[Mapping[str, Any]]] = None,
    generated_at: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build a read-only low-sensitive run-flow contract dictionary."""
    snapshot = build_run_flow_snapshot(
        lanes=lanes or [],
        nodes=nodes or [],
        edges=edges or [],
        events=events or [],
        generated_at=generated_at,
    )
    return {
        "mode": "read_only_run_flow_contract",
        "read_only": True,
        "is_trade_instruction": False,
        "manual_review_required": True,
        "side_effects": [],
        "forbidden_side_effects": list(FORBIDDEN_SIDE_EFFECTS),
        "schema": {
            "name": "run_flow_snapshot",
            "version": RUN_FLOW_SCHEMA_VERSION,
            "models": ["lane", "node", "edge", "event", "summary", "snapshot"],
            "low_sensitive_only": True,
            "raw_secret_fields": [],
            "raw_payload_fields": [],
            "fields": ["lanes", "nodes", "edges", "events", "summary"],
        },
        "links": {
            "workbench_diagnostics": "/api/v1/workbench/diagnostics",
            "schema": f"{RUN_FLOW_DIAGNOSTICS_ANCHOR}.schema",
            "snapshot": f"{RUN_FLOW_DIAGNOSTICS_ANCHOR}.snapshot",
        },
        "snapshot": snapshot.model_dump(mode="json"),
    }


def build_run_flow_snapshot(
    *,
    lanes: Sequence[Mapping[str, Any]],
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    generated_at: Optional[Any] = None,
) -> Any:
    """Build a typed run-flow snapshot from compact dictionaries."""
    run_nodes = [_node_from_mapping(node) for node in nodes]
    lane_node_ids = _lane_node_ids(run_nodes)
    run_lanes = [_lane_from_mapping(lane, lane_node_ids=lane_node_ids) for lane in lanes]
    run_edges = [_edge_from_mapping(edge) for edge in edges]
    run_events = [_event_from_mapping(event) for event in events]
    summary = _build_summary(run_lanes, run_nodes, run_edges, run_events)
    schemas = _run_flow_schemas()
    return schemas.RunFlowSnapshot(
        schema_version=RUN_FLOW_SCHEMA_VERSION,
        generated_at=_coerce_timestamp(generated_at),
        summary=summary,
        lanes=run_lanes,
        nodes=run_nodes,
        edges=run_edges,
        events=run_events,
    )


def redact_run_flow_value(value: Any, *, max_chars: int = 160) -> Any:
    """Redact a payload while keeping short low-sensitive status metadata."""
    if isinstance(value, Mapping):
        result: Dict[str, str] = {}
        safe_count = 0
        for raw_key, raw_value in value.items():
            raw_key_text = _clean_key(raw_key)
            if not raw_key_text:
                continue
            key = _redact_scalar(raw_key_text, max_chars=80)
            if not key:
                continue
            if _is_sensitive_key(raw_key_text):
                result[key] = "[redacted-sensitive]"
                continue
            if key not in _SAFE_METADATA_KEYS:
                continue
            if safe_count >= 8:
                continue
            if _is_structured_value(raw_value):
                result[key] = "[redacted-object]"
                safe_count += 1
                continue
            result[key] = _redact_scalar(raw_value, max_chars=max_chars)
            safe_count += 1
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            "[redacted-object]" if _is_structured_value(item) else _redact_scalar(item, max_chars=max_chars)
            for item in list(value)[:5]
        ]
    return _redact_scalar(value, max_chars=max_chars)


def redact_run_flow_text(value: Any, *, max_chars: int = 160) -> str:
    """Redact common token, webhook, and local-path shapes from short text."""
    return _redact_scalar(value, max_chars=max_chars)


def _lane_from_mapping(raw: Mapping[str, Any], *, lane_node_ids: Mapping[str, List[str]]) -> Any:
    schemas = _run_flow_schemas()
    lane_id = _text(raw.get("id") or raw.get("lane_id") or "lane")
    node_ids = raw.get("node_ids") or lane_node_ids.get(lane_id) or []
    return schemas.RunFlowLane(
        id=lane_id,
        label=_text(raw.get("label") or lane_id),
        status=_status(raw.get("status") or "available"),
        summary=_text(raw.get("summary") or ""),
        node_ids=[_text(node_id) for node_id in node_ids],
    )


def _node_from_mapping(raw: Mapping[str, Any]) -> Any:
    schemas = _run_flow_schemas()
    node_id = _text(raw.get("id") or raw.get("node_id") or "node")
    lane_id = _text(raw.get("lane_id") or "default")
    metadata = raw.get("metadata")
    if metadata is None:
        metadata = raw.get("details")
    redacted_metadata = redact_run_flow_value(metadata or {})
    return schemas.RunFlowNode(
        id=node_id,
        lane_id=lane_id,
        label=_text(raw.get("label") or node_id),
        status=_status(raw.get("status") or "unknown"),
        summary=_text(raw.get("summary") or ""),
        metadata=redacted_metadata if isinstance(redacted_metadata, dict) else {},
    )


def _edge_from_mapping(raw: Mapping[str, Any]) -> Any:
    schemas = _run_flow_schemas()
    return schemas.RunFlowEdge(
        source=_text(raw.get("source") or ""),
        target=_text(raw.get("target") or ""),
        relation=_text(raw.get("relation") or "then"),
        status=_status(raw.get("status") or "available"),
    )


def _event_from_mapping(raw: Mapping[str, Any]) -> Any:
    schemas = _run_flow_schemas()
    node_id = raw.get("node_id")
    return schemas.RunFlowEvent(
        id=_text(raw.get("id") or raw.get("event_id") or "event"),
        node_id=_text(node_id) if node_id else None,
        status=_status(raw.get("status") or "info"),
        message=_text(raw.get("message") or raw.get("summary") or ""),
    )


def _build_summary(
    lanes: Sequence[Any],
    nodes: Sequence[Any],
    edges: Sequence[Any],
    events: Sequence[Any],
) -> Any:
    schemas = _run_flow_schemas()
    failed_count = sum(1 for node in nodes if _is_failed_status(node.status))
    degraded_count = sum(1 for node in nodes if _is_degraded_status(node.status))
    if failed_count:
        status = "failed"
    elif degraded_count:
        status = "degraded"
    elif nodes:
        status = "success"
    else:
        status = "empty"
    return schemas.RunFlowSummary(
        status=status,
        lane_count=len(lanes),
        node_count=len(nodes),
        edge_count=len(edges),
        event_count=len(events),
        degraded_node_count=degraded_count,
        failed_node_count=failed_count,
        read_only=True,
        is_trade_instruction=False,
        manual_review_required=True,
        side_effects=[],
    )


def _lane_node_ids(nodes: Sequence[Any]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for node in nodes:
        grouped.setdefault(node.lane_id, []).append(node.id)
    return grouped


def _run_flow_schemas() -> Any:
    """Load API schemas lazily so this service can be imported without routers."""
    return import_module("api.v1.schemas.run_flow")


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(key))


def _clean_key(value: Any) -> str:
    return str(value or "").strip()[:80]


def _text(value: Any) -> str:
    return _redact_scalar(value, max_chars=160)


def _status(value: Any) -> str:
    text = _redact_scalar(value, max_chars=60).strip().lower()
    return text or "unknown"


def _redact_scalar(value: Any, *, max_chars: int) -> str:
    if value is None:
        return ""
    if _is_structured_value(value):
        return "[redacted-object]"
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    text = _URL_RE.sub(_redact_url_match, text)
    text = _LOCAL_PATH_RE.sub("[redacted-local-path]", text)
    text = _SENSITIVE_FIELD_VALUE_RE.sub(_redact_sensitive_field_value, text)
    text = _AUTH_ASSIGNMENT_RE.sub("Authorization=[redacted]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _SECRET_WORD_VALUE_RE.sub(_redact_secret_word_value, text)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if len(text) > max_chars:
        return f"{text[:max_chars]}..."
    return text


def _is_structured_value(value: Any) -> bool:
    return isinstance(value, Mapping) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
    )


def _redact_sensitive_field_value(match: re.Match[str]) -> str:
    label = match.group(2).lower().replace(" ", "_")
    return f"{label}=[redacted]"


def _redact_secret_word_value(match: re.Match[str]) -> str:
    label = match.group(1).lower().replace(" ", "_")
    return f"{label}=[redacted]"


def _redact_url_match(match: re.Match[str]) -> str:
    url = match.group(0)
    lowered = url.lower()
    if _SENSITIVE_URL_MARKER_RE.search(lowered) or any(
        marker in lowered
        for marker in [
            "webhook",
            "token",
            "access_token",
            "api_key",
            "apikey",
            "key=",
            "secret",
            "hooks.slack.com",
            "oapi.dingtalk.com",
            "open-apis/bot",
        ]
    ):
        return "[redacted-url]"
    return url


def _coerce_timestamp(value: Optional[Any]) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return _redact_scalar(value, max_chars=80)


def _is_failed_status(status: str) -> bool:
    normalized = str(status or "").lower()
    return normalized in {"failed", "error", "blocked", "block", "unavailable"}


def _is_degraded_status(status: str) -> bool:
    normalized = str(status or "").lower()
    return normalized in {"degraded", "fallback", "warning", "partial", "manual_review_required"}
