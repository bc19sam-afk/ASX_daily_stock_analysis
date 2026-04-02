# ASX 深度代码审查（2026-04-02）

> 范围：当前仓库主线代码（本地分支 `work@6a34415`）。
>
> 说明：本次审查在仓库内未找到用户提到的 4 份运行证据文件（`report_20260401.md`、`stock_analysis_20260401.log`、`stock_analysis_debug_20260401.log`、2026-04-01 PDF）。因此本报告以“代码路径 + 现有测试 + 日志模板”做根因分析，并把无法直接核验的部分标为“待证据回放确认”。

## Findings（按严重度）

### F1（高）：`realtime` 口径与 `fallback` 标签被硬编码混淆，导致“执行参考价是 realtime”与“行情来源=降级兜底”可同时出现

- 现象（从代码推断）：
  - 执行价基准由 `execution_price_source` 判定，只要 `enhanced_context.realtime.price > 0` 就会被记为 `realtime`。
  - 展示层“行情来源”取自 `market_snapshot.source`，而 AU/US 的 yfinance 实现把 `source` 固定写成 `RealtimeSource.FALLBACK`。
- 代码路径：
  - 执行价来源判定：`src/core/pipeline.py::_resolve_execution_price_source`。
  - 报告基准统计：`src/notification.py::_classify_price_basis` / `_build_data_baseline_lines`。
  - 行情来源显示：`src/notification.py::_append_market_snapshot`（`fallback -> 降级兜底` 映射）。
  - 根因触发点：`data_provider/yfinance_fetcher.py::get_realtime_quote` 中 `source=RealtimeSource.FALLBACK`。
- 最可能根因：
  - 系统把“数据通道是否为实时拉取”和“供应商标签是否叫 fallback”混成同一语义维度。
  - `RealtimeSource.FALLBACK` 在 yfinance 路径被当作默认值复用，而不是“真实兜底状态”。
- 最小 PR 方案：
  - 新增价格 provenance 枚举：`provider_id`（yfinance/akshare/efinance）与 `latency_class`（realtime/delayed/close_proxy/stored_value）分离。
  - yfinance 路径将 `source` 改为 `yfinance`（或新增枚举值），并单独给出 `latency_class`。
  - 报告层把“执行基准”与“行情来源”并排展示，禁止复用同一字段解释两种口径。
- 建议测试：
  - 构造 `realtime.price>0 + source=yfinance`，断言 baseline 计入 realtime 且行情来源显示 yfinance。
  - 构造 `close_only` 与 `stored_market_value` 路径，断言不会误记为 realtime。

### F2（高）：组合概览估值路径已支持 `stored_market_value` 回退，但报告面未披露每只持仓估值来源/时点，存在“对用户不够诚实”的信息缺口

- 现象（从代码推断）：
  - 系统内部已记录 `valuation_source`（`report_time_price` vs `stored_market_value_fallback`），并在日志输出 fallback 代码列表。
  - 但 A 段 Portfolio Overview 表格只展示名称/数量/权重，不展示估值来源、价格时间戳、是否在今日分析覆盖内。
- 代码路径：
  - 估值回退逻辑：`src/notification.py::_build_report_time_portfolio_overview`。
  - fallback 日志：`Portfolio overview price fallback ...`。
  - 展示表格缺口：`src/notification.py::generate_dashboard_report`（A 段持仓表）。
- 最可能根因：
  - 数据层已经有 provenance 字段，但模板层没把它暴露给最终报告。
- 最小 PR 方案：
  - 持仓行新增字段：`valuation_source`、`price_timestamp`、`included_in_today_analysis`。
  - A 段表格新增“估值来源/时点/是否今日分析”三列；并在段落脚注汇总 fallback 规模（n/m）。
- 建议测试：
  - 单测覆盖“部分持仓无 report-time price”时，表格列与脚注同步出现。
  - 验证 summary / section C / overview 的来源披露一致性。

### F3（中高）：Section C 仅展示“分析标的”的 simulated target weight，未显式输出 `target_cash_weight` 与“未纳入分析持仓”，组合守恒对用户不可验证

- 现象（从代码推断）：
  - C 段 `Simulated Target Allocation` 逐行输出 `target_weight` 与 `delta_amount`，但没有现金目标权重，也没有“未分析持仓残余桶”。
  - A 段是全账户 executed state，C 段是 analyzed universe 的建议 state；两者天然不闭环，但报告没有解释闭环公式。
- 代码路径：
  - C 段表格生成：`src/notification.py::_build_simulated_target_allocation_table`。
  - C 段挂载：`src/notification.py::generate_dashboard_report`。
- 最可能根因：
  - 模拟分配输出只针对 result list（今日分析股票），没有组合级 reconciliation 层。
- 最小 PR 方案：
  - 新增 C 段汇总行：`target_cash_weight`、`unmanaged_holdings_weight`、`analyzed_target_weight_sum`、`residual_weight`。
  - 统一披露等式：`analyzed + unmanaged + cash = 100%`。
- 建议测试：
  - 构造“账户有 GMG.AX，但今日未分析”场景，断言 C 段可见 `unmanaged_holdings_weight > 0`。
  - 断言 `delta_amount` 合计与权重合计不会让用户误解为“总和应等于 100%（仅分析子集）”。

### F4（中）：字段 provenance 跨层未统一，可能出现“表格 N/A 但分析文案给出确定结论”的可验证性缺口

