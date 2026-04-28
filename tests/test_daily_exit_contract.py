from types import SimpleNamespace

import main


class _FakeResult:
    code = "BHP.AX"
    name = "BHP"
    operation_advice = "HOLD"
    sentiment_score = 1
    trend_prediction = "flat"

    def get_emoji(self):
        return "*"


class _FakeNotifier:
    def is_available(self):
        return False

    def generate_dashboard_report(self, _results):
        return "dashboard"

    def send(self, *_args, **_kwargs):
        return True


class _FakeFeishuDocManager:
    def is_configured(self):
        return False


class _FakePipeline:
    results = []

    def __init__(self, *_args, **_kwargs):
        self.notifier = _FakeNotifier()
        self.analyzer = object()
        self.search_service = object()

    def run(self, *_args, **_kwargs):
        return self.results


def _args(**overrides):
    values = {
        "debug": False,
        "stocks": None,
        "webui": False,
        "webui_only": False,
        "serve": False,
        "serve_only": False,
        "host": "0.0.0.0",
        "port": 8000,
        "market_review": False,
        "no_market_review": False,
        "no_notify": True,
        "single_notify": False,
        "no_context_snapshot": False,
        "dry_run": False,
        "workers": 1,
        "backtest": False,
        "schedule": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _config(**overrides):
    values = {
        "log_dir": ".",
        "validate": lambda: [],
        "webui_enabled": False,
        "schedule_enabled": False,
        "schedule_time": "07:20",
        "schedule_run_immediately": True,
        "market_review_enabled": True,
        "single_stock_notify": False,
        "merge_email_notification": False,
        "market_review_push_enabled": True,
        "market_review_empty_results_fallback_enabled": False,
        "analysis_delay": 0,
        "backtest_enabled": False,
        "gemini_api_key": None,
        "openai_api_key": None,
        "bocha_api_keys": [],
        "tavily_api_keys": [],
        "brave_api_keys": [],
        "serpapi_keys": [],
        "news_max_age_days": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_common(monkeypatch, args, config):
    monkeypatch.setattr(main, "parse_arguments", lambda: args)
    monkeypatch.setattr(main, "get_config", lambda: config)
    monkeypatch.setattr(main, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(main, "_should_skip_for_market_window", lambda _config: False)
    monkeypatch.setattr(main, "StockAnalysisPipeline", _FakePipeline)
    monkeypatch.setattr("src.feishu_doc.FeishuDocManager", _FakeFeishuDocManager)
    monkeypatch.setattr("src.notification.NotificationService", lambda: _FakeNotifier())


def test_full_mode_exits_one_when_no_stock_or_market_report(monkeypatch):
    _FakePipeline.results = []
    args = _args()
    config = _config()
    _patch_common(monkeypatch, args, config)
    monkeypatch.setattr(main, "run_market_review", lambda **_kwargs: None)

    assert main.main() == 1


def test_full_mode_exits_zero_when_market_report_exists_without_stock_results(monkeypatch):
    _FakePipeline.results = []
    args = _args()
    config = _config()
    _patch_common(monkeypatch, args, config)
    monkeypatch.setattr(main, "run_market_review", lambda **_kwargs: "market report")

    assert main.main() == 0


def test_stocks_only_exits_one_when_all_stocks_fail(monkeypatch):
    _FakePipeline.results = []
    args = _args(no_market_review=True)
    config = _config()
    _patch_common(monkeypatch, args, config)

    assert main.main() == 1


def test_stocks_only_keeps_partial_success_green(monkeypatch):
    _FakePipeline.results = [_FakeResult()]
    args = _args(no_market_review=True)
    config = _config()
    _patch_common(monkeypatch, args, config)

    assert main.main() == 0


def test_market_only_exits_one_when_no_report(monkeypatch):
    args = _args(market_review=True)
    config = _config()
    _patch_common(monkeypatch, args, config)
    monkeypatch.setattr("src.core.market_review.run_market_review", lambda **_kwargs: None)

    assert main.main() == 1


def test_market_only_exits_zero_when_report_exists(monkeypatch):
    args = _args(market_review=True)
    config = _config()
    _patch_common(monkeypatch, args, config)
    monkeypatch.setattr("src.core.market_review.run_market_review", lambda **_kwargs: "market report")

    assert main.main() == 0


def test_market_window_skip_remains_success(monkeypatch):
    args = _args()
    config = _config()
    _patch_common(monkeypatch, args, config)
    monkeypatch.setattr(main, "_should_skip_for_market_window", lambda _config: True)

    assert main.main() == 0
