# Daily Stock Analysis

中文 | [English](README.md)

Daily Stock Analysis 是一个基于 Python 的股票分析与报告系统，整合了多源市场数据、LLM 生成分析、基于规则的仓位管理、可选的大盘复盘、通知分发，以及 FastAPI + React Web 控制台，并支持本地运行与 GitHub Actions 工作流。

## 当前架构

当前 `main` 分支按以下模块组织：

- **执行与编排**
  - `main.py`：CLI 入口、运行模式切换、调度器/Web 服务器启动、可选交易时段保护，以及运行后自动触发回测。
  - `src/core/pipeline.py`：端到端股票流程（拉取数据 → 分析 → 仓位决策模拟/持久化 → 报告生成/通知）。
  - `src/scheduler.py`：本地运行的定时调度支持。

- **领域服务**
  - `src/services/analysis_service.py`：供 API/任务层使用的分析服务。
  - `src/services/task_service.py` + `src/services/task_queue.py`：API 模式下的异步任务提交/执行。
  - `src/services/history_service.py`、`src/services/backtest_service.py`、`src/services/stock_service.py`、`src/services/system_config_service.py`。

- **存储与仓储层**
  - `src/storage.py`：SQLAlchemy 模型与数据库管理器（`analysis_history`、`backtest_results`、`backtest_summaries`、`portfolio_positions`、`account_snapshots`、`trade_journal` 等）。
  - `src/repositories/*.py`：history/analysis/backtest 的仓储层。

- **接口层**
  - `api/`：FastAPI 应用与 `/api/v1/*` 接口（analysis、history、stocks、backtest、system config）。
  - `apps/dsa-web/`：React + Vite 前端。
  - `bot/`：机器人平台集成（如 Discord、Feishu Stream、DingTalk Stream）。

- **工作流自动化**
  - `.github/workflows/daily_analysis.yml`：定时/手动分析工作流。
  - `.github/workflows/init-portfolio.yml` 和 `.github/workflows/record-trade.yml`：通过 Actions 表单进行手动账户初始化与交易记录。

## 安装与运行（当前、已验证路径）

### 1) 本地 CLI 运行

```bash
# from repo root
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with at least stock list + one LLM provider key
python main.py
```

### 2) 运行 API 服务 / Web 控制台后端

```bash
# API only
python main.py --serve-only --host 0.0.0.0 --port 8000

# API + run analysis flow in same process
python main.py --serve
```

若前端静态资源尚未构建，请先执行：

```bash
cd apps/dsa-web
npm install
npm run build
cd ../..
```

### 3) Docker / Compose

```bash
docker compose -f docker/docker-compose.yml up -d
```

- `analyzer` 服务：默认的定时/分析容器命令。
- `server` 服务：`python main.py --serve-only --host 0.0.0.0 --port ${API_PORT:-8000}`。

### 4) GitHub Actions 运行

- 每日/手动分析：`.github/workflows/daily_analysis.yml`。
- 手动账户初始化：`.github/workflows/init-portfolio.yml`。
- 手动交易记录：`.github/workflows/record-trade.yml`。

## 运行模式（实际 CLI 行为）

- `python main.py` → 执行一次分析（股票 + 可选大盘复盘）。
- `python main.py --market-review` → 仅大盘复盘模式。
- `python main.py --schedule` → 本地定时模式（`SCHEDULE_TIME`）。
- `python main.py --serve-only` → 仅 API 服务（不自动执行分析）。
- `python main.py --serve` → 启动 API 服务并执行常规分析流程。
- `python main.py --backtest [--backtest-code CODE --backtest-days N --backtest-force]` → 仅执行回测。
- `python main.py --no-market-review` / `--no-notify` / `--dry-run` / `--single-notify` 为受支持的运行修饰参数。

`--webui` 与 `--webui-only` 仍可使用，但内部会映射到 `--serve` 与 `--serve-only`。

## 报告输出与持久化产物

当前 `main` 分支输出如下：

- **通知**：由 `NotificationService` 通过配置的通道（webhook/chat/email 等）发送。
- **Markdown 报告文件**：通过 `save_report_to_file` 生成到 `reports/`，文件名如 `report_YYYYMMDD.md`。
- **日志**：写入 `logs/`。
- **SQLite 数据库**（默认 `./data/stock_analysis.db`）：存储市场数据、分析历史、仓位/账户状态和回测结果。
- **API 响应**：
  - `/api/v1/analysis/*`：同步/异步分析与任务状态。
  - `/api/v1/history/*`：报告历史与组合摘要。
  - `/api/v1/backtest/*`：运行/结果/绩效。
  - `/api/v1/stocks/extract-from-image`：基于图片的股票代码提取。

## 已知限制（基于当前代码）

- `POST /api/v1/analysis/analyze` 当前单次请求仅支持一只股票：可使用 `stock_code`，或使用仅含一个元素的 `stock_codes` 兼容传参。若提供多个去重后股票代码，接口会返回 `400 validation_error` 并提示拆分为多次请求。
- 当 `GITHUB_ACTIONS=true` 时，`main.py` 中 API 服务启动逻辑会按设计不启动。
- 默认分析模式对账户状态为只读（`ANALYSIS_READ_ONLY=true`），因此常规分析会计算建议，但除非显式关闭该设置，否则不会写入真实账户变更。
- 图片提取接口只接受一个上传文件（`file`），并带有 MIME 类型限制与 5MB 大小限制。
- 源码中的部分运行注释/文档仍保留历史命名（A股/ASX 混用），因此代码/注释命名尚未完全统一。

## 许可证
见 [LICENSE](LICENSE)。

## 贡献指南
见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 免责声明
本项目仅供研究、学习和工程验证使用，不构成任何投资建议、交易建议或收益承诺。基于本项目输出所做的任何投资或交易决策，风险均由使用者自行承担。
