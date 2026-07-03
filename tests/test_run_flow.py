# -*- coding: utf-8 -*-
"""Read-only run-flow contract tests."""

from __future__ import annotations

import subprocess
import sys

from api.v1.schemas.run_flow import RunFlowSnapshot
from src.services.run_flow import build_run_flow_contract, redact_run_flow_value


def test_run_flow_contract_summarizes_success_degraded_and_failed_nodes():
    contract = build_run_flow_contract(
        lanes=[
            {"id": "collect", "label": "Collect evidence", "summary": "Read-only inputs"},
            {"id": "review", "label": "Review", "summary": "Manual review"},
        ],
        nodes=[
            {
                "id": "price-history",
                "lane_id": "collect",
                "label": "Price history",
                "status": "success",
                "summary": "close-only evidence available",
                "metadata": {"status": "ok", "observed_rows": 12},
            },
            {
                "id": "news-fallback",
                "lane_id": "collect",
                "label": "News fallback",
                "status": "degraded",
                "summary": "provider cache reused",
                "metadata": {"status": "fallback", "reason": "external call disabled"},
            },
            {
                "id": "operator-review",
                "lane_id": "review",
                "label": "Operator review",
                "status": "failed",
                "summary": "validation blocked",
                "metadata": {"status": "blocked", "message": "manual review required"},
            },
        ],
        edges=[
            {"source": "price-history", "target": "news-fallback", "relation": "then"},
            {"source": "news-fallback", "target": "operator-review", "relation": "requires_review"},
        ],
        events=[
            {
                "id": "cache-reused",
                "node_id": "news-fallback",
                "status": "degraded",
                "message": "used local cache observation",
            },
            {
                "id": "review-blocked",
                "node_id": "operator-review",
                "status": "failed",
                "message": "blocked for manual review",
            },
        ],
    )

    assert contract["mode"] == "read_only_run_flow_contract"
    assert contract["read_only"] is True
    assert contract["is_trade_instruction"] is False
    assert contract["manual_review_required"] is True
    assert contract["side_effects"] == []
    assert contract["links"]["workbench_diagnostics"] == "/api/v1/workbench/diagnostics"
    assert contract["schema"]["low_sensitive_only"] is True
    assert contract["schema"]["models"] == ["lane", "node", "edge", "event", "summary", "snapshot"]

    snapshot = RunFlowSnapshot(**contract["snapshot"])
    assert snapshot.summary.status == "failed"
    assert snapshot.summary.lane_count == 2
    assert snapshot.summary.node_count == 3
    assert snapshot.summary.edge_count == 2
    assert snapshot.summary.event_count == 2
    assert snapshot.summary.degraded_node_count == 1
    assert snapshot.summary.failed_node_count == 1
    assert snapshot.summary.read_only is True
    assert snapshot.summary.side_effects == []
    assert [node.status for node in snapshot.nodes] == ["success", "degraded", "failed"]
    assert snapshot.nodes[0].metadata == {"status": "ok", "observed_rows": "12"}
    assert snapshot.nodes[1].metadata == {"status": "fallback", "reason": "external call disabled"}


def test_run_flow_lane_node_ids_are_redacted_when_explicitly_supplied():
    contract = build_run_flow_contract(
        lanes=[
            {
                "id": "collect",
                "label": "Collect evidence",
                "node_ids": [
                    "price-history",
                    (
                        "Authorization: Bearer abc.def.ghi tail123456 "
                        "/Users/mac/private/report.json raw_prompt=hiddenPrompt"
                    ),
                    "Bearer bare.token.value bareTail123456 /Users/mac/private/raw_prompt.txt",
                ],
            }
        ],
        nodes=[
            {
                "id": "price-history",
                "lane_id": "collect",
                "label": "Price history",
                "status": "success",
            }
        ],
    )

    snapshot = RunFlowSnapshot(**contract["snapshot"])
    assert snapshot.lanes[0].node_ids[0] == "price-history"

    serialized = str(snapshot.lanes[0].node_ids)
    assert "abc.def.ghi" not in serialized
    assert "tail123456" not in serialized
    assert "bare.token.value" not in serialized
    assert "bareTail123456" not in serialized
    assert "/Users/mac" not in serialized
    assert "hiddenPrompt" not in serialized


