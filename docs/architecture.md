# FLOPPI hybrid architecture decisions

## Cloud responsibilities
- API gateway and orchestration
- Supabase Auth and PostgreSQL
- User notification preferences and event history
- Mobile/web/Telegram API surface

## Main PC responsibilities (phase 1)
- Local inference and feature calculations
- Controlled experiments in a future isolated sandbox
- Outbound heartbeat to cloud API
- No inbound public port forwarding

## Availability
Cloud services remain reachable when the PC is off. Local compute tasks are queued
or marked unavailable until the PC reconnects. The cloud must not pretend that a
local analysis has run when the node is offline.

## Security gates before public launch
1. Supabase Auth token verification in every user endpoint.
2. User identity derived from token, never from a URL parameter.
3. Per-user authorization and rate limiting.
4. HTTPS only; secrets in deployment secret manager.
5. Per-node worker credentials stored as SHA-256 hashes, with expiry and revocation.
6. CORS allowlist for exact production origins.
7. Audit logging and backup/restore tests.
8. Sandbox isolation, CPU/RAM/time limits and manual promotion approval.

## Trading boundary
Educational analytics, synthetic/historical data, backtesting and paper trading only.
No broker credentials, real-money order placement or autonomous live trading.

## FLOPPI 0.4.0 baseline implementation

The multimarket schema is versioned in migration `002_multimarket_backtesting.sql`.
It adds seeded DEMO markets/assets, normalized OHLCV candles, provider metadata,
ingestion and quality logs, user-owned strategies, queue-backed runs, trades,
and metrics. Client RLS is enabled; the service-role key is used only by the API.

The worker's flow is outbound-only: it sends a node-bound, token-authenticated heartbeat,
claims work through `claim_backtest_run` (using row locks and `SKIP LOCKED`),
executes simulations locally, and atomically posts trades and metrics through
`complete_backtest_run`. A worker that does not reconnect leaves jobs pending;
stale running jobs become eligible for reclamation after one hour. Runs retain a
fingerprint of their OHLCV input and fail if those candles change before execution.

The implemented provider is deterministic synthetic data, explicitly labeled
`DEMO`. Indicators use rolling averages, Wilder RSI/ATR, EMA-based MACD,
population-standard-deviation Bollinger Bands, and cumulative VWAP over the
requested series. Strategy signals execute no earlier than the following bar's
open, with configurable simulated commission and slippage. Processing is capped
at 5,000 candles per run, and the API limits each account to five pending runs.

Production user writes validate Supabase Bearer JWTs and scope resources to the
verified user ID. Market history is public; node listings and operational
telemetry require a verified administrator outside explicit development mode.
Notification preferences are restricted to the authenticated owner in
production. External providers, Flutter,
Telegram, adaptive AI, operational rate limiting, and backup/restore drills
remain outside this milestone.

## Hybrid engine 0.5.0

The hybrid analyzer uses three method families to reduce correlated-vote bias:

1. Trend: SMA 20/50, with EMA 12/26 as a consistency check or fallback.
2. Momentum: MACD and RSI are combined into one family. If they disagree, the
   family is marked internally conflicted and does not cast a directional vote.
3. Price-volume: latest close is compared with cumulative VWAP for the requested
   candle sample. If VWAP is unavailable, this family is unavailable.

ATR is descriptive volatility context and never contributes a bullish/bearish
vote. At least two directional families are required. An even split or thinner
evidence causes an abstention. The reported score is a raw agreement ratio among
available directional families, not a probability, calibrated confidence, or
forecast. All outputs remain historical DEMO analysis only.
