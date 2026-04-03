from src.market_analyzer import MarketAnalyzer, MarketOverview, MarketIndex


class _DummyAnalyzer:
    def is_available(self):
        return True

    def _call_api_with_retry(self, prompt, generation_config):
        return """## 📊 2026-04-03 澳股及全球宏观复盘

### 一、宏观与大盘总结
测试内容

### 二、指数与商品点评
测试内容

### 三、热点与风险解读
测试内容

### 四、后市展望
测试内容
"""


def test_template_review_hides_zero_like_placeholder_when_stats_missing():
    analyzer = MarketAnalyzer()
    overview = MarketOverview(
        date="2026-04-03",
        indices=[MarketIndex(code="^AXJO", name="ASX 200", current=7700, change_pct=0.1)],
    )

    report = analyzer._generate_template_review(overview, news=[])

    assert "上涨家数 | 0" not in report
    assert "下跌家数 | 0" not in report
    assert "关键统计（涨跌家数/涨跌停/成交额）暂不可用" in report
    assert "板块涨跌榜暂不可用" in report


def test_template_review_keeps_validated_zero_values():
    analyzer = MarketAnalyzer()
    overview = MarketOverview(
        date="2026-04-03",
        market_stats_available=True,
        sector_rankings_available=True,
        up_count=0,
        down_count=0,
        flat_count=100,
        limit_up_count=0,
        limit_down_count=0,
        total_amount=0.0,
    )

    report = analyzer._generate_template_review(overview, news=[])

    assert "上涨家数 | 0" in report
    assert "下跌家数 | 0" in report
    assert "ASX 成交额 | 0亿" in report


def test_generate_market_review_injects_unavailable_notice_when_upstream_stats_missing():
    analyzer = MarketAnalyzer(analyzer=_DummyAnalyzer())
    overview = MarketOverview(
        date="2026-04-03",
        indices=[MarketIndex(code="^AXJO", name="ASX 200", current=7700, prev_close=7680, high=7710, low=7670)],
    )

    report = analyzer.generate_market_review(overview, news=[])

    assert "市场广度/成交额统计暂不可用" in report
    assert "领涨/领跌板块统计暂不可用" in report


def test_market_review_prompt_is_dedicated_markdown_prompt():
    analyzer = MarketAnalyzer()
    overview = MarketOverview(date="2026-04-03")

    prompt = analyzer._build_review_prompt(overview, news=[])

    assert "澳股及全球宏观复盘" in prompt
    assert "禁止输出 JSON 格式" in prompt
    assert "市场广度与成交额统计" in prompt
    assert "关键统计缺失" in prompt
