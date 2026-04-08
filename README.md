# Daily Stock Analysis

[中文](README.zh-CN.md) | English

Daily Stock Analysis is a Python-based stock analysis and reporting system for manual decision support. It combines multi-source market data, LLM-generated analysis, rule-based position management, optional market review, notification delivery, and a FastAPI + React web console, with both local execution and GitHub Actions workflows supported.

The current product positioning and default runtime assumptions are centered on ASX-first workflows, with AU/US symbols supported in the same reporting flow. The default examples in this document stay ASX-only because runtime defaults still assume `MARKET_CALENDAR=ASX` and `MARKET_TIMEZONE=Australia/Sydney`. Some source comments and legacy integrations still reflect the repository's earlier A-share history, but user-facing setup guidance in this document is written for the current ASX/AU/US usage model.

## Current architecture

The current `main` branch is organized into these modules:

- **Execution & orchestration**
  - `main.py`: CLI entrypoint, runtime mode switching, scheduler/web server bootstrap, optional market-window guard, and automatic backtest trigger after runs.
  - `src/core/pipeline.py`: end-to-end stock pipeline (fetch data → analyze → position decision simulation/persistence → report generation/notification).
  - `src/scheduler.py`: scheduled execution support for local runtime.

- **Domain services**
  - `src/services/analysis_service.py`: analysis service used by API/task layer.
  - `src/services/task_service.py` + `src/services/task_queue.py`: async task submission/execution for API mode.
    - API async path uses `AnalysisTaskQueue`; `TaskService` remains only for legacy compatibility.
  - `src/services/history_service.py`, `src/services/backtest_service.py`, `src/services/stock_service.py`, `src/services/system_config_service.py`.

- **Storage & repositories**
  - `src/storage.py`: SQLAlchemy models and database manager (`analysis_history`, `backtest_results`, `backtest_summaries`, `portfolio_positions`, `account_snapshots`, `trade_journal`, etc.).
  - `src/repositories/*.py`: repository layer for history/analysis/backtest.

- **Interfaces**
  - `api/`: FastAPI app and `/api/v1/*` endpoints (analysis, history, stocks, backtest, system config).
  - `apps/dsa-web/`: React + Vite frontend.
  - `bot/`: bot platform integrations (e.g., Discord, Feishu Stream, DingTalk Stream).

- **Workflow automation**
  - `.github/workflows/daily_analysis.yml`: scheduled/manual analysis workflow.
  - `.github/workflows/init-portfolio.yml` and `.github/workflows/record-trade.yml`: manual portfolio/account updates via Actions forms.

## Setup (current, verified paths)

### 1) Local CLI run

```bash
# from repo root
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with at least stock list + one LLM provider key
# example watchlist for current defaults: BHP.AX, CBA.AX, CSL.AX
# if you mix AU/US symbols, also review MARKET_CALENDAR / MARKET_TIMEZONE
python main.py
```

### 2) Run API server / web console backend

```bash
# API only
python main.py --serve-only --host 0.0.0.0 --port 8000

# API + run analysis flow in same process
python main.py --serve
```

If frontend assets are not prebuilt, build them first:

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

- `analyzer` service: default scheduled/analyzer container command.
- `server` service: `python main.py --serve-only --host 0.0.0.0 --port ${API_PORT:-8000}`.

### 4) GitHub Actions run

- Daily/manual analysis: `.github/workflows/daily_analysis.yml`.
- Manual account initialization: `.github/workflows/init-portfolio.yml`.
- Manual trade recording: `.github/workflows/record-trade.yml`.

## Runtime modes (actual CLI behavior)

- `python main.py` → one analysis run (stocks + market review if enabled).
- `python main.py --market-review` → market-review-only mode.
- `python main.py --schedule` → local scheduled mode (`SCHEDULE_TIME`).
- `python main.py --serve-only` → API server only (no automatic analysis run).
- `python main.py --serve` → start API server plus normal analysis flow.
- `python main.py --backtest [--backtest-code CODE --backtest-days N --backtest-force]` → run backtest only.
- `python main.py --no-market-review` / `--no-notify` / `--dry-run` / `--single-notify` are supported runtime modifiers.

`--webui` and `--webui-only` are still accepted but mapped internally to `--serve` and `--serve-only`.

## Execution price basis policy

Execution/reference price basis is now explicitly configurable via `EXECUTION_PRICE_POLICY`:

- `realtime_if_available` (default): prefer realtime price, fallback to latest close.
- `close_only`: ignore realtime price and use latest close only.

Legacy compatibility:

- If `EXECUTION_PRICE_POLICY` is not set, behavior falls back to `ENABLE_REALTIME_QUOTE`:
  - `ENABLE_REALTIME_QUOTE=true` → `realtime_if_available`
  - `ENABLE_REALTIME_QUOTE=false` → `close_only`

## ASX executable sizing constraints (PR3: executable sizing realism)

To make sizing output executable for manual ASX trading support, deterministic constraints are applied in position transition math:

- **Whole-share normalization is always active** (user-visible behavior change):
  - executable target quantity is normalized to integer shares
  - deterministic report sizing text shows integer shares only (no fractional-looking share output)
- **`MIN_POSITION_DELTA_AMOUNT`** (default `0`):
  - minimum absolute position-change amount threshold
  - if `abs(delta_amount)` is below this threshold, actionable BUY/SELL intent is suppressed to HOLD/no-action
- **`MIN_ORDER_NOTIONAL`** (default `0`):
  - minimum executable order notional threshold
  - if implied order notional is below this threshold, actionable BUY/SELL intent is suppressed to HOLD/no-action

Suppression defaults are opt-in (`0` means disabled), while whole-share normalization remains always on.

## Report outputs and persisted artifacts

Current outputs on `main`:

- **Notifications**: routed through configured channels (webhook/chat/email/etc.) by `NotificationService`.
- **Markdown report files**: generated under `reports/` via `save_report_to_file`, with names like `report_YYYYMMDD.md`.
- **Logs**: written under `logs/`.
- **SQLite DB** (default `./data/stock_analysis.db`): stores market data, analysis history, portfolio/account states, and backtest results.
- **API responses**:
  - `/api/v1/analysis/*` for sync/async analysis and task state.
  - `/api/v1/history/*` for report history + portfolio summary.
  - `/api/v1/backtest/*` for run/results/performance.
  - `/api/v1/stocks/extract-from-image` for image-based symbol extraction.

## Known limitations (from current code)

- `POST /api/v1/analysis/analyze` currently supports exactly one stock per request: use `stock_code`, or provide `stock_codes` as a single-element compatibility list. If multiple unique codes are provided, the API returns `400 validation_error` and asks clients to split into multiple requests.
- API service bootstrap in `main.py` intentionally does not start when `GITHUB_ACTIONS=true`.
- Default analysis mode is read-only for account state (`ANALYSIS_READ_ONLY=true`), so normal analysis computes recommendations without writing real account changes unless explicitly disabled.
- Image extraction endpoint accepts only one uploaded file (`file`) with MIME type restrictions and a 5MB size limit.
- Some runtime comments/docs in source files still contain legacy naming or China-market integrations from earlier repository history, so internal naming is not yet fully normalized to the current ASX/AU/US product scope.

## License
See [LICENSE](LICENSE).

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md).

## Disclaimer
This project is for research, educational, and engineering validation purposes only. It does not constitute investment advice, trading advice, or any guarantee of future results. Any investment or trading decisions made using this project are solely the responsibility of the user.
