import pytest

import importlib

from pathlib import Path
from types import SimpleNamespace

from src.analyzer import GeminiAnalyzer
from src.config import Config
from src.gemini_key_manager import GeminiKeyManager


def _load_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str):
    env_path = tmp_path / ".env"
    env_path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    Config.reset_instance()
    try:
        return Config.get_instance()
    finally:
        Config.reset_instance()


def _make_test_analyzer(keys: list[str]) -> GeminiAnalyzer:
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._use_anthropic = False
    analyzer._use_openai = False
    analyzer._anthropic_client = None
    analyzer._openai_client = None
    analyzer._using_fallback = False
    analyzer._current_model_name = "gemini-3-flash-preview"
    analyzer._gemini_key_manager = GeminiKeyManager(keys)
    analyzer._api_key = analyzer._gemini_key_manager.current_key
    analyzer._model = {"api_key": analyzer._api_key}
    analyzer._build_gemini_client = lambda api_key: {"api_key": api_key}
    analyzer._switch_to_fallback_model = lambda: False
    return analyzer


def test_config_uses_legacy_single_gemini_key_when_multi_key_is_missing(tmp_path, monkeypatch):
    config = _load_config(
        tmp_path,
        monkeypatch,
        "STOCK_LIST=BHP.AX\nGEMINI_API_KEY=legacy-key-1234567890\n",
    )

    assert config.gemini_api_key == "legacy-key-1234567890"
    assert config.gemini_api_keys == ["legacy-key-1234567890"]


def test_config_prefers_multi_gemini_keys_over_legacy_single_key(tmp_path, monkeypatch):
    config = _load_config(
        tmp_path,
        monkeypatch,
        (
            "STOCK_LIST=BHP.AX\n"
            "GEMINI_API_KEYS=multi-key-1111111111, multi-key-2222222222\n"
            "GEMINI_API_KEY=legacy-key-1234567890\n"
        ),
    )

    assert config.gemini_api_keys == ["multi-key-1111111111", "multi-key-2222222222"]
    assert config.gemini_api_key == "multi-key-1111111111"


def test_gemini_rotates_to_second_key_on_429(monkeypatch):
    first_key = "first-key-1234567890"
    second_key = "second-key-1234567890"
    analyzer = _make_test_analyzer([first_key, second_key])
    calls: list[str] = []

    monkeypatch.setattr(
        "src.analyzer.get_config",
        lambda: SimpleNamespace(
            gemini_max_retries=2,
            gemini_retry_delay=0.0,
            anthropic_api_key=None,
            openai_api_key=None,
        ),
    )
    monkeypatch.setattr("src.analyzer.time.sleep", lambda *_args, **_kwargs: None)

    def _fake_generate(_prompt: str, _generation_config: dict) -> str:
        calls.append(analyzer._api_key)
        if analyzer._api_key == first_key:
            raise RuntimeError("429 quota exceeded")
        return "ok"

    monkeypatch.setattr(analyzer, "_generate_gemini_content", _fake_generate)

    result = analyzer._call_api_with_retry("prompt", {})

    assert result == "ok"
    assert calls == [first_key, second_key]
    assert analyzer._api_key == second_key


def test_gemini_does_not_rotate_keys_on_permanent_error(monkeypatch):
    first_key = "first-key-1234567890"
    second_key = "second-key-1234567890"
    analyzer = _make_test_analyzer([first_key, second_key])
    calls: list[str] = []

    monkeypatch.setattr(
        "src.analyzer.get_config",
        lambda: SimpleNamespace(
            gemini_max_retries=3,
            gemini_retry_delay=0.0,
            anthropic_api_key=None,
            openai_api_key=None,
        ),
    )

    def _fake_generate(_prompt: str, _generation_config: dict) -> str:
        calls.append(analyzer._api_key)
        raise RuntimeError("400 invalid argument: malformed request")

    monkeypatch.setattr(analyzer, "_generate_gemini_content", _fake_generate)

    with pytest.raises(RuntimeError, match="invalid argument"):
        analyzer._call_api_with_retry("prompt", {})

    assert calls == [first_key]
    assert analyzer._api_key == first_key


def test_gemini_permanent_error_still_uses_existing_provider_fallback(monkeypatch):
    first_key = "first-key-1234567890"
    second_key = "second-key-1234567890"
    analyzer = _make_test_analyzer([first_key, second_key])
    analyzer._anthropic_client = object()
    gemini_calls: list[str] = []
    anthropic_calls: list[str] = []

    monkeypatch.setattr(
        "src.analyzer.get_config",
        lambda: SimpleNamespace(
            gemini_max_retries=3,
            gemini_retry_delay=0.0,
            anthropic_api_key="anthropic-key-1234567890",
            openai_api_key=None,
        ),
    )

    def _fake_generate(_prompt: str, _generation_config: dict) -> str:
        gemini_calls.append(analyzer._api_key)
        raise RuntimeError("400 invalid argument: malformed request")

    def _fake_anthropic(_prompt: str, _generation_config: dict) -> str:
        anthropic_calls.append("anthropic")
        return "anthropic-ok"

    monkeypatch.setattr(analyzer, "_generate_gemini_content", _fake_generate)
    monkeypatch.setattr(analyzer, "_call_anthropic_api", _fake_anthropic)

    result = analyzer._call_api_with_retry("prompt", {})

    assert result == "anthropic-ok"
    assert gemini_calls == [first_key]
    assert anthropic_calls == ["anthropic"]
    assert analyzer._api_key == first_key


def test_main_market_review_uses_default_analyzer_init_for_multi_key_config(monkeypatch):
    main_module = importlib.import_module("main")
    init_args: list[object] = []
    review_call: dict[str, object] = {}

    class FakeAnalyzer:
        def __init__(self, api_key=None):
            init_args.append(api_key)

        def is_available(self) -> bool:
            return True

    args = SimpleNamespace(
        debug=False,
        stocks=None,
        webui=False,
        webui_only=False,
        serve=False,
        serve_only=False,
        host="0.0.0.0",
        port=8000,
        market_review=True,
        no_notify=False,
        backtest=False,
        schedule=False,
    )
    config = SimpleNamespace(
        log_dir=".",
        validate=lambda: [],
        webui_enabled=False,
        schedule_enabled=False,
        gemini_api_key="first-key-1234567890",
        gemini_api_keys=["first-key-1234567890", "second-key-1234567890"],
        openai_api_key=None,
        bocha_api_keys=[],
        tavily_api_keys=[],
        brave_api_keys=[],
        serpapi_keys=[],
        news_max_age_days=3,
    )

    monkeypatch.setattr(main_module, "parse_arguments", lambda: args)
    monkeypatch.setattr(main_module, "get_config", lambda: config)
    monkeypatch.setattr(main_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(main_module, "_should_skip_for_market_window", lambda _config: False)
    monkeypatch.setattr("src.analyzer.GeminiAnalyzer", FakeAnalyzer)
    monkeypatch.setattr("src.notification.NotificationService", lambda: object())
    monkeypatch.setattr(
        "src.core.market_review.run_market_review",
        lambda **kwargs: review_call.update(kwargs),
    )

    assert main_module.main() == 0
    assert init_args == [None]
    assert isinstance(review_call["analyzer"], FakeAnalyzer)