- 现象（从代码推断）：
  - market snapshot 的 `volume_ratio/turnover_rate` 直接来自 realtime quote，缺失时显示 N/A。
  - 但 AI 输出的 `dashboard.data_perspective.volume_analysis` 是模型生成文本，当前没有与输入字段做一致性约束或校验。
- 代码路径：
  - 快照字段来源：`src/analyzer.py::_build_market_snapshot`。
  - 文案输出：`src/notification.py` 在“数据透视/量能”直接渲染 `dashboard.volume_analysis`。
  - prompt 中并无“若输入为 N/A 则禁止下结论”的强制校验逻辑（仅有一般性“严禁编造”提示）。
- 最可能根因：
  - 结构化字段与 LLM 文案缺少 post-parse consistency check。
- 最小 PR 方案：
  - 增加 `provenance_guard`：当 snapshot 字段 N/A 时，自动降级 volume_analysis 为“无可靠量能数据”。
  - 为关键字段附 `as_of` 与 `source_layer`，并在模板中统一显示。
- 建议测试：
  - 构造 `volume_ratio=None`，断言最终文案不得出现“放量/缩量 + 明确量比数值”。
  - 构造 mixed-date，断言指标段落显示日期标签。

### F5（中）：Search/News grounding 缺少实体消歧与交易所约束，错误结果可进入 LLM prompt

- 现象（从代码推断）：
  - 对外盘搜索查询主要用 `{stock_code}` 或 `{stock_name} {stock_code}`，但对结果缺少基于 ticker+exchange+legal name 的后置过滤。
  - `format_intel_report` 默认把检索结果标题直接喂入 prompt；若串台结果混入，将污染模型判断。
- 代码路径：
  - 查询构造：`src/search_service.py::search_stock_news` / `search_comprehensive_intel`。
  - 结果消费：`src/search_service.py::format_intel_report`，随后进入 `src/core/pipeline.py` 的 analyzer 输入。
- 最可能根因：
  - 仅做“搜索成功/失败”层控制，缺实体一致性评分与剔除规则。
- 最小 PR 方案：
  - 增加 `entity_filter`：
    1) URL/标题命中 ticker（`BHP.AX`）或标准名（`BHP Group`）至少其一；
    2) exchange 关键词（ASX/Australia）弱约束加分；
    3) 低分结果不入 prompt，仅入调试区。
- 建议测试：
  - 伪造同名异股结果（如 US/UK 同名公司），断言不会进入最终 intel prompt。

## Do not reopen（建议不重复开 PR）

1. **“确定性动作与 AI 文案冲突时，抑制可执行误导”**：已在报告层明确“AI 次要评论/非执行”并有冲突中性化分支，且有专项测试。
2. **`execution price policy` 枚举与兼容迁移**：配置层已统一到 `realtime_if_available/close_only` 并有回归测试。
3. **ASX 可执行股数约束（整数股、资金约束）**：仓位引擎已有可执行数量与 affordability 回退逻辑及大量 accounting 测试。
4. **`report_type` 语义标准化（workflow/config/runtime/API）**：`detailed -> full` 兼容已覆盖配置和 API 请求验证。

> 注：上述“不重开”仅针对主题本体；若在本次新问题中发现“已修主题在新 surface 未披露/未接通”，建议以“小范围补洞 PR”而非重做原 PR。

## Proposed PR Plan（建议拆分 4 个 PR）

### PR-A（先做）
- 标题建议：`Normalize price provenance: separate provider, latency class, and execution basis`
- 边界：仅处理价格来源语义与展示层标签，不改仓位算法。
- 包含：F1。
- 为什么单拆：这是所有下游披露（A/B/C 段、日志、审计）的前置语义层。

### PR-B（依赖 PR-A）
- 标题建议：`Expose portfolio valuation provenance in overview and align cross-section disclosures`
- 边界：A 段持仓表与概览脚注，新增来源/时点/覆盖标识。
- 包含：F2。
- 为什么单拆：主要是报告披露面与 DTO 扩展，风险低且可快速验证。

### PR-C（可与 PR-B 并行，建议稍后）
- 标题建议：`Add allocation reconciliation outputs for simulated targets (cash/unmanaged/residual)`
- 边界：C 段组合守恒解释，不触发真实持仓写入逻辑。
- 包含：F3。
- 为什么单拆：属于“语义完整性”改进，和价格 provenance 可独立验收。

### PR-D（最后）
- 标题建议：`Harden search grounding with ticker-exchange-name entity disambiguation`
- 边界：搜索 query 与结果过滤；新增调试可见性；不改 LLM 主提示结构。
- 包含：F5（可附带 F4 的字段一致性守卫）。
- 为什么单拆：涉及外部检索召回/精确率权衡，需独立回归与离线夹具。

依赖关系：`PR-A -> PR-B`；`PR-C` 可并行；`PR-D` 建议最后（需要额外测试夹具）。

## Quick wins vs deep fixes

### Quick wins（1 个 PR 可落地）
- yfinance `source` 标签纠偏（从 fallback 分离）。
- A 段持仓表增加 `valuation_source` 与 fallback 脚注。
- C 段增加 `target_cash_weight` 与 residual 汇总行。

### Deep fixes（先补测试夹具/审计脚本）
- 搜索实体消歧（需要构造“同名异股”样本集与稳定回放）。
- LLM 文案与结构化字段一致性校验（需要 prompt-parse 后审计器）。

### 文案修补 vs 数据流问题
- 文案修补：A/C 段标签、脚注、来源说明。
- 数据流语义：价格 provenance 拆层（provider/latency/execution basis）、search grounding filter、LLM consistency guard。
