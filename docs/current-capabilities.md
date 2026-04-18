# Current Capabilities

This repository is an execution-only engine. It owns broker adapters, account
and quote reads, rebalance planning, order submission, local execution state,
reconciliation, recovery commands, audit logs, and smoke evidence. It does not
own research, AI, backtesting, raw data import, factor pipelines, or a
cross-broker account-routing platform.

## Broker Support Matrix

| Backend | Current path | Required environment | Evidence maturity | Current gaps |
| --- | --- | --- | --- | --- |
| `alpaca-paper` | Paper-only adapter with submit/query/cancel/reconcile paths. | `ALPACA_API_KEY` or `APCA_API_KEY_ID`; `ALPACA_SECRET_KEY` or `APCA_API_SECRET_KEY`. | Stable low-cost paper baseline for repeated regression and smoke runs. Default tests use fakes and do not require network access. | No live Alpaca path. |
| `longport-paper` | LongPort paper backend with broker-backed submit/query/cancel/reconcile paths. | `LONGPORT_APP_KEY`, `LONGPORT_APP_SECRET`, `LONGPORT_ACCESS_TOKEN_TEST`. Repo-local `.env` and `.env.local` are allowed for paper credentials. | Operator-supervised paper smoke has covered submit/query/reconcile/cancel basics. | Failure-mode evidence should continue to grow. |
| `longport` | LongPort real backend with broker-backed read and execution paths behind live guards. | `LONGPORT_APP_KEY`, `LONGPORT_APP_SECRET`, `LONGPORT_ACCESS_TOKEN`, and `QEXEC_ENABLE_LIVE=1` for live `--execute`. Real tokens must come from the current process or `~/.config/qexec/longport-live.env`, not repo-local `.env*` or `.envrc*`. | Operator-supervised read-only checks have covered config, preflight, account, quotes, private live config routing, and live guard behavior. | Full real submit/query/cancel/reconcile evidence is still weaker than paper smoke and must remain operator-supervised. |
| `ibkr-paper` | Local IB Gateway over TWS API paper backend for a minimal US equities slice. | Running and logged-in IB Gateway; `IBKR_HOST`, `IBKR_PORT` or `IBKR_PORT_PAPER`, `IBKR_CLIENT_ID`; optional `IBKR_ACCOUNT_ID`. | No-order evidence has shown Gateway/account/quote/rebalance/reconcile/cancel-all reachability. | Broker order, cancel, and fill evidence under valid market data is still pending. |

## Shared Execution Semantics

- `qexec rebalance --execute` has broker-backed code paths for LongPort real,
  `longport-paper`, Alpaca paper, and `ibkr-paper`, but maturity differs by
  backend as described above.
- `--account` is currently account/profile label parsing with fail-fast
  validation. It is not multi-account routing.
- LongPort real, `longport-paper`, Alpaca paper, and `ibkr-paper` adapters
  currently run with single-account semantics. Unsupported labels fail fast.
- `orders`, `exceptions`, and `order` are local tracked-state views, not
  broker-wide order book views.
- `retry` only supports zero-fill terminal tracked orders. Partial fills must
  use `cancel-rest`, `resume-remaining`, or `accept-partial`.
- Rebalance input is canonical `targets.json` with a `targets` array. Legacy
  ticker-list, weights-only documents, and workbook inputs are not public
  execution inputs.

## Credential Source Rules

- LongPort paper can use repo-local `.env` or `.env.local` for
  `LONGPORT_ACCESS_TOKEN_TEST`.
- LongPort real defaults to `~/.config/qexec/longport-live.env`, then the
  current process environment. Repo-local `.env*` and `.envrc*` files must not
  contain real LongPort tokens.
- `QEXEC_ENABLE_LIVE` is checked in the current process first, then
  `~/.config/qexec/longport-live.env`.
- `qexec config --broker longport` and `qexec config --broker longport-paper`
  report the effective LongPort App Key, Secret, Token, Region, and Overnight
  sources so operators can verify paper versus user-private live routing.
- `LONGBRIDGE_*` names are deprecated compatibility fallbacks. New examples and
  operator instructions should use `LONGPORT_*`.

## Test Entry Points

- Fast default tests: `uv run pytest`
- End-to-end tests: `uv run pytest -m e2e`
- Integration tests: `uv run pytest -m integration`
- Coverage is opt-in, for example:

```bash
uv run pytest --cov=src/quant_execution_engine --cov-report=term-missing -m 'not integration and not e2e and not slow'
```

Broker-backed smoke evidence is operator-supervised and depends on the backend
environment. The smoke runbooks describe the required credentials and local
runtime prerequisites for each backend.

## Outputs

- Rebalance audit logs: `outputs/orders/*.jsonl`
- Local execution state: `outputs/state/*.json`
- Smoke evidence: `outputs/evidence/*.json`
- Evidence bundles: `outputs/evidence-bundles/*`

`outputs/` is ignored by Git. Evidence files are local review artifacts, not
tracked fixtures.

## Project Tools

Operator-facing smoke tools:

- `project_tools/smoke_signal_harness.py`
- `project_tools/smoke_target_harness.py`
- `project_tools/smoke_operator_harness.py`

Maintainer-only utilities:

- `project_tools/export_repo_source.py`
- `project_tools/package.sh`

The maintainer utilities are not product workflows. They exist for source
export and archive packaging tasks.