def test_run_flow_redaction_keeps_short_status_but_removes_sensitive_shapes():
    redacted = redact_run_flow_value(
        {
            "status": "failed",
            "reason": (
                "Authorization: Bearer abc.def.ghi tail123456 "
                "from /Users/mac/private/report.json"
            ),
            "message": (
                "fallback saw secret-token-value and token abc123456; "
                "Authorization: Basic dXNlcjpwYXNz; "
                "Authorization: ApiKey key-secret; "
                "cookie: session abc; password: hunter2 extra"
            ),
            "summary": {"raw_prompt": "hidden prompt", "headers": {"Cookie": "session abc"}},
            "source": [{"api_key": "nested-key"}, "safe list text"],
            "state": (
                "{'Cookie': 'session abc', 'password': 'hunter2', 'raw_prompt': 'hidden', "
                "'message': 'Authorization: Bearer abc.def.ghi tail123456'}; "
                "raw_prompt=unquotedPromptPayload; "
                "raw_response=unquotedResponsePayload; "
                "prompt=standalonePromptPayload; "
                "headers=X-Auth-Header; "
                "proxy=http://user:pass@example.test; "
                "webhook=plainWebhookPayload"
            ),
            "Authorization": "Bearer abc.def.ghi",
            "api_key": "sk-test-secret",
            "secret": "hidden",
            "password": "pw",
            "cookie": "session=abc",
            "raw_prompt": "prompt with token=secret",
            "raw_response": "response with secret",
            "prompt": "do not keep raw prompt",
            "headers": {"Cookie": "session=abc", "Authorization": "Bearer abc"},
            "proxy": "http://user:pass@example.test",
            "webhook_url": "https://hooks.slack.com/services/T000/B000/SECRET?token=abc",
            "Authorization: Bearer key.token.value keyTail123456": "sensitive key",
            "raw_prompt=hiddenPromptKey": "sensitive key",
            "safe_extra_that_should_not_be_copied": "large raw object field",
            "count": 3,
        },
        max_chars=500,
    )

    assert redacted["status"] == "failed"
    assert redacted["count"] == "3"
    assert redacted["Authorization"] == "[redacted-sensitive]"
    assert redacted["api_key"] == "[redacted-sensitive]"
    assert redacted["raw_prompt"] == "[redacted-sensitive]"
    assert redacted["headers"] == "[redacted-sensitive]"
    assert redacted["proxy"] == "[redacted-sensitive]"
    assert redacted["webhook_url"] == "[redacted-sensitive]"
    assert "[redacted-local-path]" in redacted["reason"]
    assert "secret-token-value" not in redacted["message"]
    assert "abc123456" not in redacted["message"]
    assert "dXNlcjpwYXNz" not in redacted["message"]
    assert "key-secret" not in redacted["message"]
    assert "session abc" not in redacted["message"]
    assert "hunter2 extra" not in redacted["message"]
    assert "tail123456" not in redacted["reason"]
    assert redacted["summary"] == "[redacted-object]"
    assert redacted["source"] == "[redacted-object]"

    serialized = str(redacted)
    assert "abc.def.ghi" not in serialized
    assert "sk-test-secret" not in serialized
    assert "session=abc" not in serialized
    assert "raw prompt" not in serialized
    assert "hooks.slack.com" not in serialized
    assert "/Users/mac" not in serialized
    assert "large raw object field" not in serialized
    assert "nested-key" not in serialized
    assert "hidden prompt" not in serialized
    assert "Cookie" not in serialized
    assert "hunter2" not in serialized
    assert "tail123456" not in serialized
    assert "unquotedPromptPayload" not in serialized
    assert "unquotedResponsePayload" not in serialized
    assert "standalonePromptPayload" not in serialized
    assert "X-Auth-Header" not in serialized
    assert "user:pass@example.test" not in serialized
    assert "example.test" not in serialized
    assert "plainWebhookPayload" not in serialized
    assert "key.token.value" not in serialized
    assert "keyTail123456" not in serialized
    assert "hiddenPromptKey" not in serialized


def test_run_flow_redaction_removes_key_urls_in_path_segments():
    redacted = redact_run_flow_value(
        {
            "message": (
                "fallback kept status from https://example.test/key/ABC123456789 "
                "and https://example.test/api/key/XYZ987654321"
            ),
        },
        max_chars=500,
    )

    assert redacted["message"].count("[redacted-url]") == 2
    assert "ABC123456789" not in redacted["message"]
    assert "XYZ987654321" not in redacted["message"]
    assert "example.test/key" not in redacted["message"]


def test_run_flow_redaction_removes_plural_key_urls_in_path_segments():
    redacted = redact_run_flow_value(
        {"message": "fallback kept status from https://example.test/keys/ABC123456789"},
        max_chars=500,
    )

    assert redacted["message"] == "fallback kept status from [redacted-url]"
    assert "ABC123456789" not in redacted["message"]
    assert "example.test/keys" not in redacted["message"]


def test_run_flow_service_import_does_not_initialize_api_router_cycle():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from src.services.run_flow import build_run_flow_contract;"
                "print(build_run_flow_contract()['mode'])"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "read_only_run_flow_contract"
